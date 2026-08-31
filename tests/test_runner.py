from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agent_gateway.config import Settings
from agent_gateway.runner import GatewayError, TaskManager


class TaskManagerTests(unittest.IsolatedAsyncioTestCase):
    def make_manager(self, tmp: str) -> tuple[TaskManager, Path]:
        root = Path(tmp) / "workspace"
        worktree = root / "demo"
        worktree.mkdir(parents=True)
        settings = Settings(
            host="127.0.0.1",
            port=8787,
            workspace_root=root,
            state_dir=Path(tmp) / "state",
            gateway_token=None,
            task_timeout_sec=30,
            # /bin/echo is used as a portable smoke-test stand-in for a CLI.
            trae_command="/bin/echo",
            antigravity_command="/bin/echo",
        )
        return TaskManager(settings), worktree

    async def test_dispatch_and_persist_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager, _ = self.make_manager(tmp)
            queued = manager.dispatch("trae", "hello", "demo")
            await asyncio.sleep(0.2)
            record = manager.status(queued["task_id"])
            self.assertEqual(record["status"], "succeeded")
            self.assertEqual(record["returncode"], 0)
            result = manager.result(queued["task_id"])
            self.assertTrue(result["result"]["response"])

    async def test_rejects_path_escape_and_unknown_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager, _ = self.make_manager(tmp)
            with self.assertRaises(GatewayError):
                manager.dispatch("trae", "hello", "../outside")
            with self.assertRaises(GatewayError):
                manager.dispatch("unknown", "hello", "demo")


if __name__ == "__main__":
    unittest.main()
