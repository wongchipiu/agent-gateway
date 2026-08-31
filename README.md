# Agent Gateway

一个运行在 Windows 笔记本上的轻量 HTTP MCP Gateway，用于让 Mac 上的 Codex 调度 Trae CLI 和 Antigravity CLI。

## 运行模型

```text
Mac Codex --Streamable HTTP/MCP--> Windows Agent Gateway
                                      ├─ traecli exec
                                      └─ agy -p
```

Gateway 只暴露固定的 Agent 工具，不暴露任意 Shell 执行接口：

- `gateway_info`
- `dispatch_agent`
- `get_agent_status`
- `get_agent_result`
- `cancel_agent`
- `list_agent_tasks`

## Windows 安装

1. 安装 Python 3.10+、Git、Trae CLI 和 Antigravity CLI。
2. 克隆本项目到 Windows。
3. 设置环境变量：

```powershell
$env:AGENT_GATEWAY_WORKSPACE_ROOT = "D:/agent-workspace"
$env:AGENT_GATEWAY_TOKEN = "替换为足够长的随机字符串"
$env:AGENT_GATEWAY_HOST = "0.0.0.0"
$env:AGENT_GATEWAY_PORT = "8787"
```

4. 先完成 Trae/Antigravity 的登录，并确认 `traecli`、`agy` 在 PATH 中。
5. 启动：

```powershell
.\start-gateway.ps1
```

Gateway 会为每个任务创建 `.gateway-state/<task-id>/`，保存任务状态、完整日志和结构化结果。

健康检查地址：

```text
http://<Windows-IP>:8787/healthz
```

## Mac Codex 配置

在 Codex 桌面 App 的 Settings → MCP servers → Add server 中选择 Streamable HTTP，填写：

```text
http://<Windows-IP>:8787/mcp
```

Mac 上启动 Codex 前，需要让 Codex 进程能读取同一个 Token：

```bash
export AGENT_GATEWAY_TOKEN="与 Windows 相同的 Token"
```

也可以在 `~/.codex/config.toml` 中配置 Bearer Token：

```toml
[mcp_servers.agent_gateway]
url = "http://<Windows-IP>:8787/mcp"
bearer_token_env_var = "AGENT_GATEWAY_TOKEN"
tool_timeout_sec = 1800
default_tools_approval_mode = "prompt"
```

## 工作目录约束

`dispatch_agent` 的 `worktree` 必须是相对于 `AGENT_GATEWAY_WORKSPACE_ROOT` 的目录，例如：

```text
frontend-register
```

如果根目录是 `D:/agent-workspace`，实际工作目录就是：

```text
D:/agent-workspace/frontend-register
```

Gateway 会拒绝绝对路径、目录穿越路径和根目录之外的目录。

## 推荐的首次调用

先让 Codex 调用：

```text
gateway_info()
```

然后：

```text
dispatch_agent(
  agent="trae",
  worktree="frontend-register",
  prompt="阅读 docs/tasks/frontend.md，实现任务，完成后运行测试并总结修改文件。"
)
```

之后轮询：

```text
get_agent_status(task_id="...")
get_agent_result(task_id="...", include_log=true)
```

## 安全建议

- 只在 Windows 防火墙允许的局域网网卡上开放 8787。
- 必须设置 `AGENT_GATEWAY_TOKEN`。
- 不要把 8787 端口映射到公网。
- 每个 Agent 使用独立 worktree。
- 第一版默认只允许工作目录内的 Agent CLI 操作，不提供 `run_shell` 工具。
