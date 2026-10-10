param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Yance\BrowserProfileEnrichment"
)

$ErrorActionPreference = "Stop"
$HostName = "com.yance.browser_profile_enrichment"
$RegistryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"

if (Test-Path $RegistryPath) {
    Remove-Item -Path $RegistryPath -Recurse -Force
}
if (Test-Path $InstallDir) {
    Remove-Item -Path $InstallDir -Recurse -Force
}
Write-Output "UNINSTALLED"
