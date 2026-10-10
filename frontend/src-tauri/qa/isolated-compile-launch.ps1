param(
  [string]$Stage = 'C:\Users\1\YanceScratch\W355_NATIVE_TAURI_ISOLATED',
  [string]$Source = 'C:\Users\1\YanceWorktrees\yance-chattermate-window355-desktop-bridge\frontend\src-tauri',
  [switch]$InspectWebView,
  [string]$QaDataRoot = 'C:\Users\1\YanceScratch\W355_NATIVE_TAURI_DPAPI_DATA'
)
$ErrorActionPreference = 'Stop'
$env:CARGO_HOME = 'D:\Yance-Windows-Runtime-20261005\qualification\w351-08e-package\cargo-home'
$env:RUSTUP_HOME = 'D:\Yance-Windows-Runtime-20261005\qualification\w351-08e-package\rustup-home'
$env:CARGO_TARGET_DIR = 'D:\Yance-Windows-Runtime-20261005\qualification\w351-08e-package\target'
$env:PATH = "$env:CARGO_HOME\bin;$env:PATH"
Set-Location $Source
& "$env:CARGO_HOME\bin\cargo.exe" build --offline
if($LASTEXITCODE -ne 0) { throw "CARGO_BUILD_FAILED=$LASTEXITCODE" }
$old = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'Yance.exe' -and $_.ExecutablePath -eq (Join-Path $Stage 'Yance.exe')
}
if($old) {
  $old | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction Stop }
  Start-Sleep -Seconds 2
}
$copied = $false
foreach ($n in 1..10) {
  try {
    Copy-Item (Join-Path $env:CARGO_TARGET_DIR 'debug\Yance.exe') (Join-Path $Stage 'Yance.exe') -Force -ErrorAction Stop
    $copied = $true; break
  } catch { Start-Sleep -Seconds 2 }
}
if(-not $copied) { throw 'QA_EXE_LOCKED_AFTER_20_SECONDS' }
$env:YANCE_W355_QA_DATA_ROOT = $QaDataRoot
if($InspectWebView) {
  $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = '--remote-debugging-port=58455'
} else {
  Remove-Item Env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue
}
$p = Start-Process -FilePath (Join-Path $Stage 'Yance.exe') -WorkingDirectory $Stage -PassThru
"QA_APP_PID=$($p.Id)"
Start-Sleep -Seconds 16
$err = Join-Path $env:YANCE_W355_QA_DATA_ROOT 'qa-early-error.txt'
$status = Join-Path $env:YANCE_W355_QA_DATA_ROOT 'startup-status.txt'
"QA_EARLY_ERROR=$(if(Test-Path $err) {Get-Content $err} else {'NONE'})"
"QA_STARTUP_STATUS=$(if(Test-Path $status) {Get-Content $status} else {'NONE'})"
"QA_RUNNING=$(-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) -eq $false)"
