"""環境変数（.env）からの設定読み込み。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    token: str
    db_path: Path
    tz: ZoneInfo
    dev_guild_id: int | None
    ffmpeg_path: str
    default_volume: float


def load_settings(env_file: Path | None = None) -> Settings:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv未導入でも環境変数だけで動かせる
        pass
    else:
        load_dotenv(env_file or ROOT / ".env")

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN が設定されていません（.env を確認してください）。")

    db_path = Path(os.getenv("DATABASE_PATH", "data/study.db"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    dev_guild = os.getenv("DEV_GUILD_ID", "").strip()
    volume = int(os.getenv("MUSIC_DEFAULT_VOLUME", "15"))
    return Settings(
        token=token,
        db_path=db_path,
        tz=ZoneInfo(os.getenv("BOT_TIMEZONE", "Asia/Tokyo")),
        dev_guild_id=int(dev_guild) if dev_guild else None,
        ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
        default_volume=max(0, min(100, volume)) / 100,
    )
