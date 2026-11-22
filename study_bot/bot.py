"""Discordクライアント本体：イベント処理と定期タスク。"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import discord
from discord.ext import tasks

from . import music as music_mod
from .config import Settings
from .db import Database
from .formatting import goal_text, ranking_text
from .pomodoro import PHASE_LABELS, SHORT_BREAK, WORK, PomodoroConfig, PomodoroSession
from .timeutil import date_key, day_bounds, format_duration, is_due, local_dt, week_bounds
from .tracking import is_study_channel, reconcile, transition

log = logging.getLogger(__name__)

VoiceLike = discord.VoiceChannel | discord.StageChannel


def humans(channel: VoiceLike | None) -> list[discord.Member]:
    if channel is None:
        return []
    return [m for m in channel.members if not m.bot]


class StudyBot(discord.Client):
    def __init__(self, settings: Settings, db: Database | None = None):
        intents = discord.Intents.default()  # guilds と voice_states を含む。特権Intentは不要
        intents.message_content = False
        super().__init__(intents=intents)
        self.settings = settings
        self.tz = settings.tz
        self.db = db or Database(settings.db_path)
        self.tree = discord.app_commands.CommandTree(self)
        self.pomodoros: dict[int, PomodoroSession] = {}  # voice channel id -> session
        self.music: dict[int, music_mod.GuildMusic] = {}  # guild id -> state
        self._idle_voice: set[int] = set()
        self._auto_locks: dict[int, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---- 起動 -----------------------------------------------------------
    async def setup_hook(self) -> None:
        from .commands import register_commands

        closed = self.db.close_stale_sessions()
        if closed:
            log.info("前回停止時に開いていたセッション %d 件を閉じました", closed)
        register_commands(self)
        if self.settings.dev_guild_id:
            guild = discord.Object(id=self.settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("開発用ギルドにコマンド %d 件を同期しました", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("グローバルコマンド %d 件を同期しました（反映に時間がかかる場合があります）",
                     len(synced))
        self.minute_loop.start()
        self.pomodoro_loop.start()
        self.cleanup_loop.start()

    async def on_ready(self) -> None:
        log.info("ログイン: %s（%d サーバー）", self.user, len(self.guilds))
        for guild in self.guilds:
            self.reconcile_guild(guild)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        self.reconcile_guild(guild)

    async def close(self) -> None:
        now = time.time()
        for s in self.db.open_sessions():
            self.db.end_session(s.guild_id, s.user_id, now)
        await super().close()
        self.db.close()

    # ---- 勉強VCの判定と記録 ---------------------------------------------
    def is_study(self, guild: discord.Guild, channel_id: int | None) -> bool:
        afk = guild.afk_channel.id if guild.afk_channel else None
        return is_study_channel(channel_id, self.db.study_channels(guild.id), afk)

    def present_members(self, guild: discord.Guild) -> dict[int, int]:
        present: dict[int, int] = {}
        for channel in [*guild.voice_channels, *guild.stage_channels]:
            if not self.is_study(guild, channel.id):
                continue
            for member in humans(channel):
                present[member.id] = channel.id
        return present

    def reconcile_guild(self, guild: discord.Guild) -> None:
        now = time.time()
        to_end, to_start = reconcile(self.db.open_sessions(guild.id), self.present_members(guild))
        for uid in to_end:
            self.db.end_session(guild.id, uid, now)
        for uid, cid in to_start:
            self.db.start_session(guild.id, uid, cid, now)
        if to_end or to_start:
            log.info("%s: 終了 %d / 開始 %d で記録を同期", guild.name, len(to_end), len(to_start))

    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState,
                                    after: discord.VoiceState) -> None:
        guild = member.guild
        if member.bot:
            if self.user and member.id == self.user.id and after.channel is None:
                state = self.music.pop(guild.id, None)
                if state:
                    state.clear()
            return
        now = time.time()
        b = before.channel.id if before.channel else None
        a = after.channel.id if after.channel else None
        for action, cid in transition(b, a, lambda c: self.is_study(guild, c)):
            if action == "start":
                self.db.start_session(guild.id, member.id, cid, now)
            else:
                secs = self.db.end_session(guild.id, member.id, now)
                if secs is not None:
                    await self.check_goal(guild, member.id, cid, now)
                    log.info("%s が %s 勉強しました", member, format_duration(secs))
        if before.channel and before.channel != after.channel:
            await self._stop_pomodoro_if_empty(before.channel)
        auto_id = self.db.get_config(guild.id).auto_channel_id
        if a is not None and a == auto_id and b != a:
            task = asyncio.create_task(self._auto_start_on_join(member, after.channel))
            self._tasks.add(task)  # 実行中に参照が消えないよう保持する
            task.add_done_callback(self._tasks.discard)

    # ---- 自動開始（ポモドーロ＋音楽） --------------------------------------------
    async def _auto_start_on_join(self, member: discord.Member, channel: VoiceLike) -> None:
        try:
            lines, started = await self.auto_start(member.guild, channel, member.id)
        except Exception:
            log.exception("自動開始に失敗")
            return
        if started:
            await self.safe_send(channel, f"🚀 {member.mention} が入室したので集中セッションを開始しました。\n"
                                 + "\n".join(lines))

    async def auto_start(self, guild: discord.Guild, channel: VoiceLike,
                         starter_id: int) -> tuple[list[str], bool]:
        """設定に従ってポモドーロと音楽を開始する。(結果の行, 何か開始したか) を返す。"""
        lock = self._auto_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            cfg = self.db.get_config(guild.id)
            lines: list[str] = []
            started = False
            if cfg.auto_pomodoro != 0:
                if channel.id in self.pomodoros:
                    lines.append("🍅 ポモドーロは実行中です。")
                else:
                    d = self.pomodoro_defaults(guild.id)
                    self.pomodoros[channel.id] = PomodoroSession.start(
                        guild.id, channel.id, starter_id, d, time.time())
                    lines.append(f"🍅 ポモドーロ開始：**{d.work_min}分**集中 → {d.short_break_min}分休憩"
                                 f"（{d.long_break_every}回ごとに{d.long_break_min}分）")
                    started = True
            if cfg.auto_music != 0:
                voice = guild.voice_client
                state = self.music.get(guild.id)
                if (isinstance(voice, discord.VoiceClient) and voice.channel == channel
                        and state is not None and state.current is not None):
                    lines.append(f"🎵 再生中です：**{state.current.title}**")
                else:
                    try:
                        voice = await self.connect_voice(channel)
                        source = self.music_source(guild.id)
                        query = (cfg.auto_music_query or "").strip()
                        if query:
                            tracks, playlist = await music_mod.resolve(query, source, starter_id)
                        else:
                            tracks, playlist = [await music_mod.recommend(None, source, starter_id)], None
                        state = self.music_for(guild.id)
                        was_idle = state.current is None
                        if was_idle:
                            state.loop_mode = "all"  # 集中中は流し続ける
                        playing, _added = await self.queue_tracks(guild, voice, tracks)
                        name = playlist or tracks[0].title
                        lines.append(f"🎵 {'再生開始' if playing else 'キューに追加'}：**{name}**")
                        started = True
                    except music_mod.MusicError as e:
                        lines.append(f"🎵 音楽を開始できませんでした：{e}")
            if not lines:
                lines.append("自動開始する機能がオフになっています（/setup の「自動開始」で設定）。")
            return lines, started

    async def stop_session(self, guild: discord.Guild, channel: VoiceLike) -> list[str]:
        """VCのポモドーロと音楽を止める。"""
        lines = []
        session = self.pomodoros.pop(channel.id, None)
        if session:
            lines.append(f"🍅 ポモドーロを終了しました（作業{session.completed_work}回完了）。")
        voice = guild.voice_client
        if isinstance(voice, discord.VoiceClient) and voice.channel == channel:
            state = self.music.pop(guild.id, None)
            if state:
                state.clear()
            await voice.disconnect(force=True)
            lines.append("🎵 音楽を止めて退出しました。")
        return lines

    # ---- 通知先 ---------------------------------------------------------
    def notify_target(self, guild: discord.Guild,
                      fallback_channel_id: int | None) -> discord.abc.Messageable | None:
        cfg = self.db.get_config(guild.id)
        for cid in (cfg.notify_channel_id, fallback_channel_id):
            if cid and (ch := guild.get_channel(cid)) is not None:
                return ch  # VoiceChannel もテキストチャットとして送信できる
        return None

    async def safe_send(self, target: discord.abc.Messageable | None, *args, **kwargs) -> bool:
        if target is None:
            return False
        try:
            await target.send(*args, **kwargs)
            return True
        except discord.HTTPException as e:
            log.warning("送信失敗 (%s): %s", getattr(target, "id", "?"), e)
            return False

    # ---- 目標 -----------------------------------------------------------
    async def check_goal(self, guild: discord.Guild, user_id: int,
                         channel_id: int | None, now: float) -> None:
        goal = self.db.get_goal(guild.id, user_id)
        if goal is None:
            return
        minutes, last = goal
        today = date_key(now, self.tz)
        if last == today:
            return
        lo, hi = day_bounds(now, self.tz)
        done = self.db.user_seconds(guild.id, user_id, lo, hi, now)
        if done < minutes * 60:
            return
        self.db.mark_goal_achieved(guild.id, user_id, today)
        await self.safe_send(
            self.notify_target(guild, channel_id),
            f"🎉 <@{user_id}> 今日の目標 **{format_duration(minutes * 60)}** を達成しました！\n"
            f"{goal_text(done, minutes)}")

    # ---- 定期処理（毎分） -------------------------------------------------
    @tasks.loop(seconds=60)
    async def minute_loop(self) -> None:
        now = time.time()
        self.db.heartbeat(now)
        for s in self.db.open_sessions():
            guild = self.get_guild(s.guild_id)
            if guild:
                await self.check_goal(guild, s.user_id, s.channel_id, now)
        await self._send_reminders(now)
        await self._post_rankings(now)
        await self._leave_idle_voice()

    @minute_loop.before_loop
    async def _before_minute(self) -> None:
        await self.wait_until_ready()

    @minute_loop.error
    async def _minute_error(self, error: BaseException) -> None:
        log.exception("minute_loop でエラー", exc_info=error)

    async def _send_reminders(self, now: float) -> None:
        today = date_key(now, self.tz)
        studying = {(s.guild_id, s.user_id) for s in self.db.open_sessions()}
        for guild_id, user_id, hhmm, last in self.db.all_reminders():
            if not is_due(now, self.tz, hhmm, last):
                continue
            self.db.mark_reminder_sent(guild_id, user_id, today)
            guild = self.get_guild(guild_id)
            if guild is None or (guild_id, user_id) in studying:
                continue
            lo, hi = day_bounds(now, self.tz)
            done = self.db.user_seconds(guild_id, user_id, lo, hi, now)
            goal = self.db.get_goal(guild_id, user_id)
            if goal and goal[1] == today:
                continue  # 今日の目標は達成済み
            body = f"⏰ **{guild.name}** の勉強リマインドです。今日はここまで {format_duration(done)}。"
            if goal:
                body += f"\n目標: {goal_text(done, goal[0])}"
            body += "\n勉強VCに参加して始めましょう！"
            user = self.get_user(user_id)
            try:
                user = user or await self.fetch_user(user_id)
                await user.send(body)
            except discord.HTTPException:
                # DMを受け取れない場合は通知チャンネルでメンションする
                await self.safe_send(self.notify_target(guild, None), f"<@{user_id}> {body}")

    async def _post_rankings(self, now: float) -> None:
        for cfg in self.db.all_configs():
            if not (cfg.ranking_channel_id and cfg.ranking_time):
                continue
            if not is_due(now, self.tz, cfg.ranking_time, cfg.last_ranking_date):
                continue
            self.db.update_config(cfg.guild_id, last_ranking_date=date_key(now, self.tz))
            guild = self.get_guild(cfg.guild_id)
            channel = guild.get_channel(cfg.ranking_channel_id) if guild else None
            if channel is None:
                continue
            embeds = [self.ranking_embed(guild.id, "yesterday", now)]
            if local_dt(now, self.tz).weekday() == 0:
                embeds.append(self.ranking_embed(guild.id, "last_week", now))
            await self.safe_send(channel, embeds=embeds)

    def ranking_embed(self, guild_id: int, period: str, now: float) -> discord.Embed:
        bounds = {
            "today": (day_bounds(now, self.tz), "今日"),
            "yesterday": (day_bounds(now, self.tz, 1), "昨日"),
            "week": (week_bounds(now, self.tz), "今週"),
            "last_week": (week_bounds(now, self.tz, 1), "先週"),
        }
        (lo, hi), label = bounds[period]
        rows = self.db.ranking(guild_id, lo, hi, now, limit=10)
        start = local_dt(lo, self.tz).strftime("%m/%d")
        end = local_dt(hi - 1, self.tz).strftime("%m/%d")
        span = start if start == end else f"{start}〜{end}"
        embed = discord.Embed(title=f"📚 {label}の勉強時間ランキング（{span}）",
                              description=ranking_text(rows), color=0x4F8EF7)
        total = sum(s for _, s in rows)
        if rows:
            embed.set_footer(text=f"上位{len(rows)}人の合計 {format_duration(total)}")
        return embed

    async def _leave_idle_voice(self) -> None:
        for vc in list(self.voice_clients):
            if not isinstance(vc, discord.VoiceClient):
                continue
            gid = vc.guild.id
            if humans(vc.channel):
                self._idle_voice.discard(gid)
            elif gid in self._idle_voice:  # 2回連続で無人なら退出
                self._idle_voice.discard(gid)
                state = self.music.pop(gid, None)
                if state:
                    state.clear()
                await vc.disconnect()
            else:
                self._idle_voice.add(gid)

    # ---- チャットの自動削除（10分ごと） -------------------------------------
    @tasks.loop(minutes=10)
    async def cleanup_loop(self) -> None:
        now = time.time()
        for guild_id, channel_id, hours in self.db.auto_delete_rules():
            guild = self.get_guild(guild_id)
            channel = guild.get_channel(channel_id) if guild else None
            if channel is None:
                continue
            deleted = await self.purge_old_messages(channel, hours, now)
            if deleted:
                log.info("#%s の%d時間より古いメッセージを %d 件削除", channel.name, hours, deleted)

    async def purge_old_messages(self, channel, hours: int, now: float, limit: int = 500) -> int:
        """hours時間より古いメッセージを削除する（ピン留めは残す）。削除件数を返す。"""
        cutoff = datetime.fromtimestamp(now - hours * 3600, timezone.utc)
        try:
            deleted = await channel.purge(limit=limit, before=cutoff,
                                          check=lambda m: not m.pinned,
                                          reason=f"{hours}時間経過したメッセージの自動削除")
        except discord.Forbidden:
            log.warning("#%s のメッセージを削除する権限がありません"
                        "（メッセージの管理・メッセージ履歴を読む）", getattr(channel, "name", channel))
            return 0
        except discord.HTTPException as e:
            log.warning("#%s の自動削除に失敗: %s", getattr(channel, "name", channel), e)
            return 0
        return len(deleted)

    @cleanup_loop.before_loop
    async def _before_cleanup(self) -> None:
        await self.wait_until_ready()

    @cleanup_loop.error
    async def _cleanup_error(self, error: BaseException) -> None:
        log.exception("cleanup_loop でエラー", exc_info=error)

    # ---- ポモドーロ -------------------------------------------------------
    @tasks.loop(seconds=5)
    async def pomodoro_loop(self) -> None:
        now = time.time()
        for cid, session in list(self.pomodoros.items()):
            if not session.is_due(now):
                continue
            guild = self.get_guild(session.guild_id)
            channel = guild.get_channel(cid) if guild else None
            members = humans(channel)
            if not members:
                self.pomodoros.pop(cid, None)
                continue
            finished = session.phase
            phase = session.advance(now)
            mins = session.config.minutes(phase)
            mentions = " ".join(m.mention for m in members)
            if phase == WORK:
                text = f"🍅 休憩終了！**{mins}分**の作業を始めましょう。"
            elif phase == SHORT_BREAK:
                text = (f"☕ 作業{session.completed_work}回目おつかれさま！"
                        f"**{mins}分**休憩しましょう。")
            else:
                text = (f"🌿 作業{session.completed_work}回達成！"
                        f"**{mins}分**の長い休憩です。")
            log.debug("pomodoro %s: %s -> %s", cid, finished, phase)
            await self.safe_send(channel, f"{mentions}\n{text}")

    @pomodoro_loop.before_loop
    async def _before_pomodoro(self) -> None:
        await self.wait_until_ready()

    @pomodoro_loop.error
    async def _pomodoro_error(self, error: BaseException) -> None:
        log.exception("pomodoro_loop でエラー", exc_info=error)

    async def _stop_pomodoro_if_empty(self, channel: VoiceLike) -> None:
        if channel.id in self.pomodoros and not humans(channel):
            self.pomodoros.pop(channel.id, None)
            log.info("VC %s が無人になったためポモドーロを終了", channel.id)

    def pomodoro_status(self, session: PomodoroSession, now: float) -> str:
        from .timeutil import format_clock

        label = PHASE_LABELS[session.phase]
        state = "⏸ 一時停止中" if session.paused else "▶ 進行中"
        cfg = session.config
        return (f"{state}：**{label}** 残り {format_clock(session.remaining(now))}\n"
                f"完了した作業: {session.completed_work}回\n"
                f"設定: 作業{cfg.work_min}分 / 休憩{cfg.short_break_min}分 / "
                f"{cfg.long_break_every}回ごとに長い休憩{cfg.long_break_min}分")

    # ---- 音楽 -----------------------------------------------------------
    def music_for(self, guild_id: int) -> music_mod.GuildMusic:
        if guild_id not in self.music:
            cfg = self.db.get_config(guild_id)
            volume = (cfg.music_volume / 100 if cfg.music_volume is not None
                      else self.settings.default_volume)
            self.music[guild_id] = music_mod.GuildMusic(volume=volume)
        return self.music[guild_id]

    async def connect_voice(self, channel: VoiceLike) -> discord.VoiceClient:
        """VCへ接続（または移動）する。別のVCで人がいる中で再生中なら MusicError。"""
        voice = channel.guild.voice_client
        if (isinstance(voice, discord.VoiceClient) and voice.channel != channel
                and voice.is_playing() and humans(voice.channel)):
            raise music_mod.MusicError(f"{voice.channel.mention} で再生中です。")
        try:
            if voice is None:
                # 聞き取りオフ（self_deaf）だと音声が届かないことがあるため False
                return await channel.connect(self_deaf=False)
            if voice.channel != channel:
                await voice.move_to(channel)
            return voice
        except (discord.ClientException, RuntimeError, asyncio.TimeoutError) as e:
            raise music_mod.MusicError(f"VCに接続できませんでした: {e}") from e

    async def queue_tracks(self, guild: discord.Guild, voice: discord.VoiceClient,
                           tracks: list[music_mod.Track]) -> tuple[bool, int]:
        """曲をキューに入れ、何も流れていなければ再生する。(再生を始めたか, 追加数)。"""
        state = self.music_for(guild.id)
        idle = state.current is None and not (voice.is_playing() or voice.is_paused())
        added = state.enqueue_many(tracks)
        if idle:
            state.current = state.queue.popleft()
            await self.start_track(guild, state.current)
        return idle, added

    def music_source(self, guild_id: int) -> str:
        return self.db.get_config(guild_id).music_source or music_mod.YTM

    def pomodoro_defaults(self, guild_id: int) -> PomodoroConfig:
        cfg = self.db.get_config(guild_id)
        base = PomodoroConfig()
        return PomodoroConfig(cfg.pomo_work or base.work_min,
                              cfg.pomo_short or base.short_break_min,
                              cfg.pomo_long or base.long_break_min,
                              cfg.pomo_every or base.long_break_every)

    async def start_track(self, guild: discord.Guild, track: music_mod.Track) -> None:
        voice = guild.voice_client
        if not isinstance(voice, discord.VoiceClient):
            raise music_mod.MusicError("VCに接続していません。")
        state = self.music_for(guild.id)
        info = await music_mod.extract(track.page_url)  # 再生URLは期限切れになるため毎回取得
        stream = music_mod.select_stream(info)
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(stream.url, executable=self.settings.ffmpeg_path,
                                   **music_mod.ffmpeg_options(stream)),
            volume=state.volume)
        if voice.is_playing() or voice.is_paused():
            state.generation += 1  # 止めた曲のafterで次曲へ進まないようにする
            voice.stop()
        gen = state.generation
        log.info("再生開始 guild=%s ch=%s live=%s dave=%s: %s", guild.id, voice.channel.id,
                 stream.is_live, getattr(voice._connection, "dave_protocol_version", "?"),
                 track.title)
        voice.play(source, after=lambda err: asyncio.run_coroutine_threadsafe(
            self._after_track(guild.id, gen, err), self.loop))
        self.loop.create_task(self._check_voice_encryption(voice))

    async def _check_voice_encryption(self, voice: discord.VoiceClient) -> None:
        """E2EE（DAVE）必須のVCで暗号化できていなければ警告する。

        暗号化されない音声はDiscord側で復号に失敗し、無音になる
        （davey 0.2.0 と discord.py 2.7.1 の組み合わせで発生した）。
        """
        await asyncio.sleep(5)
        conn = voice._connection
        version = getattr(conn, "dave_protocol_version", 0)
        if voice.is_playing() and version and not getattr(conn, "can_encrypt", True):
            session = getattr(conn, "dave_session", None)
            log.warning("DAVE暗号化が有効になっていません（version=%s ready=%s）。音声は無音になります。"
                        "davey と discord.py の版を確認してください。",
                        version, getattr(session, "ready", None))

    async def _after_track(self, guild_id: int, gen: int, err: Exception | None) -> None:
        if err:
            log.warning("再生エラー: %s", err)
        else:
            log.info("再生終了 guild=%s", guild_id)
        state = self.music.get(guild_id)
        guild = self.get_guild(guild_id)
        if state is None or guild is None or state.generation != gen:
            return
        for _ in range(len(state.queue) + 1):
            nxt = state.next_track()
            if nxt is None:
                return
            try:
                await self.start_track(guild, nxt)
                return
            except music_mod.MusicError as e:
                log.warning("次の曲を再生できません (%s): %s", nxt.title, e)
                if state.loop_mode == "single":
                    state.loop_mode = "off"  # 再生できない曲を繰り返さない
                    state.current = None
        state.current = None
