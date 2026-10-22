$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BaselinePath = Join-Path $PSScriptRoot 'BASELINE_MANIFEST.json'
$baseline = Get-Content -LiteralPath $BaselinePath -Raw | ConvertFrom-Json
$excludedDirectories = @('.runtime','.venv','.pytest_cache','node_modules','dist','test-results','__pycache__','.git','.mypy_cache','.ruff_cache','playwright-report','coverage','*.egg-info')
function Get-PackageFiles([string[]]$ExcludeFiles) {
  $files = [System.Collections.Generic.List[object]]::new()
  $pending = [System.Collections.Generic.Stack[string]]::new(); $pending.Push($ProjectRoot)
  while ($pending.Count) {
    $directory = $pending.Pop()
    foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
      if ($item.PSIsContainer) { if ($excludedDirectories -notcontains $item.Name -and $item.Name -notlike '*.egg-info') { $pending.Push($item.FullName) }; continue }
      $relative = [IO.Path]::GetRelativePath($ProjectRoot, $item.FullName).Replace('\','/')
      if ($ExcludeFiles -contains $relative) { continue }
      $files.Add([pscustomobject]@{path=$relative;size_bytes=$item.Length;sha256=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()})
    }
  }
  return @($files | Sort-Object path)
}
$metaFiles = @('delivery/BASELINE_DIFF.json','delivery/FINAL_MANIFEST.json','delivery/SHA256SUMS.txt')
$sourceFiles = Get-PackageFiles $metaFiles
$baselineMap = @{}; foreach ($entry in $baseline.files) { $baselineMap[$entry.path] = $entry }
$currentMap = @{}; foreach ($entry in $sourceFiles) { $currentMap[$entry.path] = $entry }
$changed = [System.Collections.Generic.List[object]]::new(); $added = [System.Collections.Generic.List[object]]::new()
foreach ($entry in $sourceFiles) {
  if (-not $baselineMap.ContainsKey($entry.path)) { $added.Add($entry); continue }
  $old = $baselineMap[$entry.path]
  if ($old.sha256 -ne $entry.sha256) { $changed.Add([pscustomobject]@{path=$entry.path;old_size_bytes=$old.size_bytes;new_size_bytes=$entry.size_bytes;old_sha256=$old.sha256;new_sha256=$entry.sha256}) }
}
$removed = @($baseline.files | Where-Object { -not $currentMap.ContainsKey($_.path) } | ForEach-Object { [pscustomobject]@{path=$_.path;size_bytes=$_.size_bytes;sha256=$_.sha256} })
$diff = [ordered]@{schema_version='1.0';generated_at_local=[DateTimeOffset]::Now.ToString('o');baseline_manifest='BASELINE_MANIFEST.json';baseline_source_zip_sha256=$baseline.inner_candidate_zip_sha256;changed_files=@($changed);added_files=@($added);removed_files=$removed;counts=[ordered]@{baseline=$baseline.file_count;changed=$changed.Count;added=$added.Count;removed=$removed.Count;unchanged=$baseline.file_count-$changed.Count-$removed.Count}}
$diff | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'BASELINE_DIFF.json') -Encoding utf8
$manifestFiles = Get-PackageFiles @('delivery/FINAL_MANIFEST.json','delivery/SHA256SUMS.txt')
$manifest = [ordered]@{schema_version='1.0';generated_at_local=[DateTimeOffset]::Now.ToString('o');project_root='6G-RESCUE';manifest_self_hash_excluded=$true;checksum_file_excluded_from_itself=$true;excluded_generated_directories=$excludedDirectories;file_count=$manifestFiles.Count;files=$manifestFiles}
$manifestPath = Join-Path $PSScriptRoot 'FINAL_MANIFEST.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8
$sumLines = foreach ($entry in $manifestFiles) { "$($entry.sha256)  $($entry.path)" }
$sumLines += "$(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256 | ForEach-Object Hash | ForEach-Object ToLowerInvariant)  delivery/FINAL_MANIFEST.json"
$sumLines | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'SHA256SUMS.txt') -Encoding utf8
$diff.counts | ConvertTo-Json
Write-Output "manifest files: $($manifestFiles.Count)"
