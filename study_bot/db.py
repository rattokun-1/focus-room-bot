"""SQLite による勉強記録・設定の保存。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL,
    last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_guild_time ON sessions (guild_id, start);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions (end) WHERE end IS NULL;

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER PRIMARY KEY,
    notify_channel_id INTEGER,
    ranking_channel_id INTEGER,
    ranking_time TEXT,
    last_ranking_date TEXT
);

CREATE TABLE IF NOT EXISTS study_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS goals (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    daily_minutes INTEGER NOT NULL,
    last_achieved_date TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS auto_delete (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    hours INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    time TEXT NOT NULL,
    last_sent_date TEXT,
    PRIMARY KEY (guild_id, user_id)
);
"""

# 区間 [lo, hi) と各セッションの重なり秒数。進行中のセッションは :now で打ち切る。
_OVERLAP = "MAX(0, MIN(COALESCE(end, :now), :hi) - MAX(start, :lo))"
_IN_RANGE = "start < :hi AND COALESCE(end, :now) > :lo"


# 後から追加した guild_config の列（既存DBには起動時に ALTER TABLE で足す）
GUILD_CONFIG_EXTRA_COLUMNS = {
    "pomo_work": "INTEGER",
    "pomo_short": "INTEGER",
    "pomo_long": "INTEGER",
    "pomo_every": "INTEGER",
    "music_volume": "INTEGER",  # %
    "music_source": "TEXT",     # ytmusic / youtube
    "auto_channel_id": "INTEGER",  # 入ると自動開始するVC
    "auto_pomodoro": "INTEGER",    # NULL/1 = 有効, 0 = 無効
    "auto_music": "INTEGER",       # NULL/1 = 有効, 0 = 無効
    "auto_music_query": "TEXT",    # 空なら勉強向けおすすめ
}


@dataclass
class GuildConfig:
    guild_id: int
    notify_channel_id: int | None = None
    ranking_channel_id: int | None = None
    ranking_time: str | None = None
    last_ranking_date: str | None = None
    pomo_work: int | None = None
    pomo_short: int | None = None
    pomo_long: int | None = None
    pomo_every: int | None = None
    music_volume: int | None = None
    music_source: str | None = None
    auto_channel_id: int | None = None
    auto_pomodoro: int | None = None
    auto_music: int | None = None
    auto_music_query: str | None = None


@dataclass
class OpenSession:
    guild_id: int
    user_id: int
    channel_id: int
    start: float


class Database:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(guild_config)")}
        for name, sql_type in GUILD_CONFIG_EXTRA_COLUMNS.items():
            if name not in cols:
                self.conn.execute(f"ALTER TABLE guild_config ADD COLUMN {name} {sql_type}")

    def close(self) -> None:
        self.conn.close()

    # ---- セッション ----------------------------------------------------
    def start_session(self, guild_id: int, user_id: int, channel_id: int, now: float) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET end = :now, last_seen = :now "
                "WHERE guild_id = :g AND user_id = :u AND end IS NULL",
                {"now": now, "g": guild_id, "u": user_id})
            self.conn.execute(
                "INSERT INTO sessions (guild_id, user_id, channel_id, start, last_seen) "
                "VALUES (?, ?, ?, ?, ?)", (guild_id, user_id, channel_id, now, now))

    def end_session(self, guild_id: int, user_id: int, now: float) -> float | None:
        """進行中セッションを閉じ、その長さ（秒）を返す。無ければ None。"""
        row = self.conn.execute(
            "SELECT id, start FROM sessions WHERE guild_id = ? AND user_id = ? AND end IS NULL",
            (guild_id, user_id)).fetchone()
        if row is None:
            return None
        with self.conn:
            self.conn.execute("UPDATE sessions SET end = ?, last_seen = ? WHERE id = ?",
                              (now, now, row["id"]))
        return max(0.0, now - row["start"])

    def heartbeat(self, now: float) -> None:
        with self.conn:
            self.conn.execute("UPDATE sessions SET last_seen = ? WHERE end IS NULL", (now,))

    def close_stale_sessions(self) -> int:
        """Bot停止中に開いたままだったセッションを最後の生存確認時刻で閉じる。"""
        with self.conn:
            cur = self.conn.execute("UPDATE sessions SET end = last_seen WHERE end IS NULL")
        return cur.rowcount

    def open_sessions(self, guild_id: int | None = None) -> list[OpenSession]:
        sql = "SELECT guild_id, user_id, channel_id, start FROM sessions WHERE end IS NULL"
        args: tuple = ()
        if guild_id is not None:
            sql += " AND guild_id = ?"
            args = (guild_id,)
        return [OpenSession(r["guild_id"], r["user_id"], r["channel_id"], r["start"])
                for r in self.conn.execute(sql, args)]

    def user_seconds(self, guild_id: int, user_id: int, lo: float, hi: float, now: float) -> float:
        row = self.conn.execute(
            f"SELECT COALESCE(SUM({_OVERLAP}), 0) AS s FROM sessions "
            f"WHERE guild_id = :g AND user_id = :u AND {_IN_RANGE}",
            {"g": guild_id, "u": user_id, "lo": lo, "hi": hi, "now": now}).fetchone()
        return float(row["s"])

    def ranking(self, guild_id: int, lo: float, hi: float, now: float,
                limit: int = 10) -> list[tuple[int, float]]:
        rows = self.conn.execute(
            f"SELECT user_id, SUM({_OVERLAP}) AS s FROM sessions "
            f"WHERE guild_id = :g AND {_IN_RANGE} GROUP BY user_id "
            "HAVING s > 0 ORDER BY s DESC, user_id LIMIT :limit",
            {"g": guild_id, "lo": lo, "hi": hi, "now": now, "limit": limit}).fetchall()
        return [(r["user_id"], float(r["s"])) for r in rows]

    def user_rank(self, guild_id: int, user_id: int, lo: float, hi: float,
                  now: float) -> int | None:
        full = self.ranking(guild_id, lo, hi, now, limit=-1)
        for i, (uid, _) in enumerate(full, start=1):
            if uid == user_id:
                return i
        return None

    # ---- 設定 ----------------------------------------------------------
    def get_config(self, guild_id: int) -> GuildConfig:
        row = self.conn.execute("SELECT * FROM guild_config WHERE guild_id = ?",
                                (guild_id,)).fetchone()
        if row is None:
            return GuildConfig(guild_id)
        return GuildConfig(**dict(row))

    def all_configs(self) -> list[GuildConfig]:
        return [GuildConfig(**dict(r)) for r in self.conn.execute("SELECT * FROM guild_config")]

    def update_config(self, guild_id: int, **fields) -> None:
        allowed = {"notify_channel_id", "ranking_channel_id", "ranking_time", "last_ranking_date",
                   *GUILD_CONFIG_EXTRA_COLUMNS}
        if not fields or set(fields) - allowed:
            raise ValueError(f"unknown config fields: {set(fields) - allowed}")
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{c} = excluded.{c}" for c in fields)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO guild_config (guild_id, {cols}) VALUES (?, {marks}) "
                f"ON CONFLICT(guild_id) DO UPDATE SET {updates}",
                (guild_id, *fields.values()))

    def study_channels(self, guild_id: int) -> set[int]:
        return {r[0] for r in self.conn.execute(
            "SELECT channel_id FROM study_channels WHERE guild_id = ?", (guild_id,))}

    def set_study_channels(self, guild_id: int, channel_ids: set[int]) -> None:
        """勉強VCの指定をまとめて置き換える（空なら全VCが対象）。"""
        with self.conn:
            self.conn.execute("DELETE FROM study_channels WHERE guild_id = ?", (guild_id,))
            self.conn.executemany("INSERT INTO study_channels VALUES (?, ?)",
                                  [(guild_id, cid) for cid in channel_ids])

    def add_study_channel(self, guild_id: int, channel_id: int) -> None:
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO study_channels VALUES (?, ?)",
                              (guild_id, channel_id))

    def remove_study_channel(self, guild_id: int, channel_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM study_channels WHERE guild_id = ? AND channel_id = ?",
                (guild_id, channel_id))
        return cur.rowcount > 0

    # ---- 目標 ----------------------------------------------------------
    def set_goal(self, guild_id: int, user_id: int, minutes: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO goals (guild_id, user_id, daily_minutes) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET daily_minutes = excluded.daily_minutes, "
                "last_achieved_date = NULL",
                (guild_id, user_id, minutes))

    def get_goal(self, guild_id: int, user_id: int) -> tuple[int, str | None] | None:
        row = self.conn.execute(
            "SELECT daily_minutes, last_achieved_date FROM goals WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)).fetchone()
        return (row[0], row[1]) if row else None

    def clear_goal(self, guild_id: int, user_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM goals WHERE guild_id = ? AND user_id = ?",
                                    (guild_id, user_id))
        return cur.rowcount > 0

    def mark_goal_achieved(self, guild_id: int, user_id: int, date: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE goals SET last_achieved_date = ? WHERE guild_id = ? AND user_id = ?",
                (date, guild_id, user_id))

    # ---- リマインド -----------------------------------------------------
    def set_reminder(self, guild_id: int, user_id: int, hhmm: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO reminders (guild_id, user_id, time) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET time = excluded.time, "
                "last_sent_date = NULL", (guild_id, user_id, hhmm))

    def get_reminder(self, guild_id: int, user_id: int) -> str | None:
        row = self.conn.execute("SELECT time FROM reminders WHERE guild_id = ? AND user_id = ?",
                                (guild_id, user_id)).fetchone()
        return row[0] if row else None

    def clear_reminder(self, guild_id: int, user_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM reminders WHERE guild_id = ? AND user_id = ?",
                                    (guild_id, user_id))
        return cur.rowcount > 0

    def all_reminders(self) -> list[tuple[int, int, str, str | None]]:
        return [tuple(r) for r in self.conn.execute(
            "SELECT guild_id, user_id, time, last_sent_date FROM reminders")]

    def mark_reminder_sent(self, guild_id: int, user_id: int, date: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE reminders SET last_sent_date = ? WHERE guild_id = ? AND user_id = ?",
                (date, guild_id, user_id))

    # ---- チャットの自動削除 ---------------------------------------------
    def set_auto_delete(self, guild_id: int, channel_id: int, hours: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO auto_delete (guild_id, channel_id, hours) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, channel_id) DO UPDATE SET hours = excluded.hours",
                (guild_id, channel_id, hours))

    def remove_auto_delete(self, guild_id: int, channel_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM auto_delete WHERE guild_id = ? AND channel_id = ?",
                (guild_id, channel_id))
        return cur.rowcount > 0

    def set_auto_delete_channels(self, guild_id: int, channel_ids: set[int], hours: int) -> None:
        """自動削除の対象チャンネルをまとめて置き換える。"""
        with self.conn:
            self.conn.execute("DELETE FROM auto_delete WHERE guild_id = ?", (guild_id,))
            self.conn.executemany("INSERT INTO auto_delete VALUES (?, ?, ?)",
                                  [(guild_id, cid, hours) for cid in channel_ids])

    def auto_delete_rules(self, guild_id: int | None = None) -> list[tuple[int, int, int]]:
        sql = "SELECT guild_id, channel_id, hours FROM auto_delete"
        args: tuple = ()
        if guild_id is not None:
            sql += " WHERE guild_id = ?"
            args = (guild_id,)
        return [tuple(r) for r in self.conn.execute(sql + " ORDER BY channel_id", args)]
