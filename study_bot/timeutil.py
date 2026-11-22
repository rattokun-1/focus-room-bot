"""日付境界・時刻表記などタイムゾーンを扱う純粋関数。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def local_dt(ts: float, tz: ZoneInfo) -> datetime:
    return datetime.fromtimestamp(ts, tz)


def day_bounds(ts: float, tz: ZoneInfo, days_ago: int = 0) -> tuple[float, float]:
    """tsを含むローカル日（days_ago日前）の [開始, 終了) をUNIX秒で返す。"""
    d = local_dt(ts, tz).date() - timedelta(days=days_ago)
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    end = start + timedelta(days=1)
    # DST のある地域でも壁時計の0時同士で区切る
    end = datetime(end.year, end.month, end.day, tzinfo=tz)
    return start.timestamp(), end.timestamp()


def week_bounds(ts: float, tz: ZoneInfo, weeks_ago: int = 0) -> tuple[float, float]:
    """tsを含む週（月曜始まり、weeks_ago週前）の [開始, 終了) を返す。"""
    d = local_dt(ts, tz).date()
    monday = d - timedelta(days=d.weekday(), weeks=weeks_ago)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=tz)
    nxt = monday + timedelta(days=7)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    return start.timestamp(), end.timestamp()


def date_key(ts: float, tz: ZoneInfo) -> str:
    return local_dt(ts, tz).date().isoformat()


def parse_hhmm(text: str) -> str:
    """'7:05' などを '07:05' に正規化する。不正なら ValueError。"""
    m = _HHMM.match(text.strip())
    if not m:
        raise ValueError("時刻は HH:MM 形式（例: 21:00）で指定してください。")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def is_due(now: float, tz: ZoneInfo, hhmm: str, last_date: str | None) -> bool:
    """今日の hhmm を過ぎていて、今日まだ実行していなければ True。"""
    local = local_dt(now, tz)
    today = local.date().isoformat()
    if last_date == today:
        return False
    return local.strftime("%H:%M") >= hhmm


def format_duration(seconds: float) -> str:
    minutes = int(max(0, seconds) // 60)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}時間{m}分"
    if h:
        return f"{h}時間"
    return f"{m}分"


def format_clock(seconds: float) -> str:
    seconds = int(max(0, seconds))
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"
