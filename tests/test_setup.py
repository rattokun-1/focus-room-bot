"""/setup パネルの組み立てと操作（Discordに接続せずに確認）。"""
import asyncio
import sqlite3
from types import SimpleNamespace

import discord

from study_bot.commands import register_commands
from study_bot.db import Database
from study_bot.setup_view import ADMIN_SECTIONS, SECTIONS, SetupView
from tests.test_bot import make_bot


def fake_guild(gid=1):
    return SimpleNamespace(id=gid, name="g", afk_channel=None, me=None, voice_client=None,
                           get_channel=lambda cid: None, voice_channels=[], stage_channels=[])


def fake_user(admin: bool, uid=10):
    return SimpleNamespace(id=uid, guild_permissions=SimpleNamespace(manage_guild=admin))


class FakeResponse:
    def __init__(self):
        self.edits = []
        self.modals = []
        self.messages = []

    async def edit_message(self, **kw):
        self.edits.append(kw)

    async def send_modal(self, modal):
        self.modals.append(modal)

    async def send_message(self, content=None, **kw):
        self.messages.append(content)


def fake_interaction(user):
    return SimpleNamespace(user=user, response=FakeResponse())


def run(coro_fn):
    return asyncio.run(coro_fn())


def test_setup_command_registered():
    bot = make_bot()
    register_commands(bot)
    assert "setup" in {c.name for c in bot.tree.get_commands()}


def test_all_sections_build_for_admin():
    bot = make_bot()

    async def go():
        for key in SECTIONS:
            view = SetupView(bot, fake_guild(), fake_user(True), section=key)
            assert view.section == key
            assert len(view.children) <= 25
            assert max(item.row or 0 for item in view.children) <= 4
            embed = view.embed()
            assert embed.title.endswith(SECTIONS[key][0])
            assert len(embed) < 6000

    run(go)


def test_non_admin_only_sees_personal_sections():
    bot = make_bot()

    async def go():
        view = SetupView(bot, fake_guild(), fake_user(False), section="pomodoro")
        assert view.section == "me"  # 管理者用の項目は開けない
        menu = view.children[0]
        assert {o.value for o in menu.options} == set(SECTIONS) - ADMIN_SECTIONS

    run(go)


def _pick(view, cls_name):
    return next(c for c in view.children if type(c).__name__ == cls_name)


def test_pomodoro_preset_and_reset():
    bot = make_bot()
    user = fake_user(True)

    async def go():
        view = SetupView(bot, fake_guild(), user, section="pomodoro")
        sel = _pick(view, "PomodoroPresetSelect")
        sel._values = ["50-10-20-3"]
        inter = fake_interaction(user)
        await sel.callback(inter)
        d = bot.pomodoro_defaults(1)
        assert (d.work_min, d.short_break_min, d.long_break_min, d.long_break_every) == (50, 10, 20, 3)
        assert "50分" in inter.response.edits[-1]["embed"].fields[0].value
        reset = next(c for c in view.children if getattr(c, "action", "") == "pomo_reset")
        await reset.callback(fake_interaction(user))
        assert bot.pomodoro_defaults(1).work_min == 25

    run(go)


def test_pomodoro_modal_validation():
    bot = make_bot()
    user = fake_user(True)

    async def go():
        view = SetupView(bot, fake_guild(), user, section="pomodoro")
        btn = next(c for c in view.children if getattr(c, "action", "") == "pomo_modal")
        inter = fake_interaction(user)
        await btn.callback(inter)
        modal = inter.response.modals[0]
        modal.work._value = "abc"
        bad = fake_interaction(user)
        await modal.on_submit(bad)
        assert "数字" in bad.response.messages[0] and not bad.response.edits
        modal.work._value, modal.every._value = "40", "2"
        ok = fake_interaction(user)
        await modal.on_submit(ok)
        assert bot.pomodoro_defaults(1).work_min == 40 and ok.response.edits

    run(go)


def test_music_and_personal_settings():
    bot = make_bot()
    user = fake_user(False)
    admin = fake_user(True, uid=11)

    async def go():
        mview = SetupView(bot, fake_guild(), admin, section="music")
        vol = _pick(mview, "VolumeSelect")
        vol._values = ["30"]
        await vol.callback(fake_interaction(admin))
        src = _pick(mview, "SourceSelect")
        src._values = ["youtube"]
        await src.callback(fake_interaction(admin))
        assert bot.music_for(1).volume == 0.3 and bot.music_source(1) == "youtube"

        view = SetupView(bot, fake_guild(), user, section="me")
        goal = _pick(view, "GoalPresetSelect")
        goal._values = ["120"]
        await goal.callback(fake_interaction(user))
        assert bot.db.get_goal(1, 10)[0] == 120
        btn = next(c for c in view.children if getattr(c, "action", "") == "remind_modal")
        inter = fake_interaction(user)
        await btn.callback(inter)
        modal = inter.response.modals[0]
        modal.time._value = "21:30"
        await modal.on_submit(fake_interaction(user))
        assert bot.db.get_reminder(1, 10) == "21:30"
        clear = next(c for c in view.children if getattr(c, "action", "") == "me_clear")
        await clear.callback(fake_interaction(user))
        assert bot.db.get_goal(1, 10) is None and bot.db.get_reminder(1, 10) is None

    run(go)


def test_migration_adds_columns_to_old_db(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE guild_config (guild_id INTEGER PRIMARY KEY, notify_channel_id INTEGER,"
                 " ranking_channel_id INTEGER, ranking_time TEXT, last_ranking_date TEXT)")
    conn.execute("INSERT INTO guild_config (guild_id, notify_channel_id) VALUES (1, 5)")
    conn.commit()
    conn.close()
    db = Database(path)
    db.update_config(1, pomo_work=50, music_source="youtube")
    c = db.get_config(1)
    assert (c.notify_channel_id, c.pomo_work, c.music_source) == (5, 50, "youtube")
    db.close()
