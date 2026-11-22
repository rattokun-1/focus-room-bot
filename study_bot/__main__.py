"""`python -m study_bot` で起動する。"""
from __future__ import annotations

import logging
import os
import sys

from .config import load_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # 例: LOG_DEBUG=discord.voice_state,discord.gateway,discord.player で音声まわりを詳しく出す
    for name in filter(None, (n.strip() for n in os.getenv("LOG_DEBUG", "").split(","))):
        logging.getLogger(name).setLevel(logging.DEBUG)
    try:
        settings = load_settings()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    from .bot import StudyBot

    bot = StudyBot(settings)
    bot.run(settings.token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
