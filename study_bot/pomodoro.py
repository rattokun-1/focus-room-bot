"""VCごとのポモドーロ状態機械（Discordに依存しない）。"""
from __future__ import annotations

from dataclasses import dataclass, field

WORK = "work"
SHORT_BREAK = "short_break"
LONG_BREAK = "long_break"

PHASE_LABELS = {WORK: "作業", SHORT_BREAK: "休憩", LONG_BREAK: "長い休憩"}


@dataclass(frozen=True)
class PomodoroConfig:
    work_min: int = 25
    short_break_min: int = 5
    long_break_min: int = 15
    long_break_every: int = 4  # 何回の作業ごとに長い休憩にするか

    def __post_init__(self) -> None:
        for name in ("work_min", "short_break_min", "long_break_min"):
            value = getattr(self, name)
            if not 1 <= value <= 180:
                raise ValueError("時間は1〜180分で指定してください。")
        if not 1 <= self.long_break_every <= 12:
            raise ValueError("長い休憩の間隔は1〜12回で指定してください。")

    def minutes(self, phase: str) -> int:
        return {WORK: self.work_min, SHORT_BREAK: self.short_break_min,
                LONG_BREAK: self.long_break_min}[phase]


@dataclass
class PomodoroSession:
    guild_id: int
    channel_id: int
    started_by: int
    config: PomodoroConfig
    phase: str = WORK
    phase_end: float = 0.0
    completed_work: int = 0
    paused_remaining: float | None = field(default=None)

    @classmethod
    def start(cls, guild_id: int, channel_id: int, started_by: int,
              config: PomodoroConfig, now: float) -> "PomodoroSession":
        return cls(guild_id, channel_id, started_by, config, WORK,
                   now + config.work_min * 60)

    @property
    def paused(self) -> bool:
        return self.paused_remaining is not None

    def remaining(self, now: float) -> float:
        if self.paused_remaining is not None:
            return self.paused_remaining
        return max(0.0, self.phase_end - now)

    def is_due(self, now: float) -> bool:
        return not self.paused and now >= self.phase_end

    def advance(self, now: float) -> str:
        """現在のフェーズを終了して次へ進め、新しいフェーズ名を返す。"""
        if self.phase == WORK:
            self.completed_work += 1
            if self.completed_work % self.config.long_break_every == 0:
                self.phase = LONG_BREAK
            else:
                self.phase = SHORT_BREAK
        else:
            self.phase = WORK
        self.phase_end = now + self.config.minutes(self.phase) * 60
        return self.phase

    def pause(self, now: float) -> None:
        if not self.paused:
            self.paused_remaining = self.remaining(now)

    def resume(self, now: float) -> None:
        if self.paused_remaining is not None:
            self.phase_end = now + self.paused_remaining
            self.paused_remaining = None
