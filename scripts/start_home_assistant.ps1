[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$OpenUi
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$configDirectory = Join-Path $repositoryRoot "dev\home-assistant"
$sourceIntegration = Join-Path $repositoryRoot "custom_components\thermal_storage_optimizer"
$customComponentsDirectory = Join-Path $configDirectory "custom_components"
$targetIntegration = Join-Path $customComponentsDirectory "thermal_storage_optimizer"
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$homeAssistantRunner = Join-Path $PSScriptRoot "run_home_assistant.py"
$env:UV_CACHE_DIR = Join-Path $configDirectory ".uv-cache"
$env:PYTHONUTF8 = "1"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Home Assistant is not installed. Create .venv and install the dev dependencies first."
}

New-Item -ItemType Directory -Force -Path $customComponentsDirectory | Out-Null

$resolvedConfigDirectory = [IO.Path]::GetFullPath($configDirectory)
$resolvedTargetIntegration = [IO.Path]::GetFullPath($targetIntegration)
if (-not $resolvedTargetIntegration.StartsWith(
        $resolvedConfigDirectory + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Refusing to replace an integration outside the test configuration."
}

if (Test-Path -LiteralPath $targetIntegration) {
    Remove-Item -LiteralPath $targetIntegration -Recurse -Force
}
Copy-Item -LiteralPath $sourceIntegration -Destination $targetIntegration -Recurse

if ($Check) {
    & $pythonExecutable $homeAssistantRunner --script check_config -c $configDirectory
    exit $LASTEXITCODE
}

$portInUse = $false
$tcpClient = [Net.Sockets.TcpClient]::new()
try {
    $connectTask = $tcpClient.ConnectAsync("127.0.0.1", 8123)
    if ($connectTask.Wait(500) -and $tcpClient.Connected) {
        $portInUse = $true
    }
}
catch {
    # A refused connection means the port is available for the test server.
}
finally {
    $tcpClient.Dispose()
}

if ($portInUse) {
    throw "Port 8123 is already in use. Stop the existing Home Assistant test instance before starting another one."
}

$arguments = @("-c", $configDirectory, "--log-rotate-days", "2")
if ($OpenUi) {
    $arguments += "--open-ui"
}

Write-Host "Starting Home Assistant at http://127.0.0.1:8123"
Write-Host "Press Ctrl+C to stop it. Source changes are copied on each start."
& $pythonExecutable $homeAssistantRunner @arguments
exit $LASTEXITCODE
