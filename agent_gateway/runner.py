from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .config import Settings
from .models import TaskRecord, utc_now


class GatewayError(RuntimeError):
    """An expected, user-actionable Gateway error."""


class TaskManager:
    AGENTS = {"trae", "antigravity"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._background: set[asyncio.Task[None]] = set()
        self._cancel_requested: set[str] = set()
        self._load_records()

    def _load_records(self) -> None:
        for path in self.settings.state_dir.glob("*/task.json"):
            try:
                record = TaskRecord(**json.loads(path.read_text(encoding="utf-8")))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            self._tasks[record.task_id] = record

    def _task_dir(self, task_id: str) -> Path:
        path = self.settings.state_dir / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _record_path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "task.json"

    def _write_record(self, record: TaskRecord) -> None:
        self._record_path(record.task_id).write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _resolve_worktree(self, value: str) -> Path:
        candidate = Path(value)
        if candidate.is_absolute():
            raise GatewayError("worktree must be a relative path under the configured workspace root")
        root = self.settings.workspace_root.resolve()
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise GatewayError("worktree escapes the configured workspace root") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise GatewayError(f"worktree does not exist: {value}")
        return resolved

    def _command_for(self, agent: str) -> str:
        if agent == "trae":
            return self.settings.trae_command
        if agent == "antigravity":
            return self.settings.antigravity_command
        raise GatewayError(f"unsupported agent: {agent}; expected one of {sorted(self.AGENTS)}")

    def _build_command(self, agent: str, prompt: str, worktree: Path, timeout_sec: int) -> list[str]:
        if agent == "trae":
            # Trae emits JSONL events in exec mode. The Gateway preserves the
            # complete stream and extracts the last JSON event as a convenience.
            return [self._command_for(agent), "--cd", str(worktree), "exec", "--json", prompt]
        # Antigravity emits one JSON result in headless mode.
        return [
            self._command_for(agent),
            "-p",
            prompt,
            "--cwd",
            str(worktree),
            "--output-format",
            "json",
            "--print-timeout",
            f"{timeout_sec}s",
        ]

    def dispatch(self, agent: str, prompt: str, worktree: str, timeout_sec: int | None = None) -> dict[str, Any]:
        if not prompt.strip():
            raise GatewayError("prompt must not be empty")
        if len(prompt) > 100_000:
            raise GatewayError("prompt is too large; limit is 100000 characters")
        resolved = self._resolve_worktree(worktree)
        timeout = timeout_sec or self.settings.task_timeout_sec
        if timeout < 10 or timeout > 86_400:
            raise GatewayError("timeout_sec must be between 10 and 86400")

        task_id = str(uuid.uuid4())
        record = TaskRecord(
            task_id=task_id,
            agent=agent,
            prompt=prompt,
            worktree=worktree,
            command=self._build_command(agent, prompt, resolved, timeout),
            log_path=str(self._task_dir(task_id) / "combined.log"),
            result_path=str(self._task_dir(task_id) / "result.json"),
        )
        self._tasks[task_id] = record
        self._write_record(record)
        job = asyncio.create_task(self._run(record, resolved, timeout))
        self._background.add(job)
        job.add_done_callback(self._background.discard)
        return {
            "task_id": task_id,
            "status": record.status,
            "agent": agent,
            "worktree": worktree,
            "message": "Task queued; poll get_agent_status or get_agent_result.",
        }

    async def _run(self, record: TaskRecord, worktree: Path, timeout_sec: int) -> None:
        record.status = "running"
        record.started_at = utc_now()
        self._write_record(record)
        stdout = b""
        stderr = b""
        process: asyncio.subprocess.Process | None = None
        try:
            kwargs: dict[str, Any] = {
                "cwd": str(worktree),
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
            }
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            process = await asyncio.create_subprocess_exec(*record.command, **kwargs)
            self._processes[record.task_id] = process
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
            record.returncode = process.returncode
            if record.task_id in self._cancel_requested:
                record.status = "cancelled"
                record.error = "cancelled by caller"
            else:
                record.status = "succeeded" if process.returncode == 0 else "failed"
        except asyncio.TimeoutError:
            record.status = "timed_out"
            record.error = f"task exceeded timeout of {timeout_sec} seconds"
            if process is not None:
                await self._terminate(process)
        except FileNotFoundError as exc:
            record.status = "failed"
            record.error = f"agent executable not found: {exc.filename}"
        except Exception as exc:  # pragma: no cover - defensive process boundary
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._processes.pop(record.task_id, None)
            self._cancel_requested.discard(record.task_id)
            combined = b"--- STDOUT ---\n" + stdout + b"\n--- STDERR ---\n" + stderr
            self._task_dir(record.task_id).joinpath("combined.log").write_bytes(combined)
            result = self._extract_result(stdout)
            self._task_dir(record.task_id).joinpath("result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            record.finished_at = utc_now()
            self._write_record(record)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            process.kill()
        else:
            process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    @staticmethod
    def _extract_result(stdout: bytes) -> Any:
        text = stdout.decode("utf-8", errors="replace").strip()
        if not text:
            return {"response": ""}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        for line in reversed(text.splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return {"response": text[-20_000:]}

    def _get(self, task_id: str) -> TaskRecord:
        record = self._tasks.get(task_id)
        if record:
            return record
        path = self._record_path(task_id)
        if not path.exists():
            raise GatewayError(f"unknown task_id: {task_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        record = TaskRecord(**data)
        self._tasks[task_id] = record
        return record

    def status(self, task_id: str) -> dict[str, Any]:
        return self._get(task_id).to_dict()

    def result(self, task_id: str, include_log: bool = False) -> dict[str, Any]:
        record = self._get(task_id)
        result_path = Path(record.result_path) if record.result_path else None
        result: Any = None
        if result_path and result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        payload: dict[str, Any] = {"task": record.to_dict(), "result": result}
        if include_log and record.log_path:
            log_path = Path(record.log_path)
            if log_path.exists():
                payload["log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-20_000:]
        return payload

    async def cancel(self, task_id: str) -> dict[str, Any]:
        record = self._get(task_id)
        process = self._processes.get(task_id)
        if process is None:
            return {"task_id": task_id, "status": record.status, "message": "Task is not running."}
        self._cancel_requested.add(task_id)
        await self._terminate(process)
        record.status = "cancelled"
        record.finished_at = utc_now()
        record.error = "cancelled by caller"
        self._write_record(record)
        return {"task_id": task_id, "status": record.status}

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        records = list(self._tasks.values())
        return [record.to_dict() for record in records[-max(1, min(limit, 100)) :]]
