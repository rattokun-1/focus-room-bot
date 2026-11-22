"""VC入退室から勉強セッションの開始・終了を決める純粋ロジック。"""
from __future__ import annotations

from collections.abc import Callable, Iterable

from .db import OpenSession


def is_study_channel(channel_id: int | None, configured: set[int],
                     afk_channel_id: int | None) -> bool:
    """勉強VCかどうか。設定が空ならAFK以外の全VCを対象にする。"""
    if channel_id is None:
        return False
    if configured:
        return channel_id in configured
    return channel_id != afk_channel_id


def transition(before: int | None, after: int | None,
               is_study: Callable[[int | None], bool]) -> list[tuple[str, int]]:
    """voice_state_update の前後チャンネルから必要な操作を返す。

    戻り値は ("end", 旧ch) / ("start", 新ch) の列。同じチャンネル内の
    ミュート切替などは操作なし。
    """
    if before == after:
        return []
    actions: list[tuple[str, int]] = []
    if before is not None and is_study(before):
        actions.append(("end", before))
    if after is not None and is_study(after):
        actions.append(("start", after))
    return actions


def reconcile(open_sessions: Iterable[OpenSession],
              present: dict[int, int]) -> tuple[list[int], list[tuple[int, int]]]:
    """DB上の進行中セッションと実際のVC在室者（user_id -> channel_id）を突き合わせる。

    戻り値: (終了させる user_id 一覧, 開始させる (user_id, channel_id) 一覧)
    """
    to_end: list[int] = []
    to_start: list[tuple[int, int]] = []
    open_by_user = {s.user_id: s for s in open_sessions}
    for uid, s in open_by_user.items():
        if present.get(uid) != s.channel_id:
            to_end.append(uid)
    for uid, cid in present.items():
        s = open_by_user.get(uid)
        if s is None or s.channel_id != cid:
            to_start.append((uid, cid))
    return to_end, to_start
