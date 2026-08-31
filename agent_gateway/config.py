from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    workspace_root: Path
    state_dir: Path
    gateway_token: str | None
    task_timeout_sec: int
    trae_command: str
    antigravity_command: str

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.getenv("AGENT_GATEWAY_WORKSPACE_ROOT", Path.cwd()))
        state = Path(os.getenv("AGENT_GATEWAY_STATE_DIR", Path.cwd() / ".gateway-state"))
        return cls(
            host=os.getenv("AGENT_GATEWAY_HOST", "127.0.0.1"),
            port=_int_env("AGENT_GATEWAY_PORT", 8787),
            workspace_root=root.expanduser().resolve(),
            state_dir=state.expanduser().resolve(),
            gateway_token=os.getenv("AGENT_GATEWAY_TOKEN") or None,
            task_timeout_sec=_int_env("AGENT_GATEWAY_TASK_TIMEOUT_SEC", 1800),
            trae_command=os.getenv("TRAE_COMMAND", "traecli"),
            antigravity_command=os.getenv("ANTIGRAVITY_COMMAND", "agy"),
        )

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("AGENT_GATEWAY_PORT must be between 1 and 65535")
        if self.task_timeout_sec < 10:
            raise ValueError("AGENT_GATEWAY_TASK_TIMEOUT_SEC must be at least 10 seconds")
        if self.host not in {"127.0.0.1", "localhost", "::1"} and not self.gateway_token:
            raise ValueError(
                "AGENT_GATEWAY_TOKEN is required when AGENT_GATEWAY_HOST is not loopback"
            )
