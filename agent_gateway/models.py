from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    task_id: str
    agent: str
    prompt: str
    worktree: str
    status: str = "queued"
    command: list[str] | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    result_path: str | None = None
    log_path: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
