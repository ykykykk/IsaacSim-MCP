# MIT License
# Copyright (c) 2026 whats2000

[CmdletBinding()]
param(
    [string]$IsaacSimRoot,
    [int]$Port,
    [string]$PhysicsGpu,
    [ValidateRange(0, 100)]
    [int]$MaxRestarts = 3,
    [ValidateRange(1, 86400)]
    [int]$RestartWindowSeconds = 300,
    [ValidateRange(1, 300)]
    [int]$BackoffSeconds = 2,
    [string]$StateFile = $env:ISAAC_MCP_RUNTIME_STATE_FILE,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$IsaacArgs
)

$ErrorActionPreference = "Stop"
$McpLauncherParameters = $PSBoundParameters
. (Join-Path $PSScriptRoot "Resolve-McpConfig.ps1")
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Repository Python was not found: $python. Run 'uv sync --dev' first."
}

if ([string]::IsNullOrWhiteSpace($StateFile)) {
    $stateRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [System.IO.Path]::GetTempPath() }
    $StateFile = Join-Path $stateRoot "IsaacSim-MCP\6.2\runtime-$Port.json"
}
$StateFile = [System.IO.Path]::GetFullPath($StateFile)
$env:ISAAC_MCP_RUNTIME_STATE_FILE = $StateFile
$env:ISAAC_MCP_PORT = $Port.ToString()

$arguments = [System.Collections.Generic.List[string]]::new()
foreach ($value in @(
        "-m", "isaac_mcp.runtime_supervisor",
        "--repository-root", $repoRoot,
        "--isaac-sim-root", $IsaacSimRoot,
        "--state-file", $StateFile,
        "--port", $Port.ToString(),
        "--max-restarts", $MaxRestarts.ToString(),
        "--restart-window-seconds", $RestartWindowSeconds.ToString(),
        "--backoff-seconds", $BackoffSeconds.ToString()
    )) {
    $arguments.Add($value)
}
if ($PSBoundParameters.ContainsKey("PhysicsGpu")) {
    $arguments.Add("--physics-gpu")
    $arguments.Add($PhysicsGpu)
}
if ($IsaacArgs.Count -gt 0) {
    $arguments.Add("--")
    foreach ($value in $IsaacArgs) {
        $arguments.Add($value)
    }
}

Write-Host "Starting supervised Isaac Sim runtime"
Write-Host "Runtime state: $StateFile"
Write-Host "Restart policy: max $MaxRestarts abnormal exits in $RestartWindowSeconds seconds"

Push-Location $repoRoot
try {
    & $python @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
