param(
  [string]$PlanPath = (Join-Path $PSScriptRoot "video_recording_plan.json"),
  [string]$OutputDirectory = (Join-Path $env:TEMP "lowalt6g-phase18-video-audio")
)

$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $OutputDirectory) {
  throw "Refusing to overwrite narration output: $OutputDirectory"
}
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $synth.SelectVoice("Microsoft Kangkang")
  $synth.Rate = -1
  $synth.Volume = 92
  $plan = Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($segment in $plan.segments) {
    $wav = Join-Path $OutputDirectory ("voice-" + $segment.id + ".wav")
    $synth.SetOutputToWaveFile($wav)
    $synth.Speak([string]$segment.narration)
    $synth.SetOutputToNull()
    $probe = & ffprobe.exe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $wav
    if ($LASTEXITCODE -ne 0) { throw "ffprobe failed for $wav" }
    $duration = [double]::Parse(($probe | Select-Object -First 1), [Globalization.CultureInfo]::InvariantCulture)
    $segment | Add-Member -NotePropertyName audio_path -NotePropertyValue $wav -Force
    $segment | Add-Member -NotePropertyName speech_seconds -NotePropertyValue $duration -Force
    $minimum = [Math]::Ceiling($duration + 1.5)
    if ([int]$segment.target_seconds -lt $minimum) {
      $segment.target_seconds = $minimum
    }
  }
  $plan | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory "video_recording_plan.json") -Encoding UTF8
  $summary = [pscustomobject]@{
    output_directory = $OutputDirectory
    voice = "Microsoft Kangkang zh-CN (Windows SAPI)"
    segment_count = $plan.segments.Count
    speech_seconds = [Math]::Round((($plan.segments | Measure-Object -Property speech_seconds -Sum).Sum), 2)
    planned_video_seconds = [int](($plan.segments | Measure-Object -Property target_seconds -Sum).Sum)
    plan_path = (Join-Path $OutputDirectory "video_recording_plan.json")
    segments = @($plan.segments | ForEach-Object { [pscustomobject]@{ id=$_.id; speech_seconds=[Math]::Round($_.speech_seconds,2); target_seconds=$_.target_seconds } })
  }
  $summary | ConvertTo-Json -Depth 6
} finally {
  $synth.Dispose()
}
