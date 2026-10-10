$ErrorActionPreference='Stop'
$stage='C:\Users\1\YanceScratch\W355_NATIVE_TAURI_ISOLATED'
$state='C:\Users\1\YanceScratch\W355_NATIVE_TAURI_DPAPI_DATA'
$pgbin=Join-Path $stage 'private-runtime\postgresql\bin'
$check = & (Join-Path $pgbin 'pg_isready.exe') -h 127.0.0.1 -p 55435
"POSTGRES_NATIVE_READINESS_EXIT=$LASTEXITCODE"
if($LASTEXITCODE -ne 0) { throw 'POSTGRES_NOT_READY' }
foreach($route in @('/health','/api/v1/organizations/setup-status')){
  $res=Invoke-WebRequest -Uri ('http://127.0.0.1:8000'+$route) -UseBasicParsing -TimeoutSec 5
  "API $route HTTP=$($res.StatusCode)"
}
$dpapi=Join-Path $state 'runtime-secrets.dpapi'
$plaintext=Join-Path $state 'private-secrets.txt'
"DPAPI_PERSISTED=$(Test-Path $dpapi)"
"PLAINTEXT_FILE_EXISTS=$(Test-Path $plaintext)"
if(Test-Path $plaintext){throw 'PLAINTEXT_SECRETS_SHOULD_NOT_EXIST'}
if(-not (Test-Path $dpapi)){throw 'DPAPI_CREDENTIAL_MISSING'}
"DPAPI_FILE_SHA256=$((Get-FileHash $dpapi -Algorithm SHA256).Hash)"
"POSTGRES_DATA_PRESENT=$(Test-Path (Join-Path $state 'postgres-data\PG_VERSION'))"
"STATE=$(Get-Content (Join-Path $state 'startup-status.txt'))"
