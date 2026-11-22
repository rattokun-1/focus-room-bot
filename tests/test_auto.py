"""自動開始（VC入室・/start）と /stop の動作。"""
import asyncio
from types import SimpleNamespace

from study_bot import music as music_mod
from study_bot.setup_view import SetupView
from tests.test_bot import make_bot
from tests.test_setup import fake_interaction, fake_user


def fake_channel(cid=100, sent=None):
    async def send(content=None, **kw):
        if sent is not None:
            sent.append(content)
    return SimpleNamespace(id=cid, members=[], send=send, mention=f"<#{cid}>")


def fake_guild(gid=1, channel=None):
    return SimpleNamespace(id=gid, name="g", afk_channel=None, me=None, voice_client=None,
                           get_channel=lambda cid: channel if channel and cid == channel.id else None,
                           voice_channels=[], stage_channels=[])


def test_auto_start_pomodoro_only_and_no_duplicate():
    bot = make_bot()
    bot.db.update_config(1, auto_music=0)
    ch = fake_channel()

    async def go():
        lines, started = await bot.auto_start(fake_guild(channel=ch), ch, 10)
        assert started and "ポモドーロ開始" in lines[0] and 100 in bot.pomodoros
        lines, started = await bot.auto_start(fake_guild(channel=ch), ch, 11)
        assert not started and "実行中" in lines[0]

    asyncio.run(go())


def test_auto_start_uses_guild_defaults_and_music(monkeypatch):
    bot = make_bot()
    bot.db.update_config(1, pomo_work=50, pomo_short=10, auto_music_query="lofi")
    ch = fake_channel()
    calls = {}

    async def connect_voice(channel):
        return SimpleNamespace(channel=channel)

    async def resolve(query, source, uid):
        calls["resolve"] = (query, source)
        return [music_mod.Track("lofi song", "u", 60, False, uid)], None

    async def queue_tracks(guild, voice, tracks):
        bot.music_for(guild.id).current = tracks[0]
        return True, 1

    monkeypatch.setattr(bot, "connect_voice", connect_voice)
    monkeypatch.setattr(music_mod, "resolve", resolve)
    monkeypatch.setattr(bot, "queue_tracks", queue_tracks)

    lines, started = asyncio.run(bot.auto_start(fake_guild(channel=ch), ch, 10))
    assert started
    assert "50分" in lines[0] and "再生開始" in lines[1] and "lofi song" in lines[1]
    assert calls["resolve"] == ("lofi", "ytmusic")
    assert bot.music[1].loop_mode == "all"


def test_auto_start_reports_music_error(monkeypatch):
    bot = make_bot()
    bot.db.update_config(1, auto_pomodoro=0)
    ch = fake_channel()

    async def connect_voice(channel):
        raise music_mod.MusicError("接続できません")

    monkeypatch.setattr(bot, "connect_voice", connect_voice)
    lines, started = asyncio.run(bot.auto_start(fake_guild(channel=ch), ch, 10))
    assert not started and "接続できません" in lines[0]


def test_joining_auto_channel_triggers_start(monkeypatch):
    bot = make_bot()
    bot.db.update_config(1, auto_channel_id=100)
    sent = []
    ch = fake_channel(100, sent)
    guild = fake_guild(channel=ch)
    member = SimpleNamespace(id=10, bot=False, guild=guild, mention="<@10>")
    called = []

    async def auto_start(g, channel, uid):
        called.append((channel.id, uid))
        return ["🍅 ポモドーロ開始"], True

    monkeypatch.setattr(bot, "auto_start", auto_start)

    async def go():
        await bot.on_voice_state_update(member, SimpleNamespace(channel=None),
                                        SimpleNamespace(channel=ch))
        await asyncio.gather(*bot._tasks)
        # 別のVCへの入室では開始しない
        other = fake_channel(200)
        await bot.on_voice_state_update(member, SimpleNamespace(channel=ch),
                                        SimpleNamespace(channel=other))
        await asyncio.gather(*bot._tasks)

    asyncio.run(go())
    assert called == [(100, 10)]
    assert sent and "<@10>" in sent[0] and "集中セッション" in sent[0]


def test_stop_session_stops_pomodoro():
    bot = make_bot()
    bot.db.update_config(1, auto_music=0)
    ch = fake_channel()
    guild = fake_guild(channel=ch)

    async def go():
        await bot.auto_start(guild, ch, 10)
        lines = await bot.stop_session(guild, ch)
        assert "ポモドーロを終了" in lines[0] and 100 not in bot.pomodoros
        assert await bot.stop_session(guild, ch) == []

    asyncio.run(go())


def test_setup_auto_section():
    bot = make_bot()
    admin = fake_user(True)

    async def go():
        view = SetupView(bot, fake_guild(), admin, section="auto")
        feat = next(c for c in view.children if type(c).__name__ == "AutoFeatureSelect")
        feat._values = ["pomodoro"]
        await feat.callback(fake_interaction(admin))
        c = bot.db.get_config(1)
        assert (c.auto_pomodoro, c.auto_music) == (1, 0)
        btn = next(c for c in view.children if getattr(c, "action", "") == "auto_music_modal")
        inter = fake_interaction(admin)
        await btn.callback(inter)
        modal = inter.response.modals[0]
        modal.query._value = "https://music.youtube.com/playlist?list=PL1"
        done = fake_interaction(admin)
        await modal.on_submit(done)
        c = bot.db.get_config(1)
        assert c.auto_music == 1 and c.auto_music_query.endswith("PL1")
        assert "PL1" in done.response.edits[-1]["embed"].fields[1].value

    asyncio.run(go())
