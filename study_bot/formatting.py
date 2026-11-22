"""Discordに出す文字列の組み立て（純粋関数）。"""
from __future__ import annotations

from .timeutil import format_duration

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def ranking_text(rows: list[tuple[int, float]]) -> str:
    if not rows:
        return "まだ記録がありません。"
    lines = []
    for i, (uid, secs) in enumerate(rows, start=1):
        mark = MEDALS.get(i, f"`{i:>2}.`")
        lines.append(f"{mark} <@{uid}> — **{format_duration(secs)}**")
    return "\n".join(lines)


def progress_bar(done: float, total: float, width: int = 10) -> str:
    if total <= 0:
        return ""
    ratio = min(1.0, max(0.0, done / total))
    filled = round(ratio * width)
    return "▰" * filled + "▱" * (width - filled) + f" {int(ratio * 100)}%"


def goal_text(done_seconds: float, goal_minutes: int) -> str:
    goal_seconds = goal_minutes * 60
    remaining = goal_seconds - done_seconds
    bar = progress_bar(done_seconds, goal_seconds)
    if remaining <= 0:
        return f"{format_duration(done_seconds)} / {format_duration(goal_seconds)}  {bar}  達成！"
    return (f"{format_duration(done_seconds)} / {format_duration(goal_seconds)}  {bar}"
            f"（あと{format_duration(remaining + 59)}）")
