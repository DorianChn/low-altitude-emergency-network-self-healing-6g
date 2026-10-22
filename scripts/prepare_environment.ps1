param([switch]$SkipFrontendInstall)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = Join-Path $ProjectRoot ".runtime"
$ToolsRoot = Join-Path $RuntimeRoot "tools"
$DownloadRoot = Join-Path $RuntimeRoot "downloads"
$NodeVersion = "24.19.0"
$UvVersion = "0.13.4"
$NodeArchive = "node-v$NodeVersion-win-x64.zip"
$UvArchive = "uv-x86_64-pc-windows-msvc.zip"
$NodeSha256 = "57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73"
$UvSha256 = "ccec7508a07d9933d7cb1261880633efcf1f30d6e6eddab21823f1dae6f23225"
$NodeHome = Join-Path $ToolsRoot "node-v$NodeVersion-win-x64"
$UvHome = Join-Path $ToolsRoot "uv-$UvVersion"
$PythonHome = Join-Path $RuntimeRoot "python"
$VenvHome = Join-Path $RuntimeRoot "venv"

New-Item -ItemType Directory -Force -Path $ToolsRoot, $DownloadRoot, $PythonHome | Out-Null
function Get-VerifiedDownload([string]$Url, [string]$Path, [string]$ExpectedHash) {
  if (-not (Test-Path $Path) -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
    Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    Write-Host "Downloading $([IO.Path]::GetFileName($Path))"
    Invoke-WebRequest -Uri $Url -OutFile $Path
  }
  $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $ExpectedHash) { throw "SHA-256 mismatch for $Path (expected $ExpectedHash, got $actual)." }
}

$nodeZip = Join-Path $DownloadRoot $NodeArchive
$uvZip = Join-Path $DownloadRoot $UvArchive
Get-VerifiedDownload "https://nodejs.org/dist/v$NodeVersion/$NodeArchive" $nodeZip $NodeSha256
Get-VerifiedDownload "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvArchive" $uvZip $UvSha256
if (-not (Test-Path (Join-Path $NodeHome "node.exe"))) {
  Expand-Archive -LiteralPath $nodeZip -DestinationPath $ToolsRoot -Force
}
if (-not (Test-Path (Join-Path $UvHome "uv.exe"))) {
  New-Item -ItemType Directory -Force -Path $UvHome | Out-Null
  Expand-Archive -LiteralPath $uvZip -DestinationPath $UvHome -Force
  $extractedUv = Get-ChildItem -LiteralPath $UvHome -Filter "uv.exe" -Recurse | Select-Object -First 1
  if (-not $extractedUv) { throw "The verified uv archive did not contain uv.exe." }
  if ($extractedUv.DirectoryName -ne $UvHome) { Copy-Item -LiteralPath $extractedUv.FullName -Destination (Join-Path $UvHome "uv.exe") -Force }
}

$env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"
$env:UV_PYTHON_INSTALL_DIR = $PythonHome
$env:UV_PROJECT_ENVIRONMENT = $VenvHome
$uv = Join-Path $UvHome "uv.exe"
$pythonExe = $null
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
  $candidate = & $pyLauncher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
  if ($LASTEXITCODE -eq 0 -and (Test-Path $candidate)) { $pythonExe = $candidate.Trim() }
}
if (-not $pythonExe) {
  $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($pythonCommand) {
    $candidateVersion = & $pythonCommand.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidateVersion.Trim() -eq "3.12") { $pythonExe = $pythonCommand.Source }
  }
}
if (-not $pythonExe) {
  Write-Host "Installing managed Python 3.12.10..."
  & $uv python install 3.12.10
  if ($LASTEXITCODE -ne 0) { throw "uv could not install Python 3.12.10. Check network access and retry this script." }
  $pythonExe = (& $uv python find 3.12.10).Trim()
}
Write-Host "Syncing Python dependencies from uv.lock..."
& $uv sync --project $ProjectRoot --locked --all-extras --python $pythonExe
if ($LASTEXITCODE -ne 0) { throw "Locked Python dependency installation failed." }

$node = Join-Path $NodeHome "node.exe"
$npm = Join-Path $NodeHome "npm.cmd"
if (-not $SkipFrontendInstall) {
  Write-Host "Installing frontend dependencies from package-lock.json..."
  & $npm ci --prefix (Join-Path $ProjectRoot "frontend") --cache (Join-Path $RuntimeRoot "npm-cache")
  if ($LASTEXITCODE -ne 0) { throw "Locked frontend dependency installation failed." }
}

$python = Join-Path $VenvHome "Scripts\python.exe"
$metadata = [ordered]@{
  prepared_utc = [DateTime]::UtcNow.ToString("o")
  python = (& $python --version 2>&1 | Out-String).Trim()
  node = (& $node --version 2>&1 | Out-String).Trim()
  npm = (& $npm --version 2>&1 | Out-String).Trim()
  uv = (& $uv --version 2>&1 | Out-String).Trim()
  python_lock = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot "uv.lock") -Algorithm SHA256).Hash.ToLowerInvariant()
  frontend_lock = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot "frontend\package-lock.json") -Algorithm SHA256).Hash.ToLowerInvariant()
}
$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RuntimeRoot "environment.json") -Encoding UTF8
Write-Host "Environment ready: Python $($metadata.python); Node $($metadata.node); npm $($metadata.npm); uv $($metadata.uv)" -ForegroundColor Green
Write-Host "Runtimes, virtual environment and package caches are under .runtime and are excluded from delivery ZIPs."
