from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from study_bot.db import Database, OpenSession
from study_bot.formatting import goal_text, progress_bar, ranking_text
from study_bot.music import GuildMusic, MusicError, Track, select_stream, track_from_info
from study_bot.pomodoro import LONG_BREAK, SHORT_BREAK, WORK, PomodoroConfig, PomodoroSession
from study_bot.timeutil import (day_bounds, format_duration, is_due, parse_hhmm,
                                week_bounds)
from study_bot.tracking import is_study_channel, reconcile, transition

JST = ZoneInfo("Asia/Tokyo")


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=JST).timestamp()


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


# ---- timeutil ------------------------------------------------------------
def test_day_and_week_bounds_jst():
    now = ts(2026, 11, 21, 15)  # 土曜
    assert day_bounds(now, JST) == (ts(2026, 11, 21), ts(2026, 11, 22))
    assert day_bounds(now, JST, 1) == (ts(2026, 11, 20), ts(2026, 11, 21))
    assert week_bounds(now, JST) == (ts(2026, 11, 16), ts(2026, 11, 23))
    assert week_bounds(now, JST, 1) == (ts(2026, 11, 9), ts(2026, 11, 16))


def test_parse_hhmm():
    assert parse_hhmm("7:05") == "07:05"
    assert parse_hhmm(" 21:00 ") == "21:00"
    for bad in ("24:00", "7", "12:60", "ab:cd"):
        with pytest.raises(ValueError):
            parse_hhmm(bad)


def test_is_due():
    now = ts(2026, 11, 21, 21, 30)
    assert is_due(now, JST, "21:00", None)
    assert is_due(now, JST, "21:00", "2026-11-20")
    assert not is_due(now, JST, "21:00", "2026-11-21")
    assert not is_due(now, JST, "22:00", None)


def test_format_duration():
    assert format_duration(59) == "0分"
    assert format_duration(60 * 5) == "5分"
    assert format_duration(3600) == "1時間"
    assert format_duration(3600 * 2 + 60 * 3 + 30) == "2時間3分"


# ---- db -----------------------------------------------------------------
def test_session_split_across_midnight(db):
    db.start_session(1, 10, 100, ts(2026, 11, 20, 23))
    db.end_session(1, 10, ts(2026, 11, 21, 1, 30))
    lo, hi = day_bounds(ts(2026, 11, 21, 12), JST)
    assert db.user_seconds(1, 10, lo, hi, ts(2026, 11, 21, 12)) == 90 * 60
    lo, hi = day_bounds(ts(2026, 11, 21, 12), JST, 1)
    assert db.user_seconds(1, 10, lo, hi, ts(2026, 11, 21, 12)) == 60 * 60


def test_open_session_counts_until_now(db):
    db.start_session(1, 10, 100, ts(2026, 11, 21, 9))
    lo, hi = day_bounds(ts(2026, 11, 21, 9), JST)
    assert db.user_seconds(1, 10, lo, hi, ts(2026, 11, 21, 9, 45)) == 45 * 60


def test_start_session_closes_previous(db):
    db.start_session(1, 10, 100, ts(2026, 11, 21, 9))
    db.start_session(1, 10, 200, ts(2026, 11, 21, 10))
    opens = db.open_sessions(1)
    assert [(s.user_id, s.channel_id) for s in opens] == [(10, 200)]


def test_close_stale_uses_last_seen(db):
    db.start_session(1, 10, 100, ts(2026, 11, 21, 9))
    db.heartbeat(ts(2026, 11, 21, 9, 20))
    assert db.close_stale_sessions() == 1
    lo, hi = day_bounds(ts(2026, 11, 21, 9), JST)
    assert db.user_seconds(1, 10, lo, hi, ts(2026, 11, 21, 23)) == 20 * 60
    assert db.open_sessions() == []


def test_ranking_and_rank(db):
    base = ts(2026, 11, 21, 8)
    for uid, mins in ((10, 30), (11, 90), (12, 60)):
        db.start_session(1, uid, 100, base)
        db.end_session(1, uid, base + mins * 60)
    db.start_session(2, 99, 100, base)  # 別サーバーは含めない
    db.end_session(2, 99, base + 999 * 60)
    lo, hi = day_bounds(base, JST)
    rows = db.ranking(1, lo, hi, base + 10**5)
    assert rows == [(11, 5400.0), (12, 3600.0), (10, 1800.0)]
    assert db.user_rank(1, 10, lo, hi, base + 10**5) == 3
    assert db.user_rank(1, 77, lo, hi, base + 10**5) is None


def test_config_upsert(db):
    assert db.get_config(1).notify_channel_id is None
    db.update_config(1, notify_channel_id=5)
    db.update_config(1, ranking_channel_id=6, ranking_time="07:00")
    c = db.get_config(1)
    assert (c.notify_channel_id, c.ranking_channel_id, c.ranking_time) == (5, 6, "07:00")
    with pytest.raises(ValueError):
        db.update_config(1, bogus=1)


def test_goal_and_reminder(db):
    db.set_goal(1, 10, 120)
    db.mark_goal_achieved(1, 10, "2026-11-21")
    assert db.get_goal(1, 10) == (120, "2026-11-21")
    db.set_goal(1, 10, 180)  # 目標を変えたら達成済みフラグはリセット
    assert db.get_goal(1, 10) == (180, None)
    db.set_reminder(1, 10, "21:00")
    db.mark_reminder_sent(1, 10, "2026-11-21")
    assert db.all_reminders() == [(1, 10, "21:00", "2026-11-21")]
    db.set_reminder(1, 10, "22:00")
    assert db.all_reminders() == [(1, 10, "22:00", None)]
    assert db.clear_reminder(1, 10) and not db.clear_reminder(1, 10)


def test_auto_delete_rules(db):
    db.set_auto_delete(1, 100, 24)
    db.set_auto_delete(1, 100, 12)
    db.set_auto_delete(2, 200, 48)
    assert db.auto_delete_rules(1) == [(1, 100, 12)]
    assert len(db.auto_delete_rules()) == 2
    assert db.remove_auto_delete(1, 100) and not db.remove_auto_delete(1, 100)


def test_study_channels(db):
    db.add_study_channel(1, 100)
    db.add_study_channel(1, 100)
    assert db.study_channels(1) == {100}
    assert db.remove_study_channel(1, 100)
    assert db.study_channels(1) == set()


# ---- tracking -------------------------------------------------------------
def test_is_study_channel():
    assert is_study_channel(5, set(), afk_channel_id=9)
    assert not is_study_channel(9, set(), afk_channel_id=9)
    assert not is_study_channel(None, set(), None)
    assert is_study_channel(5, {5}, None)
    assert not is_study_channel(6, {5}, None)


def test_transition():
    study = {1, 2}.__contains__
    assert transition(None, 1, study) == [("start", 1)]
    assert transition(1, None, study) == [("end", 1)]
    assert transition(1, 2, study) == [("end", 1), ("start", 2)]
    assert transition(1, 3, study) == [("end", 1)]
    assert transition(3, 1, study) == [("start", 1)]
    assert transition(1, 1, study) == []  # ミュート切替など
    assert transition(None, 3, study) == []


def test_reconcile():
    opens = [OpenSession(1, 10, 100, 0), OpenSession(1, 11, 100, 0), OpenSession(1, 12, 100, 0)]
    present = {10: 100, 11: 200, 13: 100}
    to_end, to_start = reconcile(opens, present)
    assert sorted(to_end) == [11, 12]
    assert sorted(to_start) == [(11, 200), (13, 100)]


# ---- pomodoro ---------------------------------------------------------------
def test_pomodoro_cycle():
    cfg = PomodoroConfig(25, 5, 15, 2)
    s = PomodoroSession.start(1, 100, 10, cfg, now=0)
    assert s.phase == WORK and s.phase_end == 25 * 60
    assert not s.is_due(25 * 60 - 1) and s.is_due(25 * 60)
    assert s.advance(1500) == SHORT_BREAK and s.phase_end == 1500 + 300
    assert s.advance(1800) == WORK
    assert s.advance(3300) == LONG_BREAK and s.completed_work == 2
    assert s.advance(4200) == WORK


def test_pomodoro_pause_resume():
    s = PomodoroSession.start(1, 100, 10, PomodoroConfig(), now=0)
    s.pause(600)
    assert s.paused and s.remaining(5000) == 900 and not s.is_due(10**6)
    s.resume(5000)
    assert not s.paused and s.phase_end == 5900


def test_pomodoro_config_validation():
    with pytest.raises(ValueError):
        PomodoroConfig(work_min=0)
    with pytest.raises(ValueError):
        PomodoroConfig(long_break_every=0)


# ---- formatting -------------------------------------------------------------
def test_ranking_text_and_goal():
    assert ranking_text([]) == "まだ記録がありません。"
    text = ranking_text([(1, 3600), (2, 1800), (3, 600), (4, 60)])
    assert text.splitlines()[0] == "🥇 <@1> — **1時間**"
    assert text.splitlines()[3].startswith("` 4.` <@4>")
    assert progress_bar(30, 60) == "▰▰▰▰▰▱▱▱▱▱ 50%"
    assert "達成" in goal_text(7200, 120)
    assert "あと30分" in goal_text(5400, 120)


# ---- music ------------------------------------------------------------------
def test_track_from_search_result():
    info = {"_type": "playlist", "entries": [
        {"title": "lofi", "webpage_url": "https://youtu.be/x", "duration": 3600}]}
    t = track_from_info(info, requested_by=10)
    assert (t.title, t.page_url, t.duration, t.is_live) == (
        "lofi", "https://www.youtube.com/watch?v=x", 3600, False)
    with pytest.raises(MusicError):
        track_from_info({"_type": "playlist", "entries": []}, 10)
    with pytest.raises(MusicError):
        track_from_info({"live_status": "is_upcoming", "webpage_url": "u"}, 10)


def test_select_stream_prefers_audio_hls_for_live():
    info = {"is_live": True, "url": "fallback", "formats": [
        {"url": "v", "protocol": "m3u8_native", "acodec": "mp4a", "vcodec": "avc1", "height": 360},
        {"url": "a1", "protocol": "m3u8_native", "acodec": "mp4a", "vcodec": "none", "abr": 48},
        {"url": "a2", "protocol": "m3u8_native", "acodec": "mp4a", "vcodec": "none", "abr": 128},
    ]}
    s = select_stream(info)
    assert s.url == "a2" and s.is_live
    assert select_stream({"url": "plain"}).url == "plain"
    with pytest.raises(MusicError):
        select_stream({})


def test_guild_music_loop_modes():
    m = GuildMusic()
    a, b, c = (Track(x, "u" + x, 1, False, 1) for x in "abc")
    m.enqueue_many([a, b, c])
    assert m.next_track() is a
    m.loop_mode = "single"
    assert m.next_track() is a          # 1曲リピート
    assert m.skip() is b                # スキップは次の曲へ
    m.loop_mode = "all"
    assert m.next_track() is c and list(m.queue) == [b]  # 全曲ループは終わった曲を末尾へ
    assert m.next_track() is b and list(m.queue) == [c]
    m.loop_mode = "off"
    assert m.next_track() is c and m.next_track() is None
    gen = m.generation
    m.clear()
    assert m.generation == gen + 1


def test_enqueue_many_respects_cap(monkeypatch):
    import study_bot.music as mm
    monkeypatch.setattr(mm, "MAX_QUEUE", 3)
    m = GuildMusic()
    t = [Track(str(i), "u", 1, False, 1) for i in range(5)]
    assert m.enqueue_many(t) == 3
    with pytest.raises(MusicError):
        m.enqueue_many(t)


def test_normalize_youtube_url():
    from study_bot.music import normalize_youtube_url as n
    assert n("https://music.youtube.com/watch?v=abc&list=RD123&si=x") == "https://www.youtube.com/watch?v=abc"
    assert n("https://youtu.be/abc?si=x") == "https://www.youtube.com/watch?v=abc"
    assert n("https://www.youtube.com/shorts/abc") == "https://www.youtube.com/watch?v=abc"
    assert n("https://music.youtube.com/playlist?list=PL1") == "https://music.youtube.com/playlist?list=PL1"
    assert n("https://music.youtube.com/browse/MPREb_x") == "https://music.youtube.com/browse/MPREb_x"


def test_prepare_query(monkeypatch):
    from study_bot import music as mm
    assert mm.prepare_query("lofi study") == "https://music.youtube.com/search?q=lofi+study#songs"
    assert mm.prepare_query("lofi study", mm.YOUTUBE) == "ytsearch1:lofi study"
    assert mm.prepare_query("https://youtu.be/abc") == "https://www.youtube.com/watch?v=abc"
    assert mm.prepare_query("https://soundcloud.com/x/y") == "https://soundcloud.com/x/y"
    monkeypatch.setattr(mm, "spotify_search_text", lambda url: "Artist - Song")
    assert mm.prepare_query("https://open.spotify.com/track/1") ==         "https://music.youtube.com/search?q=Artist+-+Song#songs"
    with pytest.raises(MusicError):
        mm.prepare_query("  ")


def test_tracks_from_search_and_playlist():
    from study_bot.music import tracks_from_info
    entries = [{"id": f"v{i}", "url": f"https://music.youtube.com/watch?v=v{i}", "title": f"t{i}"}
               for i in range(3)]
    search = {"_type": "playlist", "extractor_key": "YoutubeMusicSearchURL", "entries": entries}
    tracks, name = tracks_from_info(search, 1)
    assert name is None and [t.page_url for t in tracks] == ["https://www.youtube.com/watch?v=v0"]
    album = {"_type": "playlist", "extractor_key": "YoutubeTab", "title": "Album - X",
             "entries": entries + [None, {"id": "up", "live_status": "is_upcoming"}]}
    tracks, name = tracks_from_info(album, 1)
    assert name == "Album - X" and [t.title for t in tracks] == ["t0", "t1", "t2"]
    single = {"title": "s", "webpage_url": "https://www.youtube.com/watch?v=s", "duration": 61.0}
    tracks, name = tracks_from_info(single, 1)
    assert tracks[0].duration == 61 and name is None


def test_error_message_geo():
    from study_bot.music import error_message
    assert "地域制限" in error_message(RuntimeError("The uploader has not made this video available in your country"))
