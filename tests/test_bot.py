"""Discordに接続せず、コマンド登録と主要なイベント処理を確かめる。"""
import asyncio
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from study_bot.bot import StudyBot
from study_bot.commands import register_commands
from study_bot.config import Settings
from study_bot.db import Database


def make_bot():
    settings = Settings(token="x", db_path=Path(":memory:"), tz=ZoneInfo("Asia/Tokyo"),
                        dev_guild_id=None, ffmpeg_path="ffmpeg", default_volume=0.15)
    return StudyBot(settings, db=Database(":memory:"))


def test_commands_register():
    bot = make_bot()
    register_commands(bot)
    names = {c.name for c in bot.tree.get_commands()}
    assert names == {"setup", "start", "stop", "stats", "ranking", "pomodoro", "goal", "remind", "music",
                     "studyconfig"}
    music = bot.tree.get_command("music")
    assert {c.name for c in music.commands} == {"play", "recommend", "pause", "resume", "skip", "stop", "volume", "loop",
                                                "shuffle", "queue"}
    cfg = bot.tree.get_command("studyconfig")
    assert cfg.default_permissions.manage_guild


def fake_guild(gid=1, afk=None):
    return SimpleNamespace(id=gid, afk_channel=afk, name="g", get_channel=lambda cid: None,
                           voice_channels=[], stage_channels=[])


def vstate(cid):
    return SimpleNamespace(channel=SimpleNamespace(id=cid, members=[]) if cid else None)


def test_voice_state_updates_record_sessions():
    bot = make_bot()
    guild = fake_guild()
    member = SimpleNamespace(id=10, bot=False, guild=guild)

    async def run():
        await bot.on_voice_state_update(member, vstate(None), vstate(100))
        assert [(s.user_id, s.channel_id) for s in bot.db.open_sessions(1)] == [(10, 100)]
        await bot.on_voice_state_update(member, vstate(100), vstate(200))
        assert [(s.user_id, s.channel_id) for s in bot.db.open_sessions(1)] == [(10, 200)]
        await bot.on_voice_state_update(member, vstate(200), vstate(None))
        assert bot.db.open_sessions(1) == []

    asyncio.run(run())


def test_bots_are_not_recorded():
    bot = make_bot()
    member = SimpleNamespace(id=99, bot=True, guild=fake_guild())
    asyncio.run(bot.on_voice_state_update(member, vstate(None), vstate(100)))
    assert bot.db.open_sessions() == []


def test_goal_notification_sent_once():
    bot = make_bot()
    guild = fake_guild()
    sent = []
    channel = SimpleNamespace(id=100, send=None)

    async def send(content=None, **kw):
        sent.append(content)

    channel.send = send
    guild.get_channel = lambda cid: channel if cid == 100 else None
    # 日付をまたがないよう日本時間の正午に固定する
    now = datetime(2026, 11, 21, 12, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp()
    bot.db.set_goal(1, 10, 30)
    bot.db.start_session(1, 10, 100, now - 31 * 60)

    async def run():
        await bot.check_goal(guild, 10, 100, now)
        await bot.check_goal(guild, 10, 100, now + 60)

    asyncio.run(run())
    assert len(sent) == 1 and "<@10>" in sent[0] and "達成" in sent[0]


def test_ranking_embed_builds():
    bot = make_bot()
    now = time.time()
    bot.db.start_session(1, 10, 100, now - 3600)
    embed = bot.ranking_embed(1, "today", now)
    assert "今日" in embed.title and "<@10>" in embed.description


def test_commands_include_auto_delete():
    bot = make_bot()
    register_commands(bot)
    cfg = bot.tree.get_command("studyconfig")
    assert {"auto-delete", "auto-delete-off"} <= {c.name for c in cfg.commands}


def test_purge_old_messages_keeps_pins_and_uses_cutoff():
    bot = make_bot()
    calls = {}
    now = datetime(2026, 11, 22, 12, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp()

    async def purge(limit, before, check, reason):
        calls.update(limit=limit, before=before)
        msgs = [SimpleNamespace(pinned=False), SimpleNamespace(pinned=True)]
        return [m for m in msgs if check(m)]

    channel = SimpleNamespace(name="focus", purge=purge)
    deleted = asyncio.run(bot.purge_old_messages(channel, 24, now))
    assert deleted == 1
    assert calls["before"].timestamp() == now - 24 * 3600


def test_purge_old_messages_handles_forbidden():
    import discord

    bot = make_bot()

    async def purge(**kw):
        raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "no")

    channel = SimpleNamespace(name="focus", purge=purge)
    assert asyncio.run(bot.purge_old_messages(channel, 24, time.time())) == 0
