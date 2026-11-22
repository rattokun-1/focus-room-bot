"""スラッシュコマンド定義。"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from . import music as music_mod
from .formatting import goal_text
from .pomodoro import PomodoroConfig, PomodoroSession
from .timeutil import date_key, day_bounds, format_duration, is_due, parse_hhmm, week_bounds

if TYPE_CHECKING:
    from .bot import StudyBot

Interaction = discord.Interaction


async def reply(interaction: Interaction, content: str | None = None, *,
                ephemeral: bool = True, **kwargs) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral, **kwargs)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral, **kwargs)


def user_voice_channel(interaction: Interaction):
    member = interaction.user
    if isinstance(member, discord.Member) and member.voice and member.voice.channel:
        return member.voice.channel
    return None


def register_commands(bot: "StudyBot") -> None:
    tree = bot.tree

    # ---- 対話式の設定パネル ------------------------------------------------
    @tree.command(name="setup", description="勉強記録・ポモドーロ・通知・音楽・自分の目標をまとめて設定します")
    @app_commands.guild_only()
    async def setup(interaction: Interaction):
        from .setup_view import SetupView

        view = SetupView(bot, interaction.guild, interaction.user)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    @tree.command(name="start", description="参加中のVCで集中セッション（ポモドーロ＋音楽）を開始します")
    @app_commands.guild_only()
    async def start(interaction: Interaction):
        channel = user_voice_channel(interaction)
        if channel is None:
            return await reply(interaction, "先にVCに参加してください。")
        await interaction.response.defer(ephemeral=True, thinking=True)
        lines, started = await bot.auto_start(interaction.guild, channel, interaction.user.id)
        if started:
            await bot.safe_send(channel, f"🚀 {interaction.user.mention} が集中セッションを開始しました。\n"
                                + "\n".join(lines))
        await reply(interaction, "\n".join(lines))

    @tree.command(name="stop", description="参加中のVCの集中セッション（ポモドーロ＋音楽）を終了します")
    @app_commands.guild_only()
    async def stop(interaction: Interaction):
        channel = user_voice_channel(interaction)
        if channel is None:
            return await reply(interaction, "先にVCに参加してください。")
        lines = await bot.stop_session(interaction.guild, channel)
        if not lines:
            return await reply(interaction, "このVCでは集中セッションは動いていません。")
        await bot.safe_send(channel, f"🛑 {interaction.user.mention} が集中セッションを終了しました。")
        await reply(interaction, "\n".join(lines))

    # ---- 記録・ランキング -------------------------------------------------
    @tree.command(name="stats", description="勉強時間（今日・今週・累計）を表示します")
    @app_commands.guild_only()
    @app_commands.describe(member="表示するメンバー（省略時は自分）")
    async def stats(interaction: Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        gid = interaction.guild_id
        now = time.time()
        d_lo, d_hi = day_bounds(now, bot.tz)
        w_lo, w_hi = week_bounds(now, bot.tz)
        today = bot.db.user_seconds(gid, target.id, d_lo, d_hi, now)
        week = bot.db.user_seconds(gid, target.id, w_lo, w_hi, now)
        total = bot.db.user_seconds(gid, target.id, 0, now + 1, now)
        embed = discord.Embed(title=f"📖 {target.display_name} の勉強記録", color=0x4F8EF7)
        d_rank = bot.db.user_rank(gid, target.id, d_lo, d_hi, now)
        w_rank = bot.db.user_rank(gid, target.id, w_lo, w_hi, now)
        embed.add_field(name="今日", value=format_duration(today)
                        + (f"（{d_rank}位）" if d_rank else ""))
        embed.add_field(name="今週", value=format_duration(week)
                        + (f"（{w_rank}位）" if w_rank else ""))
        embed.add_field(name="累計", value=format_duration(total))
        goal = bot.db.get_goal(gid, target.id)
        if goal:
            embed.add_field(name="今日の目標", value=goal_text(today, goal[0]), inline=False)
        current = [s for s in bot.db.open_sessions(gid) if s.user_id == target.id]
        if current:
            s = current[0]
            embed.add_field(name="現在", value=f"<#{s.channel_id}> で勉強中"
                            f"（{format_duration(now - s.start)}経過）", inline=False)
        await reply(interaction, embed=embed, ephemeral=False)

    @tree.command(name="ranking", description="勉強時間ランキングを表示します")
    @app_commands.guild_only()
    @app_commands.describe(period="集計期間")
    @app_commands.choices(period=[
        app_commands.Choice(name="今日", value="today"),
        app_commands.Choice(name="今週", value="week"),
        app_commands.Choice(name="昨日", value="yesterday"),
        app_commands.Choice(name="先週", value="last_week"),
    ])
    async def ranking(interaction: Interaction, period: app_commands.Choice[str] | None = None):
        value = period.value if period else "today"
        embed = bot.ranking_embed(interaction.guild_id, value, time.time())
        await reply(interaction, embed=embed, ephemeral=False)

    # ---- ポモドーロ -------------------------------------------------------
    pomo = app_commands.Group(name="pomodoro", description="VCのポモドーロタイマー",
                              guild_only=True)

    @pomo.command(name="start", description="参加中のVCでポモドーロを開始します")
    @app_commands.describe(work="作業時間（分。省略でサーバーの既定値）", short_break="休憩時間（分）",
                           long_break="長い休憩（分）", long_break_every="何回ごとに長い休憩にするか")
    async def pomo_start(interaction: Interaction,
                         work: app_commands.Range[int, 1, 180] | None = None,
                         short_break: app_commands.Range[int, 1, 60] | None = None,
                         long_break: app_commands.Range[int, 1, 120] | None = None,
                         long_break_every: app_commands.Range[int, 1, 12] | None = None):
        # 省略した値はサーバーの既定値（/setup で変更）を使う
        d = bot.pomodoro_defaults(interaction.guild_id)
        work = work or d.work_min
        short_break = short_break or d.short_break_min
        long_break = long_break or d.long_break_min
        long_break_every = long_break_every or d.long_break_every
        channel = user_voice_channel(interaction)
        if channel is None:
            return await reply(interaction, "先にVCに参加してください。")
        if channel.id in bot.pomodoros:
            return await reply(interaction, "このVCではすでにポモドーロが動いています。"
                               "`/pomodoro stop` で止めてから開始してください。")
        cfg = PomodoroConfig(work, short_break, long_break, long_break_every)
        session = PomodoroSession.start(interaction.guild_id, channel.id,
                                        interaction.user.id, cfg, time.time())
        bot.pomodoros[channel.id] = session
        await reply(interaction,
                    f"🍅 {channel.mention} でポモドーロを開始しました。**{work}分**集中しましょう！\n"
                    f"（休憩{short_break}分、{long_break_every}回ごとに{long_break}分の長い休憩。"
                    "切替時はVCのチャットでお知らせします）", ephemeral=False)

    def session_for(interaction: Interaction) -> PomodoroSession | None:
        channel = user_voice_channel(interaction)
        return bot.pomodoros.get(channel.id) if channel else None

    @pomo.command(name="status", description="ポモドーロの残り時間を表示します")
    async def pomo_status(interaction: Interaction):
        session = session_for(interaction)
        if session is None:
            return await reply(interaction, "参加中のVCではポモドーロが動いていません。")
        await reply(interaction, bot.pomodoro_status(session, time.time()))

    @pomo.command(name="pause", description="ポモドーロを一時停止します")
    async def pomo_pause(interaction: Interaction):
        session = session_for(interaction)
        if session is None:
            return await reply(interaction, "参加中のVCではポモドーロが動いていません。")
        session.pause(time.time())
        await reply(interaction, "⏸ ポモドーロを一時停止しました。", ephemeral=False)

    @pomo.command(name="resume", description="一時停止したポモドーロを再開します")
    async def pomo_resume(interaction: Interaction):
        session = session_for(interaction)
        if session is None:
            return await reply(interaction, "参加中のVCではポモドーロが動いていません。")
        session.resume(time.time())
        await reply(interaction, "▶ ポモドーロを再開しました。", ephemeral=False)

    @pomo.command(name="stop", description="ポモドーロを終了します")
    async def pomo_stop(interaction: Interaction):
        channel = user_voice_channel(interaction)
        session = bot.pomodoros.pop(channel.id, None) if channel else None
        if session is None:
            return await reply(interaction, "参加中のVCではポモドーロが動いていません。")
        await reply(interaction, f"🛑 ポモドーロを終了しました（作業{session.completed_work}回完了）。",
                    ephemeral=False)

    tree.add_command(pomo)

    # ---- 目標 -----------------------------------------------------------
    goal = app_commands.Group(name="goal", description="1日の勉強目標", guild_only=True)

    @goal.command(name="set", description="1日の目標勉強時間を設定します")
    @app_commands.describe(minutes="目標（分）")
    async def goal_set(interaction: Interaction, minutes: app_commands.Range[int, 1, 1440]):
        bot.db.set_goal(interaction.guild_id, interaction.user.id, minutes)
        await reply(interaction, f"🎯 1日の目標を **{format_duration(minutes * 60)}** に設定しました。"
                    "達成するとお知らせします。")

    @goal.command(name="show", description="今日の目標の進み具合を表示します")
    async def goal_show(interaction: Interaction):
        g = bot.db.get_goal(interaction.guild_id, interaction.user.id)
        if g is None:
            return await reply(interaction, "目標は未設定です。`/goal set` で設定できます。")
        now = time.time()
        lo, hi = day_bounds(now, bot.tz)
        done = bot.db.user_seconds(interaction.guild_id, interaction.user.id, lo, hi, now)
        await reply(interaction, f"🎯 今日の目標: {goal_text(done, g[0])}")

    @goal.command(name="clear", description="目標を削除します")
    async def goal_clear(interaction: Interaction):
        ok = bot.db.clear_goal(interaction.guild_id, interaction.user.id)
        await reply(interaction, "目標を削除しました。" if ok else "目標は未設定です。")

    tree.add_command(goal)

    # ---- リマインド -------------------------------------------------------
    remind = app_commands.Group(name="remind", description="毎日の勉強リマインド", guild_only=True)

    @remind.command(name="set", description="毎日指定時刻にDMでリマインドします（勉強中・目標達成済みなら送りません）")
    @app_commands.describe(time_of_day="時刻（例: 21:00）")
    @app_commands.rename(time_of_day="time")
    async def remind_set(interaction: Interaction, time_of_day: str):
        try:
            hhmm = parse_hhmm(time_of_day)
        except ValueError as e:
            return await reply(interaction, str(e))
        gid, uid = interaction.guild_id, interaction.user.id
        bot.db.set_reminder(gid, uid, hhmm)
        now = time.time()
        if is_due(now, bot.tz, hhmm, None):  # 今日の時刻を過ぎていれば明日から
            bot.db.mark_reminder_sent(gid, uid, date_key(now, bot.tz))
        await reply(interaction, f"⏰ 毎日 **{hhmm}** にリマインドします。"
                    "DMを受け取れない設定の場合は通知チャンネルでメンションします。")

    @remind.command(name="show", description="リマインド設定を表示します")
    async def remind_show(interaction: Interaction):
        hhmm = bot.db.get_reminder(interaction.guild_id, interaction.user.id)
        await reply(interaction, f"⏰ 毎日 {hhmm} にリマインドします。" if hhmm
                    else "リマインドは未設定です。")

    @remind.command(name="clear", description="リマインドを停止します")
    async def remind_clear(interaction: Interaction):
        ok = bot.db.clear_reminder(interaction.guild_id, interaction.user.id)
        await reply(interaction, "リマインドを停止しました。" if ok else "リマインドは未設定です。")

    tree.add_command(remind)

    # ---- 音楽 -----------------------------------------------------------
    mus = app_commands.Group(name="music", description="集中用BGM（YouTube Music / YouTube）",
                             guild_only=True)
    source_choices = [
        app_commands.Choice(name="YouTube Music", value=music_mod.YTM),
        app_commands.Choice(name="YouTube", value=music_mod.YOUTUBE),
    ]

    async def ensure_voice(interaction: Interaction):
        """呼び出した人のVCへ接続し、VoiceClientを返す。失敗時は返信してNone。"""
        channel = user_voice_channel(interaction)
        if channel is None:
            await reply(interaction, "先にVCに参加してください。")
            return None
        try:
            return await bot.connect_voice(channel)
        except music_mod.MusicError as e:
            await reply(interaction, f"⚠️ {e}")
            return None

    async def add_and_play(interaction: Interaction, voice, tracks, playlist: str | None):
        state = bot.music_for(interaction.guild_id)
        idle, added = await bot.queue_tracks(interaction.guild, voice, tracks)
        first = tracks[0]
        if playlist:
            msg = f"📚 **{playlist}** から **{added}曲** を追加しました。"
            if added < len(tracks):
                msg += f"（キュー上限のため{len(tracks) - added}曲は追加していません）"
            if idle:
                msg += f"\n🎵 再生開始: **{first.title}**"
        elif idle:
            tag = "🔴 ライブ" if first.is_live else format_duration(first.duration or 0)
            msg = f"🎵 再生開始: **{first.title}**（{tag}）"
        else:
            msg = f"➕ キューに追加（{len(state.queue)}番目）: **{first.title}**"
        if state.loop_mode != "off":
            msg += f"　{music_mod.LOOP_MODES[state.loop_mode]}"
        await reply(interaction, msg)

    @mus.command(name="play",
                 description="YouTube Music / YouTube の曲・プレイリスト・アルバムを再生します")
    @app_commands.describe(query="曲名・アーティスト名、またはYouTube Music / YouTube / SpotifyのURL",
                           source="検索に使うサービス（URL指定時は無視。省略でサーバーの既定値）")
    @app_commands.choices(source=source_choices)
    async def music_play(interaction: Interaction, query: str,
                         source: app_commands.Choice[str] | None = None):
        if user_voice_channel(interaction) is None:
            return await reply(interaction, "先にVCに参加してください。")
        await interaction.response.defer(ephemeral=True, thinking=True)  # VC接続と検索は3秒を超えることがある
        voice = await ensure_voice(interaction)
        if voice is None:
            return
        try:
            tracks, playlist = await music_mod.resolve(
                query, source.value if source else bot.music_source(interaction.guild_id), interaction.user.id)
            await add_and_play(interaction, voice, tracks, playlist)
        except music_mod.MusicError as e:
            await reply(interaction, f"⚠️ {e}")

    @mus.command(name="recommend", description="勉強向けのおすすめ曲を選んで再生します")
    @app_commands.describe(theme="ジャンルや気分（例: lofi、ピアノ、カフェ。省略で勉強向けからランダム）",
                           source="検索に使うサービス")
    @app_commands.choices(source=source_choices)
    async def music_recommend(interaction: Interaction, theme: str | None = None,
                              source: app_commands.Choice[str] | None = None):
        if user_voice_channel(interaction) is None:
            return await reply(interaction, "先にVCに参加してください。")
        await interaction.response.defer(ephemeral=True, thinking=True)  # VC接続と検索は3秒を超えることがある
        voice = await ensure_voice(interaction)
        if voice is None:
            return
        try:
            track = await music_mod.recommend(
                theme, source.value if source else bot.music_source(interaction.guild_id), interaction.user.id)
            await add_and_play(interaction, voice, [track], None)
        except music_mod.MusicError as e:
            await reply(interaction, f"⚠️ {e}")

    def active_voice(interaction: Interaction):
        voice = interaction.guild.voice_client
        state = bot.music.get(interaction.guild_id)
        if not isinstance(voice, discord.VoiceClient) or state is None or state.current is None:
            return None, None
        return voice, state

    @mus.command(name="pause", description="再生を一時停止します")
    async def music_pause(interaction: Interaction):
        voice, _ = active_voice(interaction)
        if voice is None or not voice.is_playing():
            return await reply(interaction, "再生中の曲はありません。")
        voice.pause()
        await reply(interaction, "⏸ 一時停止しました。")

    @mus.command(name="resume", description="一時停止した再生を再開します")
    async def music_resume(interaction: Interaction):
        voice, _ = active_voice(interaction)
        if voice is None or not voice.is_paused():
            return await reply(interaction, "一時停止中の曲はありません。")
        voice.resume()
        await reply(interaction, "▶ 再開しました。")

    @mus.command(name="skip", description="次の曲へ進みます")
    async def music_skip(interaction: Interaction):
        voice, state = active_voice(interaction)
        if voice is None:
            return await reply(interaction, "再生中の曲はありません。")
        if state.skip() is None:
            state.generation += 1
            voice.stop()
            return await reply(interaction, "⏭ スキップしました（キューは空です）。")
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await bot.start_track(interaction.guild, state.current)
        except music_mod.MusicError as e:
            return await reply(interaction, f"⚠️ {e}")
        await reply(interaction, f"⏭ 次の曲: **{state.current.title}**")

    @mus.command(name="stop", description="再生を止め、キューを消してVCから退出します")
    async def music_stop(interaction: Interaction):
        guild = interaction.guild
        state = bot.music.pop(guild.id, None)
        if state:
            state.clear()
        voice = guild.voice_client
        if voice is None:
            return await reply(interaction, "VCに接続していません。")
        await voice.disconnect(force=True)
        await reply(interaction, "⏹ 再生を停止して退出しました。")

    @mus.command(name="volume", description="音量を変更します（0〜100%）")
    async def music_volume(interaction: Interaction, percent: app_commands.Range[int, 0, 100]):
        state = bot.music_for(interaction.guild_id)
        state.volume = percent / 100
        voice = interaction.guild.voice_client
        if isinstance(voice, discord.VoiceClient) and isinstance(voice.source,
                                                                 discord.PCMVolumeTransformer):
            voice.source.volume = state.volume
        await reply(interaction, f"🔊 音量を {percent}% にしました。")

    @mus.command(name="loop", description="ループモードを切り替えます")
    @app_commands.choices(mode=[
        app_commands.Choice(name="ループなし", value="off"),
        app_commands.Choice(name="1曲リピート", value="single"),
        app_commands.Choice(name="全曲ループ", value="all"),
    ])
    async def music_loop(interaction: Interaction, mode: app_commands.Choice[str]):
        state = bot.music_for(interaction.guild_id)
        state.loop_mode = mode.value
        await reply(interaction, f"{music_mod.LOOP_MODES[mode.value]} にしました。")

    @mus.command(name="shuffle", description="キューの順番をシャッフルします")
    async def music_shuffle(interaction: Interaction):
        state = bot.music.get(interaction.guild_id)
        if state is None or len(state.queue) < 2:
            return await reply(interaction, "シャッフルできる曲がキューにありません。")
        state.shuffle()
        await reply(interaction, f"🔀 キューの{len(state.queue)}曲をシャッフルしました。",)

    @mus.command(name="queue", description="再生中の曲とキューを表示します")
    async def music_queue(interaction: Interaction):
        state = bot.music.get(interaction.guild_id)
        if state is None or state.current is None:
            return await reply(interaction, "再生中の曲はありません。")
        lines = [f"▶ **{state.current.title}**　{music_mod.LOOP_MODES[state.loop_mode]}"]
        shown = list(state.queue)[:15]
        lines += [f"`{i:>2}.` {t.title}" for i, t in enumerate(shown, start=1)]
        if len(state.queue) > len(shown):
            lines.append(f"…ほか{len(state.queue) - len(shown)}曲")
        await reply(interaction, "\n".join(lines)[:1900])

    tree.add_command(mus)

    # ---- サーバー設定（サーバー管理権限） -------------------------------
    cfg = app_commands.Group(name="studyconfig", description="勉強Botのサーバー設定",
                             guild_only=True,
                             default_permissions=discord.Permissions(manage_guild=True))

    @cfg.command(name="add-channel", description="勉強時間を記録するVCを追加します")
    async def cfg_add(interaction: Interaction,
                      channel: discord.VoiceChannel | discord.StageChannel):
        bot.db.add_study_channel(interaction.guild_id, channel.id)
        bot.reconcile_guild(interaction.guild)
        await reply(interaction, f"{channel.mention} を勉強VCに追加しました。")

    @cfg.command(name="remove-channel", description="勉強VCの指定を外します")
    async def cfg_remove(interaction: Interaction,
                         channel: discord.VoiceChannel | discord.StageChannel):
        ok = bot.db.remove_study_channel(interaction.guild_id, channel.id)
        bot.reconcile_guild(interaction.guild)
        await reply(interaction, f"{channel.mention} を外しました。" if ok
                    else f"{channel.mention} は勉強VCに指定されていません。")

    @cfg.command(name="show", description="現在の設定を表示します")
    async def cfg_show(interaction: Interaction):
        gid = interaction.guild_id
        c = bot.db.get_config(gid)
        chans = bot.db.study_channels(gid)
        lines = [
            "**勉強VC**: " + (" ".join(f"<#{x}>" for x in sorted(chans)) if chans
                             else "未指定（AFK以外の全VCを記録）"),
            "**通知チャンネル**: " + (f"<#{c.notify_channel_id}>" if c.notify_channel_id
                                    else "未指定（VCのチャットに送信）"),
            "**ランキング自動投稿**: " + (f"<#{c.ranking_channel_id}> 毎日 {c.ranking_time}"
                                       if c.ranking_channel_id else "オフ"),
            "**チャット自動削除**: " + ("、".join(f"<#{cid}> {h}時間"
                                                for _, cid, h in bot.db.auto_delete_rules(gid))
                                      or "なし"),
            f"**タイムゾーン**: {bot.tz.key}",
        ]
        await reply(interaction, "\n".join(lines))

    @cfg.command(name="notify-channel", description="目標達成などの通知先を設定します（省略で解除）")
    async def cfg_notify(interaction: Interaction, channel: discord.TextChannel | None = None):
        bot.db.update_config(interaction.guild_id,
                             notify_channel_id=channel.id if channel else None)
        await reply(interaction, f"通知先を {channel.mention} にしました。" if channel
                    else "通知先を解除しました（VCのチャットに送信します）。")

    @cfg.command(name="ranking-post", description="前日のランキングを毎日自動投稿します（月曜は先週分も）")
    @app_commands.describe(channel="投稿先", time_of_day="投稿時刻（例: 07:00）")
    @app_commands.rename(time_of_day="time")
    async def cfg_ranking(interaction: Interaction, channel: discord.TextChannel,
                          time_of_day: str = "07:00"):
        try:
            hhmm = parse_hhmm(time_of_day)
        except ValueError as e:
            return await reply(interaction, str(e))
        now = time.time()
        last = date_key(now, bot.tz) if is_due(now, bot.tz, hhmm, None) else None
        bot.db.update_config(interaction.guild_id, ranking_channel_id=channel.id,
                             ranking_time=hhmm, last_ranking_date=last)
        await reply(interaction, f"毎日 {hhmm} に {channel.mention} へランキングを投稿します。")

    @cfg.command(name="ranking-off", description="ランキングの自動投稿を止めます")
    async def cfg_ranking_off(interaction: Interaction):
        bot.db.update_config(interaction.guild_id, ranking_channel_id=None, ranking_time=None)
        await reply(interaction, "ランキングの自動投稿を止めました。")

    @cfg.command(name="auto-delete",
                 description="チャンネルのメッセージを指定時間後に自動削除します（ピン留めは残します）")
    @app_commands.describe(channel="対象のチャンネル（VCのチャットも指定可）",
                           hours="何時間たったメッセージを消すか（初期値24）")
    async def cfg_auto_delete(interaction: Interaction,
                              channel: discord.TextChannel | discord.VoiceChannel
                              | discord.StageChannel,
                              hours: app_commands.Range[int, 1, 168] = 24):
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.manage_messages and perms.read_message_history):
            return await reply(interaction, f"{channel.mention} でBotに「メッセージの管理」と"
                               "「メッセージ履歴を読む」権限が必要です。")
        bot.db.set_auto_delete(interaction.guild_id, channel.id, hours)
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted = await bot.purge_old_messages(channel, hours, time.time())
        await reply(interaction, f"🧹 {channel.mention} のメッセージを **{hours}時間** で自動削除します"
                    f"（10分ごとに確認。今回 {deleted} 件削除）。")

    @cfg.command(name="auto-delete-off", description="チャンネルの自動削除を止めます")
    async def cfg_auto_delete_off(interaction: Interaction,
                                  channel: discord.TextChannel | discord.VoiceChannel
                                  | discord.StageChannel):
        ok = bot.db.remove_auto_delete(interaction.guild_id, channel.id)
        await reply(interaction, f"{channel.mention} の自動削除を止めました。" if ok
                    else f"{channel.mention} は自動削除の対象ではありません。")

    tree.add_command(cfg)
