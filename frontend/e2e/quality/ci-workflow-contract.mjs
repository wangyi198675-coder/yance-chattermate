// YAML-source guard only. MUST NOT assert that GitHub ran this workflow.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
const base=resolve(import.meta.dirname,'../../..')
const workflow=readFileSync(resolve(base,'.github/workflows/test.yml'),'utf8')
const inject=process.argv.includes('--inject=remove-runner')?'remove-runner':
 process.argv.includes('--inject=remove-branch')?'remove-branch':''
const content=inject==='remove-runner'?workflow.replace('yance-native-qa','not-registered'):
 inject==='remove-branch'?workflow.replaceAll('integrate/post-c2-controlled-source-20261007','old-branch'):workflow
const required=[
 ['CURRENT_C3_BRANCH','integrate/post-c2-controlled-source-20261007'],
 ['NATIVE_RUNNER_LABEL','runs-on: [self-hosted, windows, yance-native-qa]'],
 ['FAIL_CLOSED_PG_AUTH','YANCE_QA_PGSERVICEFILE'],
 ['SOURCE_BRANCH_PR','pull_request:'],
 ['NATIVE_TEST','--project=chromium-native'],
 ['TRACE_PROVENANCE','capture-ci-provenance.mjs'],
 ['NEGATIVE_SELFTEST','gate-selftest.mjs'],
 ['PERMANENT_TEST_ARTIFACT','actions/upload-artifact@v4'],
]
let red=false
for(const [key,match] of required)if(!content.includes(match)){
 console.error('CI_SOURCE_CONTRACT_MISSING:'+key);red=true
}
const repo=execFileSync('git',['remote','-v'],{cwd:base,encoding:'utf8'}).trim()
if(!repo.includes('github.com'))console.log('CI_REAL_REMOTE_UNVERIFIED')
console.log('CI_SOURCE_ONLY_NOT_REAL_WORKFLOW_RUN')
if(red)process.exitCode=1
