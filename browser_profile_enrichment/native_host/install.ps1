param(
    [Parameter(Mandatory=$true)][string]$BackendRoot,
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [string]$InstallDir = "$env:LOCALAPPDATA\Yance\BrowserProfileEnrichment"
)

$ErrorActionPreference = "Stop"
$HostName = "com.yance.browser_profile_enrichment"
$ExtensionId = "hfcmihknnigilcafmalchjopmhhkihjf"
$AllowedOrigin = "chrome-extension://$ExtensionId/"
$RegistryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"

$BackendRoot = (Resolve-Path $BackendRoot).Path
$PythonExe = (Resolve-Path $PythonExe).Path
if (-not (Test-Path (Join-Path $BackendRoot "app\services\browser_profile_enrichment.py"))) {
    throw "BackendRoot does not contain the Window56 service"
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$SourceHost = Join-Path $PSScriptRoot "yance_browser_profile_host.py"
$HostScript = Join-Path $InstallDir "yance_browser_profile_host.py"
Copy-Item -Force $SourceHost $HostScript

$Launcher = Join-Path $InstallDir "yance_browser_profile_host.cmd"
$LauncherBody = @"
@echo off
set "YANCE_BACKEND_ROOT=$BackendRoot"
"$PythonExe" "$HostScript" %*
"@
Set-Content -Path $Launcher -Value $LauncherBody -Encoding ASCII

$ManifestPath = Join-Path $InstallDir "$HostName.json"
$Manifest = [ordered]@{
    name = $HostName
    description = "Yance one-shot browser-assisted profile enrichment"
    path = $Launcher
    type = "stdio"
    allowed_origins = @($AllowedOrigin)
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText(
    $ManifestPath,
    $ManifestJson,
    (New-Object System.Text.UTF8Encoding($false))
)

New-Item -Path $RegistryPath -Force | Out-Null
Set-Item -Path $RegistryPath -Value $ManifestPath

Write-Output "INSTALLED"
Write-Output "HOST=$HostName"
Write-Output "EXTENSION_ID=$ExtensionId"
Write-Output "MANIFEST=$ManifestPath"
