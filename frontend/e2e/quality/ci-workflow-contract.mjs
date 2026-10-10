// YAML-source guard only. MUST NOT assert that GitHub ran this workflow.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
const base=resolve(import.meta.dirname,'../../..')
const workflow=readFileSync(resolve(base,'.github/workflows/test.yml'),'utf8')
const nativeWindows=readFileSync(resolve(base,'frontend/e2e/quality/hosted-windows-native.ps1'),'utf8')
const inject=process.argv.includes('--inject=remove-runner')?'remove-runner':
 process.argv.includes('--inject=remove-branch')?'remove-branch':''
const content=inject==='remove-runner'?workflow.replace('runs-on: windows-2025','runs-on: invalid-unqualified-runner'):
 inject==='remove-branch'?workflow.replaceAll('integrate/post-c2-controlled-source-20261007','old-branch'):workflow
const required=[
 ['CURRENT_C3_BRANCH','integrate/post-c2-controlled-source-20261007'],
 ['NATIVE_RUNNER_LABEL','runs-on: windows-2025'],
 ['GITHUB_VM_RESTRICTION','GITHUB_HOSTED_ONLY'],
 ['READ_ONLY_PR_REPO_ACCESS','contents: read'],
 ['ACTUAL_POSTGRES_ALEMBIC_SEED','hosted-windows-native.ps1 -Phase prepare'],
 ['ACTUAL_NATIVE_APP_START','hosted-windows-native.ps1 -Phase start'],
 ['ACTUAL_POSTGRES_RESTART','hosted-windows-native.ps1 -Phase restart'],
 ['FOUR_REQUIRED_CHECKS_1','Requirement catalog and Playwright discovery'],
 ['FOUR_REQUIRED_CHECKS_2','Vitest typecheck build'],
 ['FOUR_REQUIRED_CHECKS_3','Backend pytest (not provider acceptance)'],
 ['FOUR_REQUIRED_CHECKS_4','REQUIRED real isolated PG Chromium 920x620 (no mock PASS)'],
 ['BACKEND_POSTGRES16_PGVECTOR','pgvector/pgvector:pg16'],
 ['BACKEND_PG_ISOLATED_TEST_DSN','W381_TEST_POSTGRES_URL'],
 ['BACKEND_PG_TEMPLATE','w381_test_template'],
 ['BACKEND_PG_REAL_MIGRATION','python -m alembic upgrade head'],
 ['BACKEND_TEST_OWNER','Run pytest (preserve all real failures, including W387 Agent schema)'],
 ['FAIL_CLOSED_PG_AUTH','YANCE_QA_NATIVE_API_URL'],
 ['ONLY_GITHUB_HOSTED','runs-on: windows-2025'],
 ['SOURCE_BRANCH_PR','pull_request:'],
 ['NATIVE_TEST','--project=chromium-native'],
 ['TRACE_PROVENANCE','capture-ci-provenance.mjs'],
 ['NEGATIVE_SELFTEST','gate-selftest.mjs'],
 ['PERMANENT_TEST_ARTIFACT','actions/upload-artifact@v4'],
]
let red=false
if(!nativeWindows.includes('CREATE_ACTUAL_PGVECTOR_EXTENSION')||!nativeWindows.includes('REAL_WINDOWS_PGVECTOR_NATIVE_INSTALL')){
 console.error('CI_SOURCE_CONTRACT_MISSING:WINDOWS_REAL_PGVECTOR');red=true
}
if(/continue-on-error:\s*true|pull_request_target\s*:|runs-on:\s*\[self-hosted|\btest\.skip\b/.test(content)){
 console.error('CI_FORBIDDEN_BYPASS_OR_SELF_HOSTED');red=true
}
for(const [key,match] of required)if(!content.includes(match)){
 console.error('CI_SOURCE_CONTRACT_MISSING:'+key);red=true
}
const repo=execFileSync('git',['remote','-v'],{cwd:base,encoding:'utf8'}).trim()
if(!repo.includes('github.com'))console.log('CI_REAL_REMOTE_UNVERIFIED')
console.log('CI_SOURCE_ONLY_NOT_REAL_WORKFLOW_RUN')
if(red)process.exitCode=1
