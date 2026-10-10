# GitHub-hosted windows-2025 only. Fail closed on every native dependency.
param([ValidateSet('prepare','start','restart')][string]$Phase)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
 throw 'GITHUB_WINDOWS_RUN_REQUIRED'
}
if ($env:GITHUB_EVENT_NAME -eq 'pull_request_target') { throw 'UNTRUSTED_PR_TARGET_FORBIDDEN' }
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$logDir = Join-Path $frontend 'test-results\yance-quality\hosted-native'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$py = (Get-Command python -ErrorAction Stop).Source
function PutEnv([string]$key,[string]$value) {
 if (-not $env:GITHUB_ENV) { throw 'GITHUB_ENV_REQUIRED' }
 # Mask disposable QA values BEFORE persisting GITHUB_ENV. These were visible
 # in GitHub's untrusted logs on the first real native job.
 if($key -in @('DATABASE_URL','JWT_SECRET_KEY','CONVERSATION_SECRET_KEY',
              'ENCRYPTION_KEY','YANCE_QA_SYNTHETIC_PASSWORD')){
  Write-Output ('::add-mask::'+$value)
 }
 Add-Content -Path $env:GITHUB_ENV -Encoding UTF8 -Value ($key+'='+$value)
 [Environment]::SetEnvironmentVariable($key,$value,'Process')
}
function RequireExit([string]$label) {
 if ($LASTEXITCODE -ne 0) { throw ($label+'_FAILED_'+$LASTEXITCODE) }
}
function Health {
 for($i=0;$i -lt 60;$i++) {
  try {
   $r=Invoke-WebRequest 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2
   if ($r.StatusCode -eq 200) { return }
  } catch {}
  Start-Sleep -Seconds 2
 }
 throw 'REAL_NATIVE_APP_HEALTH_FAILED'
}
if ($Phase -eq 'prepare') {
 $pgbin='C:\Program Files\PostgreSQL\17\bin'
 $pgdata='C:\PostgreSQL\17\data'
 $psql=Join-Path $pgbin 'psql.exe'
 if (-not (Test-Path $psql)) { throw 'OFFICIAL_WINDOWS_2025_POSTGRES_17_NOT_FOUND' }
 $conf=Join-Path $pgdata 'postgresql.conf'
 $raw=[IO.File]::ReadAllText($conf)
 $pattern='(?m)^\s*#?\s*listen_addresses\s*=.*$'
 if (-not [regex]::IsMatch($raw,$pattern)) { throw 'PG_BIND_ADDRESS_NOT_CONFIGURED' }
 [IO.File]::WriteAllText($conf,[regex]::Replace($raw,$pattern,"listen_addresses = 'localhost'"))
 # Actual native migration add_ticketing_core_001 requires pgvector; compile the
 # pinned mature upstream extension against this VM's real PostgreSQL 17.
 $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
 if (-not (Test-Path $vswhere)) { throw 'OFFICIAL_GH_RUNNER_VSWHERE_MISSING' }
 $vsRoot=(& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
 if (-not $vsRoot) { throw 'OFFICIAL_GH_RUNNER_MSVC_COMPONENT_MISSING' }
 $vcvars=Join-Path $vsRoot 'VC\Auxiliary\Build\vcvars64.bat'
 if (-not (Test-Path $vcvars)) { throw 'OFFICIAL_MSVC_CXX_COMPILER_MISSING_FOR_REAL_PGVECTOR' }
 $extSrc=Join-Path $env:RUNNER_TEMP 'yance-native-pgvector-src'
 & git clone --quiet --depth 1 --branch v0.8.1 https://github.com/pgvector/pgvector.git $extSrc
 RequireExit 'PINNED_PGVECTOR_GIT_CLONE'
 $build='call "'+$vcvars+'" >nul && set "PGROOT=C:\Program Files\PostgreSQL\17" && cd /d "'+$extSrc+'" && nmake /NOLOGO /F Makefile.win && nmake /NOLOGO /F Makefile.win install'
 & cmd.exe /d /s /c $build *>&1 | Tee-Object -FilePath (Join-Path $logDir 'pgvector-native-build.log')
 RequireExit 'REAL_WINDOWS_PGVECTOR_NATIVE_INSTALL'
 Set-Service postgresql-x64-17 -StartupType Manual
 Start-Service postgresql-x64-17
 & $psql --version | Tee-Object -FilePath (Join-Path $logDir 'postgres-client-version.log')
 & (Join-Path $pgbin 'pg_isready.exe') -h 127.0.0.1 -p 5432
 RequireExit 'REAL_POSTGRES_READY'
 $env:PGPASSWORD='root'
 $password=([guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N'))
 Write-Output ('::add-mask::'+$password)
 ("CREATE ROLE yance_ci_runner LOGIN PASSWORD '"+$password+"' NOSUPERUSER NOCREATEDB NOCREATEROLE;") |
   & $psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1
 RequireExit 'CREATE_QA_ROLE'
 'CREATE DATABASE yance_hosted_qa OWNER yance_ci_runner;' |
   & $psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1
 RequireExit 'CREATE_QA_DATABASE'
 & $psql -h 127.0.0.1 -U postgres -d yance_hosted_qa -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS vector'
 RequireExit 'CREATE_ACTUAL_PGVECTOR_EXTENSION'
 & $psql -h 127.0.0.1 -U postgres -d yance_hosted_qa -v ON_ERROR_STOP=1 -c "SELECT extversion FROM pg_extension WHERE extname='vector'"
 RequireExit 'REAL_PGVECTOR_VERSION_QUERY'
 $adminPassword=([guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N'))
 ("ALTER ROLE postgres WITH PASSWORD '"+$adminPassword+"';") |
   & $psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1
 RequireExit 'ROTATE_DEFAULT_IMAGE_POSTGRES_ADMIN'
 Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
 $svc=Join-Path $env:RUNNER_TEMP 'yance-pg-service.conf'
 [IO.File]::WriteAllText($svc,("[nativeqa]`nhost=127.0.0.1`nport=5432`n" +
  "dbname=yance_hosted_qa`nuser=yance_ci_runner`npassword=$password`n"))
 PutEnv 'DATABASE_URL' ('postgresql+psycopg://yance_ci_runner:'+$password+'@127.0.0.1:5432/yance_hosted_qa')
 PutEnv 'YANCE_QA_PSQL_EXE' $psql
 PutEnv 'YANCE_QA_PGSERVICEFILE' $svc
 PutEnv 'YANCE_QA_PGSERVICE' 'nativeqa'
 PutEnv 'YANCE_QA_ISOLATED' '1'
 PutEnv 'YANCE_QA_FIXTURE' 'NATIVE_POSTGRES_AUTH'
 PutEnv 'YANCE_QA_NATIVE_URL' 'http://127.0.0.1:5173'
 PutEnv 'YANCE_QA_NATIVE_API_URL' 'http://127.0.0.1:8000'
 PutEnv 'ENVIRONMENT' 'development'
 PutEnv 'REDIS_ENABLED' 'false'
 PutEnv 'S3_FILE_STORAGE' 'false'
 PutEnv 'FRONTEND_URL' 'http://127.0.0.1:5173'
 PutEnv 'BACKEND_URL' 'http://127.0.0.1:8000'
 PutEnv 'CORS_ORIGINS' '["http://127.0.0.1:5173","http://localhost:5173","http://127.0.0.1:8000"]'
 PutEnv 'VITE_API_URL' 'http://127.0.0.1:8000/api/v1'
 PutEnv 'VITE_WS_URL' 'ws://127.0.0.1:8000'
 PutEnv 'JWT_SECRET_KEY' ([guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N'))
 PutEnv 'CONVERSATION_SECRET_KEY' ([guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N'))
 $qaPassword=([guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N'))
 $passFile=Join-Path $env:RUNNER_TEMP 'qa-synthetic-user-password.txt'
 [IO.File]::WriteAllText($passFile,$qaPassword)
 PutEnv 'YANCE_QA_SYNTHETIC_PASSWORD' $qaPassword
 PutEnv 'YANCE_QA_AUTH_PASSWORD_FILE' $passFile
 Push-Location $backend
 try {
  & $py -m pip install -r requirements.txt *>&1 |
    Tee-Object -FilePath (Join-Path $logDir 'pip-install.log')
  RequireExit 'BACKEND_REAL_REQUIREMENTS'
  $key=(& $py -c 'import base64;from cryptography.fernet import Fernet;print(base64.b64encode(Fernet.generate_key()).decode())').Trim()
  RequireExit 'GENERATE_DISPOSABLE_ENCRYPTION_KEY'
  PutEnv 'ENCRYPTION_KEY' $key
  & $py -m alembic upgrade head *>&1 |
    Tee-Object -FilePath (Join-Path $logDir 'alembic.log')
  RequireExit 'REAL_ALEMBIC_MIGRATIONS'
  & $py (Join-Path $PSScriptRoot 'hosted-native-seed.py') seed *>&1 |
    Tee-Object -FilePath (Join-Path $logDir 'orm-seed.log')
  RequireExit 'REAL_NATIVE_ORM_SEED'
 } finally { Pop-Location }
 Write-Output 'REAL_POSTGRES_MIGRATION_SEED_DONE_NOT_BROWSER_PASS'
}
function GetBoundNativeBackendPid {
 $listeners=@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop |
    Where-Object { $_.LocalAddress -in @('127.0.0.1','::1') })
 $owners=@($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
 if($owners.Count -ne 1){throw 'NATIVE_BACKEND_EXPECTED_ONE_LOOPBACK_LISTENER'}
 $ownerPid=[int]$owners[0]
 $pinfo=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$ownerPid)
 if($null -eq $pinfo -or $pinfo.Name -notmatch '^python(?:\.exe)?$' -or
    $pinfo.CommandLine -notmatch 'uvicorn|multiprocessing'){
   throw 'NATIVE_BACKEND_PORT_NOT_OWNED_BY_REAL_PYTHON'
 }
 return $ownerPid
}
function BeginBackend {
 $args=@('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000')
 $p=Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory $backend -PassThru -RedirectStandardOutput (Join-Path $logDir 'backend-stdout.log') -RedirectStandardError (Join-Path $logDir 'backend-stderr.log')
 Health
 $boundPid=GetBoundNativeBackendPid
 Set-Content (Join-Path $env:RUNNER_TEMP 'qa-backend.pid') $boundPid
 Write-Output ('REAL_BACKEND_BOUND_LOOPBACK_PID='+$boundPid)
 return $boundPid
}
if ($Phase -eq 'start') {
 $backendPid=BeginBackend
 $probe=Join-Path $logDir 'anonymous-native-access-check.log'
 $status=0
 try {
  Invoke-WebRequest 'http://127.0.0.1:8000/api/v1/chats/00000000-0000-0000-0000-000000000000' -UseBasicParsing -TimeoutSec 5 | Out-Null
  $status=200
 }catch{if($_.Exception.Response){$status=[int]$_.Exception.Response.StatusCode}else{throw}}
 Set-Content -Path $probe -Value ('ANONYMOUS_NATIVE_CHAT_STATUS='+$status)
 if($status -notin @(401,403)){throw ('ANONYMOUS_NATIVE_CHAT_NOT_DENIED_'+$status)}
 $node=(Get-Command node -ErrorAction Stop).Source
 $vite=Join-Path $frontend 'node_modules\vite\bin\vite.js'
 if (-not (Test-Path $vite)) { throw 'REAL_VITE_DEPENDENCIES_MISSING' }
 $web=Start-Process -FilePath $node -WorkingDirectory $frontend -PassThru -ArgumentList @($vite,'--host','127.0.0.1','--port','5173','--strictPort') -RedirectStandardOutput (Join-Path $logDir 'vite-stdout.log') -RedirectStandardError (Join-Path $logDir 'vite-stderr.log')
 Set-Content (Join-Path $env:RUNNER_TEMP 'qa-vite.pid') $web.Id
 $ok=$false
 for($i=0;$i -lt 45;$i++){
  try {
   $r=Invoke-WebRequest 'http://127.0.0.1:5173/yance' -UseBasicParsing -TimeoutSec 3
   if($r.StatusCode -eq 200){$ok=$true;break}
  }catch{}
  Start-Sleep -Seconds 2
 }
 if (-not $ok){throw 'VUE_NATIVE_HOST_ROUTE_NOT_200'}
 Write-Output 'REAL_VUE_HTTP_200_NOT_ACCEPTED_UAT'
}
if ($Phase -eq 'restart') {
 $before=[int](Get-Content (Join-Path $env:RUNNER_TEMP 'qa-backend.pid') -Raw)
 if($before -ne (GetBoundNativeBackendPid)){throw 'NATIVE_RESTART_PID_DIFFERENT_FROM_BOUND_LISTENER'}
 Get-Process -Id $before -ErrorAction Stop | Stop-Process -Force
 Start-Sleep -Seconds 2
 if(Get-Process -Id $before -ErrorAction SilentlyContinue){throw 'BACKEND_OLD_PID_STILL_RUNNING'}
 $after=BeginBackend
 if($before -eq $after){throw 'PROCESS_ID_NOT_CHANGED'}
 Push-Location $backend
 try {
  & $py (Join-Path $PSScriptRoot 'hosted-native-seed.py') readback *>&1 |
    Tee-Object -FilePath (Join-Path $logDir 'postgres-restart-readback.log')
  RequireExit 'RESTART_PG_JOINED_READBACK'
 } finally { Pop-Location }
 @{sourceSha=$env:GITHUB_SHA;githubRun=$env:GITHUB_RUN_ID;beforePid=$before;afterPid=$after;
   pgIdentityRestored=$true;type='SELF_OBSERVATION_NOT_RELEASE_PROOF'} |
    ConvertTo-Json | Set-Content (Join-Path $logDir 'restart-proof-UNVERIFIED.json')
 Write-Output 'REAL_PROCESS_RESTART_AND_JOINED_POSTGRES_READBACK_PASS_NOT_E2E'
}
