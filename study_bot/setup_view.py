"""/setup の対話式設定パネル（ボタン・選択メニュー・入力フォーム）。

パネルは実行した本人にだけ表示する。サーバー全体の設定は「サーバー管理」権限を
持つ人だけが開け、それ以外の人は自分の目標とリマインドだけを設定できる。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord

from . import music as music_mod
from .formatting import goal_text
from .pomodoro import PomodoroConfig
from .timeutil import date_key, day_bounds, format_duration, is_due, parse_hhmm

if TYPE_CHECKING:
    from .bot import StudyBot

COLOR = 0x4F8EF7
DEFAULT_DELETE_HOURS = 24
DEFAULT_RANKING_TIME = "07:00"

SECTIONS = {
    "home": ("🏠 概要", "今の設定をまとめて表示"),
    "auto": ("🚀 自動開始", "VCに入ったらポモドーロと音楽を開始"),
    "study": ("📚 勉強記録", "勉強時間を記録するVC"),
    "pomodoro": ("🍅 ポモドーロ", "既定の作業・休憩時間"),
    "notify": ("🔔 通知・チャット", "通知先・ランキング投稿・自動削除"),
    "music": ("🎵 音楽", "既定の音量・検索サービス"),
    "me": ("🎯 自分の目標・リマインド", "1日の目標とリマインド時刻"),
}
ADMIN_SECTIONS = {"auto", "study", "pomodoro", "notify", "music"}

POMODORO_PRESETS = {
    "25-5-15-4": "標準 25分 / 休憩5分 / 4回ごとに15分",
    "50-10-20-3": "長め 50分 / 休憩10分 / 3回ごとに20分",
    "90-15-30-2": "じっくり 90分 / 休憩15分 / 2回ごとに30分",
    "15-3-10-4": "短め 15分 / 休憩3分 / 4回ごとに10分",
}
VOLUME_CHOICES = [5, 10, 15, 20, 30, 50, 75, 100]
GOAL_PRESETS = [30, 60, 90, 120, 180, 240, 300, 480]


def _mention(channel_id: int | None, empty: str = "未設定") -> str:
    return f"<#{channel_id}>" if channel_id else empty


class SetupView(discord.ui.View):
    def __init__(self, bot: "StudyBot", guild: discord.Guild, user: discord.Member,
                 section: str = "home"):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.user = user
        self.is_admin = bool(getattr(user.guild_permissions, "manage_guild", False))
        self.section = section if (self.is_admin or section not in ADMIN_SECTIONS) else "me"
        self.build()

    # ---- 共通 ------------------------------------------------------------
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user.id

    def build(self) -> None:
        self.clear_items()
        self.add_item(SectionSelect(self))
        builder = getattr(self, f"_build_{self.section}", None)
        if builder:
            builder()

    async def refresh(self, interaction: discord.Interaction, note: str | None = None) -> None:
        self.build()
        await interaction.response.edit_message(content=note, embed=self.embed(), view=self)

    def embed(self) -> discord.Embed:
        title, _ = SECTIONS[self.section]
        e = discord.Embed(title=f"⚙️ 設定 — {title}", color=COLOR)
        getattr(self, f"_embed_{self.section}")(e)
        e.set_footer(text="上のメニューで項目を切り替えます。パネルは10分で操作できなくなります（/setup で再表示）")
        return e

    @property
    def cfg(self):
        return self.bot.db.get_config(self.guild.id)

    # ---- 概要 ------------------------------------------------------------
    def _embed_home(self, e: discord.Embed) -> None:
        e.description = ("勉強Botの設定を、ここからまとめて変更できます。\n"
                         "上のメニューから項目を選んでください。")
        if not self.is_admin:
            e.description += "\n\nサーバー全体の設定は「サーバー管理」権限を持つ人が変更できます。"
        self._embed_auto(e, compact=True)
        self._embed_study(e, compact=True)
        self._embed_pomodoro(e, compact=True)
        self._embed_notify(e, compact=True)
        self._embed_music(e, compact=True)
        self._embed_me(e, compact=True)

    # ---- 自動開始 ----------------------------------------------------------
    def _embed_auto(self, e: discord.Embed, compact: bool = False) -> None:
        c = self.cfg
        feats = []
        if c.auto_pomodoro != 0:
            feats.append("🍅 ポモドーロ")
        if c.auto_music != 0:
            query = (c.auto_music_query or "").strip()
            feats.append(f"🎵 音楽（{query if query else '勉強向けおすすめをランダム'}）")
        what = "、".join(feats) if feats else "なし"
        if not compact:
            e.description = ("下で選んだVCにだれかが入ると、ポモドーロと音楽を自動で開始します。"
                             "どのVCでも `/start` で同じように開始でき、`/stop` で終了します。"
                             "すでに動いているときは何もしません。")
        e.add_field(name="🚀 自動開始するVC",
                    value=_mention(c.auto_channel_id, "未設定（/start でのみ開始）"), inline=False)
        e.add_field(name="🚀 開始する内容", value=what, inline=False)

    def _build_auto(self) -> None:
        self.add_item(AutoChannelSelect(self))
        self.add_item(AutoFeatureSelect(self))
        self.add_item(ActionButton(self, "流す音楽を設定", "auto_music_modal",
                                   discord.ButtonStyle.primary, "🎵", row=3))

    # ---- 勉強記録 ----------------------------------------------------------
    def _embed_study(self, e: discord.Embed, compact: bool = False) -> None:
        chans = sorted(self.bot.db.study_channels(self.guild.id))
        value = " ".join(_mention(c) for c in chans) if chans else "AFK以外のすべてのVC"
        if not compact:
            e.description = ("VCにいる時間を勉強時間として記録します。マイク・カメラの状態は問いません。\n"
                             "記録するVCを下のメニューで選んでください（何も選ばなければ全VC）。")
        e.add_field(name="📚 記録するVC", value=value, inline=False)

    def _build_study(self) -> None:
        self.add_item(StudyChannelSelect(self))
        self.add_item(ActionButton(self, "全VCを対象にする", "study_all", discord.ButtonStyle.secondary,
                                   "🌐", row=2))

    # ---- ポモドーロ ---------------------------------------------------------
    def _embed_pomodoro(self, e: discord.Embed, compact: bool = False) -> None:
        d = self.bot.pomodoro_defaults(self.guild.id)
        value = (f"作業 **{d.work_min}分** / 休憩 **{d.short_break_min}分** / "
                 f"{d.long_break_every}回ごとに長い休憩 **{d.long_break_min}分**")
        if not compact:
            e.description = ("`/pomodoro start` で時間を省略したときの既定値です。\n"
                             "プリセットから選ぶか、「時間を細かく設定」で入力してください。")
        e.add_field(name="🍅 ポモドーロ", value=value, inline=False)

    def _build_pomodoro(self) -> None:
        self.add_item(PomodoroPresetSelect(self))
        self.add_item(ActionButton(self, "時間を細かく設定", "pomo_modal", discord.ButtonStyle.primary,
                                   "⏱", row=2))
        self.add_item(ActionButton(self, "初期値に戻す", "pomo_reset", discord.ButtonStyle.secondary,
                                   "↩", row=2))

    # ---- 通知・チャット -------------------------------------------------------
    def _delete_hours(self) -> int:
        rules = self.bot.db.auto_delete_rules(self.guild.id)
        return rules[0][2] if rules else getattr(self, "_pending_hours", DEFAULT_DELETE_HOURS)

    def _embed_notify(self, e: discord.Embed, compact: bool = False) -> None:
        c = self.cfg
        rules = self.bot.db.auto_delete_rules(self.guild.id)
        if not compact:
            e.description = ("下のメニューで、それぞれのチャンネルを選んでください。\n"
                             "時刻や削除までの時間は「時刻・時間を変更」で変えられます。")
        e.add_field(name="🔔 目標達成などの通知先",
                    value=_mention(c.notify_channel_id, "未設定（VCのチャットに送信）"), inline=False)
        ranking = (f"{_mention(c.ranking_channel_id)} 毎日 {c.ranking_time or DEFAULT_RANKING_TIME}"
                   "（前日分、月曜は先週分も）" if c.ranking_channel_id else "オフ")
        e.add_field(name="🏆 ランキング自動投稿", value=ranking, inline=False)
        if rules:
            warn = []
            for _, cid, _h in rules:
                ch = self.guild.get_channel(cid)
                me = getattr(self.guild, "me", None)
                if ch is not None and me is not None:
                    perms = ch.permissions_for(me)
                    if not (perms.manage_messages and perms.read_message_history):
                        warn.append(f"<#{cid}>")
            value = (" ".join(f"<#{cid}>" for _, cid, _h in rules)
                     + f" — **{rules[0][2]}時間**で削除（ピン留めは残す）")
            if warn:
                value += "\n⚠️ 権限不足: " + " ".join(warn) + "（メッセージの管理・履歴を読む）"
        else:
            value = "オフ"
        e.add_field(name="🧹 チャットの自動削除", value=value, inline=False)

    def _build_notify(self) -> None:
        self.add_item(NotifyChannelSelect(self))
        self.add_item(RankingChannelSelect(self))
        self.add_item(AutoDeleteSelect(self))
        self.add_item(ActionButton(self, "時刻・時間を変更", "notify_modal",
                                   discord.ButtonStyle.primary, "⏰", row=4))

    # ---- 音楽 ------------------------------------------------------------
    def _embed_music(self, e: discord.Embed, compact: bool = False) -> None:
        c = self.cfg
        volume = c.music_volume if c.music_volume is not None else round(
            self.bot.settings.default_volume * 100)
        source = "YouTube" if (c.music_source == music_mod.YOUTUBE) else "YouTube Music"
        if not compact:
            e.description = ("`/music play` の既定の音量と、曲名で検索するときのサービスです。\n"
                             "再生中の音量もすぐに変わります。")
        e.add_field(name="🎵 音楽", value=f"既定の音量 **{volume}%** / 検索 **{source}**",
                    inline=False)

    def _build_music(self) -> None:
        self.add_item(VolumeSelect(self))
        self.add_item(SourceSelect(self))

    # ---- 自分の目標・リマインド ---------------------------------------------------
    def _embed_me(self, e: discord.Embed, compact: bool = False) -> None:
        gid, uid = self.guild.id, self.user.id
        goal = self.bot.db.get_goal(gid, uid)
        now = time.time()
        lo, hi = day_bounds(now, self.bot.tz)
        done = self.bot.db.user_seconds(gid, uid, lo, hi, now)
        reminder = self.bot.db.get_reminder(gid, uid)
        if not compact:
            e.description = ("あなただけの設定です。目標を達成すると通知し、リマインドはDMで届きます"
                             "（勉強中・目標達成済みの日は送りません）。")
        e.add_field(name="🎯 あなたの1日の目標",
                    value=goal_text(done, goal[0]) if goal else "未設定", inline=False)
        e.add_field(name="⏰ あなたのリマインド",
                    value=f"毎日 {reminder}" if reminder else "未設定", inline=False)

    def _build_me(self) -> None:
        self.add_item(GoalPresetSelect(self))
        self.add_item(ActionButton(self, "目標を入力", "goal_modal", discord.ButtonStyle.primary,
                                   "🎯", row=2))
        self.add_item(ActionButton(self, "リマインド時刻", "remind_modal",
                                   discord.ButtonStyle.primary, "⏰", row=2))
        self.add_item(ActionButton(self, "目標・リマインドを消す", "me_clear",
                                   discord.ButtonStyle.danger, "🗑", row=2))

    # ---- 変更処理 ----------------------------------------------------------
    def apply_pomodoro(self, cfg: PomodoroConfig | None) -> None:
        if cfg is None:
            self.bot.db.update_config(self.guild.id, pomo_work=None, pomo_short=None,
                                      pomo_long=None, pomo_every=None)
        else:
            self.bot.db.update_config(self.guild.id, pomo_work=cfg.work_min,
                                      pomo_short=cfg.short_break_min,
                                      pomo_long=cfg.long_break_min,
                                      pomo_every=cfg.long_break_every)

    def apply_ranking(self, channel_id: int | None, hhmm: str | None = None) -> None:
        if channel_id is None:
            self.bot.db.update_config(self.guild.id, ranking_channel_id=None, ranking_time=None)
            return
        hhmm = hhmm or self.cfg.ranking_time or DEFAULT_RANKING_TIME
        now = time.time()
        last = date_key(now, self.bot.tz) if is_due(now, self.bot.tz, hhmm, None) else None
        self.bot.db.update_config(self.guild.id, ranking_channel_id=channel_id,
                                  ranking_time=hhmm, last_ranking_date=last)

    def apply_reminder(self, hhmm: str | None) -> None:
        gid, uid = self.guild.id, self.user.id
        if hhmm is None:
            self.bot.db.clear_reminder(gid, uid)
            return
        self.bot.db.set_reminder(gid, uid, hhmm)
        now = time.time()
        if is_due(now, self.bot.tz, hhmm, None):  # 今日の時刻を過ぎていれば明日から
            self.bot.db.mark_reminder_sent(gid, uid, date_key(now, self.bot.tz))

    def apply_volume(self, percent: int) -> None:
        self.bot.db.update_config(self.guild.id, music_volume=percent)
        state = self.bot.music.get(self.guild.id)
        if state is not None:
            state.volume = percent / 100
        voice = self.guild.voice_client
        if isinstance(voice, discord.VoiceClient) and isinstance(voice.source,
                                                                 discord.PCMVolumeTransformer):
            voice.source.volume = percent / 100


# ---- 部品 -----------------------------------------------------------------
class SectionSelect(discord.ui.Select):
    def __init__(self, view: SetupView):
        keys = [k for k in SECTIONS if view.is_admin or k not in ADMIN_SECTIONS]
        options = [discord.SelectOption(label=SECTIONS[k][0], description=SECTIONS[k][1], value=k,
                                        default=(k == view.section)) for k in keys]
        super().__init__(placeholder="設定する項目を選ぶ", options=options, row=0)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.setup.section = self.values[0]
        await self.setup.refresh(interaction)


class ActionButton(discord.ui.Button):
    def __init__(self, view: SetupView, label: str, action: str, style: discord.ButtonStyle,
                 emoji: str | None = None, row: int = 1):
        super().__init__(label=label, style=style, emoji=emoji, row=row)
        self.setup = view
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        v = self.setup
        gid, uid = v.guild.id, v.user.id
        if self.action == "study_all":
            v.bot.db.set_study_channels(gid, set())
            v.bot.reconcile_guild(v.guild)
            return await v.refresh(interaction, "✅ AFK以外のすべてのVCを記録対象にしました。")
        if self.action == "pomo_reset":
            v.apply_pomodoro(None)
            return await v.refresh(interaction, "✅ ポモドーロを初期値（25/5/15、4回ごと）に戻しました。")
        if self.action == "auto_music_modal":
            return await interaction.response.send_modal(AutoMusicModal(v))
        if self.action == "pomo_modal":
            return await interaction.response.send_modal(PomodoroModal(v))
        if self.action == "notify_modal":
            return await interaction.response.send_modal(NotifyTimeModal(v))
        if self.action == "goal_modal":
            return await interaction.response.send_modal(GoalModal(v))
        if self.action == "remind_modal":
            return await interaction.response.send_modal(ReminderModal(v))
        if self.action == "me_clear":
            v.bot.db.clear_goal(gid, uid)
            v.bot.db.clear_reminder(gid, uid)
            return await v.refresh(interaction, "🗑 目標とリマインドを消しました。")


def _channels(guild: discord.Guild, ids) -> list:
    return [ch for cid in ids if (ch := guild.get_channel(cid)) is not None]


class StudyChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: SetupView):
        current = _channels(view.guild, sorted(view.bot.db.study_channels(view.guild.id)))
        super().__init__(placeholder="記録するVCを選ぶ（複数可）",
                         channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice],
                         min_values=0, max_values=25, default_values=current[:25], row=1)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        v = self.setup
        v.bot.db.set_study_channels(v.guild.id, {c.id for c in self.values})
        v.bot.reconcile_guild(v.guild)
        msg = (f"✅ 記録するVCを{len(self.values)}個にしました。" if self.values
               else "✅ AFK以外のすべてのVCを記録対象にしました。")
        await v.refresh(interaction, msg)


class AutoChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: SetupView):
        cid = view.cfg.auto_channel_id
        super().__init__(placeholder="🚀 入ったら自動開始するVC（未選択で /start のみ）",
                         channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice],
                         min_values=0, max_values=1,
                         default_values=_channels(view.guild, [cid] if cid else []), row=1)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        cid = self.values[0].id if self.values else None
        self.setup.bot.db.update_config(self.setup.guild.id, auto_channel_id=cid)
        msg = ("✅ そのVCに入ると集中セッションを自動で開始します。" if cid
               else "✅ VCに入ったときの自動開始をオフにしました（/start は使えます）。")
        await self.setup.refresh(interaction, msg)


class AutoFeatureSelect(discord.ui.Select):
    def __init__(self, view: SetupView):
        c = view.cfg
        options = [
            discord.SelectOption(label="ポモドーロを開始", value="pomodoro", emoji="🍅",
                                 description="ポモドーロの項目で決めた時間で開始",
                                 default=(c.auto_pomodoro != 0)),
            discord.SelectOption(label="音楽を再生", value="music", emoji="🎵",
                                 description="「流す音楽を設定」の曲・プレイリストを全曲ループ",
                                 default=(c.auto_music != 0)),
        ]
        super().__init__(placeholder="開始する内容（複数可）", options=options,
                         min_values=0, max_values=2, row=2)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        chosen = set(self.values)
        self.setup.bot.db.update_config(self.setup.guild.id,
                                        auto_pomodoro=int("pomodoro" in chosen),
                                        auto_music=int("music" in chosen))
        await self.setup.refresh(interaction, "✅ 開始する内容を変更しました。")


class PomodoroPresetSelect(discord.ui.Select):
    def __init__(self, view: SetupView):
        d = view.bot.pomodoro_defaults(view.guild.id)
        now = f"{d.work_min}-{d.short_break_min}-{d.long_break_min}-{d.long_break_every}"
        options = [discord.SelectOption(label=label, value=key, default=(key == now))
                   for key, label in POMODORO_PRESETS.items()]
        super().__init__(placeholder="プリセットから選ぶ", options=options, row=1)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        work, short, long_, every = (int(x) for x in self.values[0].split("-"))
        self.setup.apply_pomodoro(PomodoroConfig(work, short, long_, every))
        await self.setup.refresh(interaction, f"✅ ポモドーロを「{POMODORO_PRESETS[self.values[0]]}」にしました。")


class NotifyChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: SetupView):
        current = _channels(view.guild, [view.cfg.notify_channel_id] if view.cfg.notify_channel_id else [])
        super().__init__(placeholder="🔔 通知先のチャンネル（未選択でVCのチャット）",
                         channel_types=[discord.ChannelType.text], min_values=0, max_values=1,
                         default_values=current, row=1)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        cid = self.values[0].id if self.values else None
        self.setup.bot.db.update_config(self.setup.guild.id, notify_channel_id=cid)
        await self.setup.refresh(interaction, "✅ 通知先を変更しました。")


class RankingChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: SetupView):
        cid = view.cfg.ranking_channel_id
        current = _channels(view.guild, [cid] if cid else [])
        super().__init__(placeholder="🏆 ランキングの投稿先（未選択でオフ）",
                         channel_types=[discord.ChannelType.text], min_values=0, max_values=1,
                         default_values=current, row=2)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        cid = self.values[0].id if self.values else None
        self.setup.apply_ranking(cid)
        await self.setup.refresh(interaction, "✅ ランキングの自動投稿を変更しました。")


class AutoDeleteSelect(discord.ui.ChannelSelect):
    def __init__(self, view: SetupView):
        ids = [cid for _, cid, _h in view.bot.db.auto_delete_rules(view.guild.id)]
        super().__init__(placeholder="🧹 自動削除するチャンネル（VCのチャットも可・複数可）",
                         channel_types=[discord.ChannelType.text, discord.ChannelType.voice,
                                        discord.ChannelType.stage_voice],
                         min_values=0, max_values=25, default_values=_channels(view.guild, ids)[:25],
                         row=3)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        v = self.setup
        hours = v._delete_hours()
        v.bot.db.set_auto_delete_channels(v.guild.id, {c.id for c in self.values}, hours)
        msg = (f"✅ {len(self.values)}個のチャンネルで{hours}時間たったメッセージを自動削除します"
               "（10分ごとに確認）。" if self.values else "✅ チャットの自動削除をオフにしました。")
        await v.refresh(interaction, msg)


class VolumeSelect(discord.ui.Select):
    def __init__(self, view: SetupView):
        c = view.cfg
        now = c.music_volume if c.music_volume is not None else round(view.bot.settings.default_volume * 100)
        options = [discord.SelectOption(label=f"音量 {p}%", value=str(p), default=(p == now))
                   for p in VOLUME_CHOICES]
        if now not in VOLUME_CHOICES:
            options.insert(0, discord.SelectOption(label=f"音量 {now}%（現在）", value=str(now),
                                                   default=True))
        super().__init__(placeholder="既定の音量", options=options, row=1)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        percent = int(self.values[0])
        self.setup.apply_volume(percent)
        await self.setup.refresh(interaction, f"🔊 既定の音量を{percent}%にしました。")


class SourceSelect(discord.ui.Select):
    def __init__(self, view: SetupView):
        now = view.cfg.music_source or music_mod.YTM
        options = [
            discord.SelectOption(label="YouTube Music で検索", value=music_mod.YTM,
                                 description="曲・アルバム中心。おすすめ", default=(now == music_mod.YTM)),
            discord.SelectOption(label="YouTube で検索", value=music_mod.YOUTUBE,
                                 description="作業用BGMの長尺動画やライブ配信",
                                 default=(now == music_mod.YOUTUBE)),
        ]
        super().__init__(placeholder="曲名で検索するサービス", options=options, row=2)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.setup.bot.db.update_config(self.setup.guild.id, music_source=self.values[0])
        await self.setup.refresh(interaction, "✅ 検索サービスを変更しました。")


class GoalPresetSelect(discord.ui.Select):
    def __init__(self, view: SetupView):
        goal = view.bot.db.get_goal(view.guild.id, view.user.id)
        now = goal[0] if goal else None
        options = [discord.SelectOption(label=f"目標 {format_duration(m * 60)}", value=str(m),
                                        default=(m == now)) for m in GOAL_PRESETS]
        super().__init__(placeholder="1日の目標を選ぶ", options=options, row=1)
        self.setup = view

    async def callback(self, interaction: discord.Interaction) -> None:
        minutes = int(self.values[0])
        self.setup.bot.db.set_goal(self.setup.guild.id, self.setup.user.id, minutes)
        await self.setup.refresh(interaction, f"🎯 1日の目標を{format_duration(minutes * 60)}にしました。")


# ---- 入力フォーム ------------------------------------------------------------
class _Modal(discord.ui.Modal):
    def __init__(self, view: SetupView, title: str):
        super().__init__(title=title, timeout=300)
        self.setup = view

    async def fail(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.response.send_message(f"⚠️ {message}", ephemeral=True)


def _int(text: str, name: str) -> int:
    try:
        return int(text.strip())
    except ValueError:
        raise ValueError(f"{name}は数字で入力してください。") from None


class AutoMusicModal(_Modal):
    def __init__(self, view: SetupView):
        super().__init__(view, "自動開始で流す音楽")
        self.query = discord.ui.TextInput(
            label="曲名・URL・プレイリスト（空欄でおすすめ）",
            placeholder="例: https://music.youtube.com/playlist?list=... / lofi study",
            default=view.cfg.auto_music_query or "", required=False, max_length=300)
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        v = self.setup
        text = self.query.value.strip()
        v.bot.db.update_config(v.guild.id, auto_music_query=text or None, auto_music=1)
        await v.refresh(interaction, f"🎵 自動開始で「{text}」を流します。" if text
                        else "🎵 自動開始では勉強向けのおすすめをランダムに流します。")


class PomodoroModal(_Modal):
    def __init__(self, view: SetupView):
        super().__init__(view, "ポモドーロの時間")
        d = view.bot.pomodoro_defaults(view.guild.id)
        self.work = discord.ui.TextInput(label="作業時間（分、1〜180）", default=str(d.work_min), max_length=3)
        self.short = discord.ui.TextInput(label="休憩時間（分、1〜180）", default=str(d.short_break_min),
                                          max_length=3)
        self.long = discord.ui.TextInput(label="長い休憩（分、1〜180）", default=str(d.long_break_min),
                                         max_length=3)
        self.every = discord.ui.TextInput(label="何回ごとに長い休憩にするか（1〜12）",
                                          default=str(d.long_break_every), max_length=2)
        for item in (self.work, self.short, self.long, self.every):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            cfg = PomodoroConfig(_int(self.work.value, "作業時間"), _int(self.short.value, "休憩時間"),
                                 _int(self.long.value, "長い休憩"), _int(self.every.value, "回数"))
        except ValueError as e:
            return await self.fail(interaction, str(e))
        self.setup.apply_pomodoro(cfg)
        await self.setup.refresh(interaction, "✅ ポモドーロの時間を変更しました。")


class NotifyTimeModal(_Modal):
    def __init__(self, view: SetupView):
        super().__init__(view, "時刻・削除までの時間")
        self.time = discord.ui.TextInput(label="ランキングの投稿時刻（例 07:00）",
                                         default=view.cfg.ranking_time or DEFAULT_RANKING_TIME,
                                         max_length=5)
        self.hours = discord.ui.TextInput(label="自動削除までの時間（時間、1〜168）",
                                          default=str(view._delete_hours()), max_length=3)
        self.add_item(self.time)
        self.add_item(self.hours)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        v = self.setup
        try:
            hhmm = parse_hhmm(self.time.value)
            hours = _int(self.hours.value, "削除までの時間")
            if not 1 <= hours <= 168:
                raise ValueError("削除までの時間は1〜168時間で入力してください。")
        except ValueError as e:
            return await self.fail(interaction, str(e))
        cfg = v.cfg
        if cfg.ranking_channel_id:
            v.apply_ranking(cfg.ranking_channel_id, hhmm)
        else:
            v.bot.db.update_config(v.guild.id, ranking_time=hhmm)
        ids = {cid for _, cid, _h in v.bot.db.auto_delete_rules(v.guild.id)}
        if ids:
            v.bot.db.set_auto_delete_channels(v.guild.id, ids, hours)
        note = f"✅ ランキングの投稿時刻を{hhmm}にしました。"
        note += (f" 自動削除は{hours}時間にしました。" if ids
                 else " 自動削除するチャンネルを選ぶと、その時間で削除します。")
        if not ids:
            # まだ対象が無いときも、次に選んだチャンネルで使えるよう既定値を覚えておく
            v._pending_hours = hours
        await v.refresh(interaction, note)


class GoalModal(_Modal):
    def __init__(self, view: SetupView):
        super().__init__(view, "1日の目標")
        goal = view.bot.db.get_goal(view.guild.id, view.user.id)
        self.minutes = discord.ui.TextInput(label="目標（分、1〜1440。空欄で削除）",
                                            default=str(goal[0]) if goal else "",
                                            required=False, max_length=4)
        self.add_item(self.minutes)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        v = self.setup
        text = self.minutes.value.strip()
        if not text:
            v.bot.db.clear_goal(v.guild.id, v.user.id)
            return await v.refresh(interaction, "🗑 目標を消しました。")
        try:
            minutes = _int(text, "目標")
            if not 1 <= minutes <= 1440:
                raise ValueError("目標は1〜1440分で入力してください。")
        except ValueError as e:
            return await self.fail(interaction, str(e))
        v.bot.db.set_goal(v.guild.id, v.user.id, minutes)
        await v.refresh(interaction, f"🎯 1日の目標を{format_duration(minutes * 60)}にしました。")


class ReminderModal(_Modal):
    def __init__(self, view: SetupView):
        super().__init__(view, "毎日のリマインド")
        now = view.bot.db.get_reminder(view.guild.id, view.user.id)
        self.time = discord.ui.TextInput(label="時刻（例 21:00。空欄で停止）", default=now or "",
                                         required=False, max_length=5)
        self.add_item(self.time)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        v = self.setup
        text = self.time.value.strip()
        if not text:
            v.apply_reminder(None)
            return await v.refresh(interaction, "🗑 リマインドを停止しました。")
        try:
            hhmm = parse_hhmm(text)
        except ValueError as e:
            return await self.fail(interaction, str(e))
        v.apply_reminder(hhmm)
        await v.refresh(interaction, f"⏰ 毎日{hhmm}にリマインドします。")
