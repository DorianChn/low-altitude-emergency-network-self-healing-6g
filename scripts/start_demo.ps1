param(
  [ValidateRange(0, 3600)][int]$RunDurationSeconds = 0,
  [switch]$NoBrowser,
  [ValidateRange(1024, 65535)][int]$ApiPort = 0,
  [ValidateRange(1024, 65535)][int]$FrontendPort = 0
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$RuntimeRoot = Join-Path $ProjectRoot ".runtime"
$VenvPython = Join-Path $RuntimeRoot "venv\Scripts\python.exe"
$Node = Join-Path $RuntimeRoot "tools\node-v24.19.0-win-x64\node.exe"
$Vite = Join-Path $FrontendRoot "node_modules\vite\bin\vite.js"
$LogRoot = Join-Path $RuntimeRoot "logs"
$Owned = [Collections.Generic.List[System.Diagnostics.Process]]::new()
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Get-FreePort {
  $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
  $listener.Start(); $value = ([Net.IPEndPoint]$listener.LocalEndpoint).Port; $listener.Stop(); return $value
}
function Test-PortAvailable([int]$Port) {
  $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
  try { $listener.Start(); return $true } catch { return $false } finally { $listener.Stop() }
}
function Start-ProjectProcess([string]$File, [string[]]$Arguments, [string]$WorkingDirectory, [string]$Prefix) {
  $tag = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
  $stdout = Join-Path $LogRoot "$Prefix-$tag.out.log"; $stderr = Join-Path $LogRoot "$Prefix-$tag.err.log"
  $oldUtf8 = $env:PYTHONUTF8; $oldApiTarget = $env:LOWALT6G_API_TARGET
  $env:PYTHONUTF8 = "1"
  if ($Prefix -eq "frontend") { $env:LOWALT6G_API_TARGET = "http://127.0.0.1:$script:ApiPort" }
  try {
    $quotedArguments = ($Arguments | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }) -join ' '
    $process = Start-Process -FilePath $File -ArgumentList $quotedArguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  } finally {
    $env:PYTHONUTF8 = $oldUtf8
    $env:LOWALT6G_API_TARGET = $oldApiTarget
  }
  $Owned.Add($process)
  return $process
}
function Wait-Ready([string]$Uri, [Diagnostics.Process]$Process, [string]$Label) {
  for ($i = 0; $i -lt 80; $i++) {
    if ($Process.HasExited) { throw "$Label exited during startup with code $($Process.ExitCode). See .runtime\logs." }
    try { return Invoke-RestMethod -Uri $Uri -TimeoutSec 2 } catch { Start-Sleep -Milliseconds 350 }
  }
  throw "$Label did not become ready within 28 seconds at $Uri. See .runtime\logs."
}
function Stop-ProjectProcess([Diagnostics.Process]$Process) {
  if ($null -ne $Process -and -not $Process.HasExited) { & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null }
}

try {
  if (-not (Test-Path $VenvPython) -or -not (Test-Path $Node) -or -not (Test-Path $Vite)) {
    throw "Project runtime is not prepared. Double-click prepare_environment.cmd, then retry."
  }
  if (-not (Test-Path (Join-Path $ProjectRoot "results\phase6_demo_manifest.json"))) { throw "Frozen Phase 6 replay manifest is missing." }
  if ($ApiPort -eq 0) { $ApiPort = Get-FreePort }
  if ($FrontendPort -eq 0) { $FrontendPort = Get-FreePort }
  if ($ApiPort -eq $FrontendPort) { throw "API and frontend ports must be different." }
  if (-not (Test-PortAvailable $ApiPort)) { throw "Port $ApiPort is occupied. No service was stopped. Choose another port with -ApiPort." }
  if (-not (Test-PortAvailable $FrontendPort)) { throw "Port $FrontendPort is occupied. No service was stopped. Choose another port with -FrontendPort." }

  $api = Start-ProjectProcess $VenvPython @("-m", "uvicorn", "lowalt6g.phase6_api:app", "--host", "127.0.0.1", "--port", "$ApiPort") $ProjectRoot "api"
  $index = Wait-Ready "http://127.0.0.1:$ApiPort/api/demo/phase6" $api "API"
  if ($index.mode -ne "precomputed_offline_replay" -or $index.live_stream -ne $false -or @($index.scenarios.PSObject.Properties).Count -ne 4) { throw "API responded but its frozen Phase 6 replay contract did not match." }
  $null = Wait-Ready "http://127.0.0.1:$ApiPort/api/health" $api "API health"

  $frontend = Start-ProjectProcess $Node @($Vite, "--host", "127.0.0.1", "--port", "$FrontendPort", "--strictPort") $FrontendRoot "frontend"
  $null = Wait-Ready "http://127.0.0.1:$FrontendPort/" $frontend "Frontend"
  $url = "http://127.0.0.1:$FrontendPort/demo"
  Write-Host "6G / RESCUE local demonstration is ready." -ForegroundColor Green
  Write-Host "演示地址: $url"
  Write-Host "API: http://127.0.0.1:$ApiPort/api/health"
  Write-Host "日志: $LogRoot"
  if (-not $NoBrowser) { Start-Process $url | Out-Null }
  $clock = [Diagnostics.Stopwatch]::StartNew()
  while ($true) {
    foreach ($process in $Owned) { if ($process.HasExited) { throw "A service stopped unexpectedly (exit $($process.ExitCode)). See .runtime\logs." } }
    if ($RunDurationSeconds -gt 0 -and $clock.Elapsed.TotalSeconds -ge $RunDurationSeconds) { break }
    if ($RunDurationSeconds -eq 0 -and [Console]::KeyAvailable -and [Console]::ReadKey($true).Key -eq [ConsoleKey]::Q) { break }
    Start-Sleep -Milliseconds 250
  }
} catch {
  Write-Host "启动失败：$($_.Exception.Message)" -ForegroundColor Red
  exit 1
} finally {
  for ($i = $Owned.Count - 1; $i -ge 0; $i--) { Stop-ProjectProcess $Owned[$i] }
}
