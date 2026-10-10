// Untrusted CI self-observation, not W362 independent GitHub API approval. Copy actual trace ZIP bytes
// into downloadable artifact; independent reviewer must re-download and rehash.
import { readFileSync, existsSync, mkdirSync, writeFileSync, copyFileSync, lstatSync, realpathSync } from 'node:fs'
import { resolve, join, relative, sep } from 'node:path'
import { execFileSync } from 'node:child_process'
import { digest, verifyArtifactBundle } from './playwright-artifact-proof.mjs'
const cwd=resolve(import.meta.dirname,'../..')
const fail=s=>{console.error('UNPROVEN_NATIVE_CI:'+s);process.exit(1)}
const sourceSha=execFileSync('git',['rev-parse','HEAD'],{cwd,encoding:'utf8'}).trim()
const env=process.env
if(env.GITHUB_ACTIONS!=='true'||env.RUNNER_OS!=='Windows'||env.GITHUB_SHA!==sourceSha
 ||env.GITHUB_JOB!=='native-chromium'||!/^\d+$/.test(env.GITHUB_RUN_ID||'')
 ||!/^\d+$/.test(env.GITHUB_REPOSITORY_ID||'')||!/^\d+$/.test(env.GITHUB_RUN_ATTEMPT||''))
 fail('NOT_A_CURRENT_SHA_PROTECTED_GITHUB_WINDOWS_JOB')
if(env.RUNNER_ENVIRONMENT!=='github-hosted'||env.GITHUB_REPOSITORY!=='wangyi198675-coder/yance-chattermate')
 fail('NOT_OFFICIAL_EPHEMERAL_WINDOWS_OR_WRONG_REPO')
// Runner cannot self-certify GitHub job ID. W362 independently queries GH API before any admission.
const run={runId:env.GITHUB_RUN_ID,jobName:env.GITHUB_JOB,jobId:'W327_GITHUB_API_LOOKUP_REQUIRED',
 repositoryId:env.GITHUB_REPOSITORY_ID,runAttempt:env.GITHUB_RUN_ATTEMPT}
const raw=join(cwd,'test-results/playwright-results.json')
if(!existsSync(raw))fail('PLAYWRIGHT_RAW_JSON_MISSING')
const report=JSON.parse(readFileSync(raw,'utf8'))
const out=join(cwd,'test-results/yance-quality')
const tracesDir=join(out,'traces')
mkdirSync(tracesDir,{recursive:true})
const specs=(suites,acc=[])=>{for(const s of suites||[]){acc.push(...(s.specs||[]));specs(s.suites,acc)}return acc}
const tests=[],used=new Set(),nativeDir=realpathSync(join(cwd,'test-results/playwright-artifacts'))
for(const spec of specs(report.suites)){
 const id=/^\[([A-Za-z0-9-]+)\]/.exec(spec.title||'')?.[1]
 if(!id)continue
 if(used.has(id))fail('DUPLICATE_SPEC_ID:'+id)
 used.add(id)
 const t=spec.tests||[]
 if(t.length!==1||t[0].projectName!=='chromium-native')fail('NON_NATIVE_OR_DUPLICATE_EXECUTION:'+id)
 if(t[0].status!=='expected'||t[0].results?.length!==1||t[0].results[0].status!=='passed')
  fail('NATIVE_TEST_FAILED_SKIP_OR_NOT_EXECUTED:'+id)
 const attachments=(t[0].results[0].attachments||[]).filter(a=>a.name==='trace')
 if(attachments.length!==1||!attachments[0].path)fail('PASSED_WITHOUT_SINGLE_TRACE:'+id)
 const original=realpathSync(attachments[0].path)
 if(lstatSync(attachments[0].path).isSymbolicLink()||!relative(nativeDir,original)
  ||relative(nativeDir,original).startsWith('..'+sep)||relative(nativeDir,original)==='..')
  fail('TRACE_SOURCE_UNTRUSTED_PATH:'+id)
 const dest=join(tracesDir,id+'.zip')
 copyFileSync(original,dest)
 tests.push({id,status:'passed',projectName:'chromium-native',sourceSha,
   runId:run.runId,jobId:run.jobId,repositoryId:run.repositoryId,runAttempt:run.runAttempt,
   tracePath:'traces/'+id+'.zip',traceSha256:digest(readFileSync(dest)),
   attachmentOriginalPath:relative(nativeDir,original).replaceAll('\\','/')})
}
if(!tests.length)fail('NO_NATIVE_PASSED_PLAYWRIGHT_TESTS')
const manifest={sourceSha,...{runId:run.runId,job:run.jobName,jobId:run.jobId,
 repositoryId:run.repositoryId,runAttempt:run.runAttempt},tests}
writeFileSync(join(out,'trace-manifest.json'),JSON.stringify(manifest,null,2)+'\n')
try{
 verifyArtifactBundle({report,manifest,artifactRoot:out,sourceArtifactRoot:join(cwd,'test-results'),
  acceptedIds:tests.filter(t=>!t.id.startsWith('DIAG-')&&t.id!=='GF-INTENT-15').map(t=>t.id),sourceSha,run})
}catch(e){fail('SELF_OBSERVATION_TRACE_BYTES_OR_PLAYWRIGHT_MISMATCH:'+e.message)}
writeFileSync(join(out,'ci-run-context-UNVERIFIED.json'),JSON.stringify({
 evidenceClass:'UNVERIFIED_SELF_OBSERVATION_NOT_CONTROLLER_APPROVAL',
 sourceSha,...run,githubRepository:env.GITHUB_REPOSITORY,
 artifacts:{playwrightJsonSha256:digest(readFileSync(raw)),
 traceManifestSha256:digest(readFileSync(join(out,'trace-manifest.json')))},
 verifiedTraceZipsCopied:tests.length
},null,2)+'\n')
console.log('CI_ZIP_BYTES_CAPTURED_UNVERIFIED_PENDING_W362_EXTERNAL_GH_API_RETRIEVAL count='+tests.length)
