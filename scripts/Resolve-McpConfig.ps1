$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Install the repository environment before using its launchers.'
}
$configArgs = @('-m', 'isaac_mcp.config')
if ($McpLauncherParameters.ContainsKey('Port')) { $configArgs += @('--port', "$Port") }
if ($McpLauncherParameters.ContainsKey('IsaacSimRoot')) { $configArgs += @('--isaac-root', $IsaacSimRoot) }
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $configJson = & $python @configArgs
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve MCP configuration.' }
    $effectiveConfig = $configJson | ConvertFrom-Json
}
finally { Pop-Location }
$Port = [int]$effectiveConfig.port
$IsaacSimRoot = $effectiveConfig.isaac_root
$env:ISAAC_MCP_PORT = "$Port"
$env:ISAAC_MCP_HOST = $effectiveConfig.host
$env:ISAAC_MCP_TOOL_PROFILE = $effectiveConfig.tool_profile
$env:ISAAC_MCP_TOOL_DOMAINS = $effectiveConfig.tool_domains
if ($IsaacSimRoot) { $env:ISAACSIM_ROOT = $IsaacSimRoot }
