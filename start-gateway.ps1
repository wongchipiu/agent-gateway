$ErrorActionPreference = "Stop"

$gatewayRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $gatewayRoot

$pythonExe = Join-Path (Join-Path $gatewayRoot ".venv") (Join-Path "Scripts" "python.exe")

if (-not (Test-Path $pythonExe)) {
    py -3 -m venv .venv
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install -e .
}

if (-not $env:AGENT_GATEWAY_WORKSPACE_ROOT) {
    throw "Set AGENT_GATEWAY_WORKSPACE_ROOT before starting the Gateway."
}

if (-not $env:AGENT_GATEWAY_TOKEN) {
    throw "Set AGENT_GATEWAY_TOKEN before starting a network-accessible Gateway."
}

& $pythonExe -m agent_gateway.server
