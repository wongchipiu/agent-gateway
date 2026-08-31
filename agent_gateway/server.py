from __future__ import annotations

import asyncio
import hmac
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .runner import GatewayError, TaskManager


settings = Settings.from_env()
manager = TaskManager(settings)
mcp = FastMCP(
    "Agent Gateway",
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def gateway_info() -> dict[str, Any]:
    """Return available agents and the configured workspace boundary."""
    return {
        "name": "Agent Gateway",
        "version": "0.1.0",
        "agents": sorted(TaskManager.AGENTS),
        "workspace_root": str(settings.workspace_root),
        "transport": "streamable-http",
    }


@mcp.tool()
async def dispatch_agent(
    agent: str,
    prompt: str,
    worktree: str,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Queue a Trae or Antigravity task in an approved relative worktree.

    The agent name is allowlisted and the worktree must be below
    AGENT_GATEWAY_WORKSPACE_ROOT. This tool never accepts an arbitrary shell
    command.
    """
    try:
        return manager.dispatch(agent, prompt, worktree, timeout_sec)
    except GatewayError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def get_agent_status(task_id: str) -> dict[str, Any]:
    """Return the current status and metadata for a dispatched task."""
    try:
        return manager.status(task_id)
    except GatewayError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def get_agent_result(task_id: str, include_log: bool = False) -> dict[str, Any]:
    """Return the structured result and optionally the tail of the combined log."""
    try:
        return manager.result(task_id, include_log)
    except GatewayError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
async def cancel_agent(task_id: str) -> dict[str, Any]:
    """Cancel a running delegated task."""
    try:
        return await manager.cancel(task_id)
    except GatewayError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def list_agent_tasks(limit: int = 20) -> list[dict[str, Any]]:
    """List recently known tasks."""
    return manager.list_tasks(limit)


def _check_token(scope: dict[str, Any], token: str | None) -> bool:
    if not token:
        return True
    headers = dict(scope.get("headers", []))
    raw = headers.get(b"authorization", b"").decode("utf-8")
    scheme, _, supplied = raw.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(supplied, token)


class AuthMiddleware:
    """Small ASGI bearer-token guard around the MCP application."""

    def __init__(self, app: Any, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path") == "/healthz":
            body = b'{"status":"ok","service":"agent-gateway"}'
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            })
            await send({"type": "http.response.body", "body": body})
            return
        if scope.get("type") != "http" or _check_token(scope, self.token):
            await self.app(scope, receive, send)
            return
        body = b'{"error":"unauthorized"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


def build_app() -> Any:
    settings.validate()
    app = mcp.streamable_http_app()
    return AuthMiddleware(app, settings.gateway_token)


def main() -> None:
    import uvicorn

    app = build_app()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
