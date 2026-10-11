param([Parameter(Mandatory=$true)][ValidateSet('protect','unprotect')][string]$Mode,
      [Parameter(Mandatory=$true)][string]$Account)
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Security -ErrorAction Stop
  $encoded = [Console]::In.ReadLine()
  if ([string]::IsNullOrWhiteSpace($encoded)) { throw 'Missing secret input' }
  $bytes = [Convert]::FromBase64String($encoded)
  $sha = [Security.Cryptography.SHA256]::Create()
  $entropy = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes('Yance-Personal-WA-v1:' + $Account))
  if ($Mode -eq 'protect') {
    $output = [System.Security.Cryptography.ProtectedData]::Protect(
      $bytes, $entropy, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
  } else {
    $output = [System.Security.Cryptography.ProtectedData]::Unprotect(
      $bytes, $entropy, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
  }
  [Console]::Out.WriteLine([Convert]::ToBase64String($output))
} catch {
  [Console]::Error.WriteLine('DPAPI_OPERATION_FAILED')
  exit 23
} finally {
  if ($bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
  if ($output) { [Array]::Clear($output, 0, $output.Length) }
}
