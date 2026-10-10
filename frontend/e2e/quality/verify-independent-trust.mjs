// Offline W327 controller trust-chain verifier. Read-only; never signs or creates receipts.
// SOURCE-WRITER CANNOT GRANT RELEASE from JSON, SHA, environment variables or local CI claim.
import { readFileSync, existsSync } from 'node:fs'
import { resolve, join, isAbsolute } from 'node:path'
import { createHash, createPublicKey, verify } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { verifyArtifactBundle } from './playwright-artifact-proof.mjs'
const w327='C:/Users/1/Documents/YanceAuthority/20261005'
const pointer=join(w327,'LATEST_MASTER_CONTROLLER_POINTER.txt')
const rootPath=join(w327,'MasterController','W373_QA_PROTECTED_TRUST_ROOT.json')
const approvalPath=join(w327,'MasterController','W373_QA_W377_W327_PROTECTED_APPROVAL.json')
const sha=s=>createHash('sha256').update(s).digest('hex').toUpperCase()
function fail(message){console.error('W327_TRUST_GATE_HOLD:'+message);process.exit(1)}
function read(path){if(!existsSync(path))fail('PROTECTED_AUTHORITY_RECORD_MISSING');return readFileSync(path)}
function cert(key,msg,sig){
 if(typeof key!=='string'||typeof sig!=='string'||!sig.match(/^[A-Za-z0-9+/=]+$/))return false
 try{return verify(null,Buffer.from(msg,'utf8'),createPublicKey(key),Buffer.from(sig,'base64'))}catch{return false}
}
try {
 const authority=read(pointer).toString('utf8')
 if(!authority.includes('ACTIVE_CONTROLLER_ROLE=WINDOW327_YANCE_MASTER_CONTROLLER'))
  fail('WRONG_ACTIVE_CONTROLLER')
 const field=k=>authority.match(new RegExp('^'+k+'=([A-Fa-f0-9]{64})$','m'))?.[1]?.toUpperCase()
 const rootExpected=field('W373_RELEASE_TRUST_ROOT_SHA256')
 const approvalExpected=field('W373_RELEASE_APPROVAL_SHA256')
 if(!rootExpected||!approvalExpected)fail('W327_POINTER_HAS_NO_PROTECTED_TRUST_DIGESTS')
 const rootBytes=read(rootPath), approvalBytes=read(approvalPath)
 if(sha(rootBytes)!==rootExpected||sha(approvalBytes)!==approvalExpected)
  fail('W327_PROTECTED_POINTER_DIGEST_MISMATCH')
 const root=JSON.parse(rootBytes.toString('utf8'))
 const approval=JSON.parse(approvalBytes.toString('utf8'))
 const signed=JSON.stringify(approval.payload)
 if(root.role!=='W327_RELEASE_AUTHORITY'||root.approvedReviewer!=='W377'
  ||!root.w327PublicKey||!root.w377PublicKey)fail('UNREGISTERED_REVIEWER_OR_SIGNING_ROOT')
 if(!cert(root.w327PublicKey,signed,approval.w327Signature)
  ||!cert(root.w377PublicKey,signed,approval.w377Signature))
  fail('INDEPENDENT_ED25519_SIGNATURE_INVALID')
 const a=approval.payload||{}
 const current=execFileSync('git',['rev-parse','HEAD'],{cwd:resolve(import.meta.dirname,'../..'),encoding:'utf8'}).trim()
 const parent=execFileSync('git',['rev-parse','HEAD^'],{cwd:resolve(import.meta.dirname,'../..'),encoding:'utf8'}).trim()
 if(a.sourceSha!==current||a.parentSha!==parent||a.decision!=='W327_PROTECTED_APPROVED'
  ||a.reviewer!=='W377'||a.controller!=='W327')fail('DECISION_ROLE_OR_EXACT_GIT_SHA_MISMATCH')
 const run=a.githubRun||{}
 if(!/^\d+$/.test(String(run.runId||''))||!/^\d+$/.test(String(run.jobId||''))||
  !/^\d+$/.test(String(run.repositoryId||''))||String(run.repositoryId)!==String(root.repositoryId)
  ||run.headSha!==current||run.branch!==a.branch||run.conclusion!=='success'
  ||!/^\d+$/.test(String(run.runAttempt||''))||run.jobName!=='native-chromium'
  ||run.runnerOS!=='Windows'||run.runnerLabel!=='yance-native-qa'
  ||!run.runUrl?.startsWith('https://github.com/'))
  fail('PROTECTED_REAL_GITHUB_RUN_JOB_RUNNER_UNVERIFIED')
 if(!a.evidence||a.evidence.class!=='NATIVE_POSTGRES_AUTH'||
  a.evidence.viewport!=='920x620'||!Array.isArray(a.evidence.acceptedIds)
  ||!a.evidence.pgProbeSha256||!a.evidence.playwrightJsonSha256
  ||!a.evidence.traceManifestSha256||!a.evidence.restartProofSha256
  ||!a.evidence.githubJobApiSha256)
  fail('NATIVE_PG_AUTH_CHATHISTORY_RESTART_OR_TRACE_PROOF_MISSING')
 if(!a.evidence.acceptedIds.length||new Set(a.evidence.acceptedIds).size!==a.evidence.acceptedIds.length)
  fail('UNBOUND_OR_DUPLICATE_PASSED_TEST_IDS')
 // Protected approval alone is not enough: runner artifacts must be independently
 // retrieved by W327/W377 from the named GitHub job, not locally supplied by W373.
 const evidenceRoot=process.env.W327_DOWNLOADED_PROTECTED_RUN_ARTIFACT_DIR||''
 if(!evidenceRoot||!isAbsolute(evidenceRoot)||
  resolve(evidenceRoot).startsWith(resolve(import.meta.dirname)))
  fail('NOT_INDEPENDENTLY_RETRIEVED_CI_ARTIFACTS')
 const checks=[
  ['playwright-results.json',a.evidence.playwrightJsonSha256],
  ['trace-manifest.json',a.evidence.traceManifestSha256],
  ['native-pg-evidence.json',a.evidence.pgProbeSha256],
  ['restart-proof.json',a.evidence.restartProofSha256],
  ['github-job-api.json',a.evidence.githubJobApiSha256]
 ]
 for(const [name,digest] of checks){
  const data=read(join(evidenceRoot,name))
  if(sha(data)!==String(digest).toUpperCase())fail('RUNNER_ARTIFACT_DIGEST_MISMATCH:'+name)
 }
 const results=JSON.parse(read(join(evidenceRoot,'playwright-results.json')).toString('utf8'))
 const trace=JSON.parse(read(join(evidenceRoot,'trace-manifest.json')).toString('utf8'))
 const githubJob=JSON.parse(read(join(evidenceRoot,'github-job-api.json')).toString('utf8'))
 // This JSON must come from W327 independently downloading GitHub API output,
 // and its digest is anchored by W327/W377 signatures and protected pointer.
 if(String(githubJob.id)!==String(run.jobId)||String(githubJob.run_id)!==String(run.runId)
  ||githubJob.name!==run.jobName||githubJob.head_sha!==current
  ||githubJob.conclusion!=='success'
  ||!Array.isArray(githubJob.labels)||!githubJob.labels.includes('yance-native-qa')
  ||String(githubJob.run_attempt)!==String(run.runAttempt))
  fail('W327_SIGNED_GITHUB_API_JOB_RUN_ATTEMPT_RUNNER_MISMATCH')
 const pg=JSON.parse(read(join(evidenceRoot,'native-pg-evidence.json')).toString('utf8'))
 const restart=JSON.parse(read(join(evidenceRoot,'restart-proof.json')).toString('utf8'))
 if(pg.sourceSha!==current||pg.database!==restart.database||
    !pg.customerId||!pg.organizationId||!pg.authenticatedUserId||!pg.chatHistoryId||
    pg.queryProtocol!=='READ_ONLY_PSQL_POSTGRES'||
    pg.sessionId!==restart.sessionId||pg.chatHistoryId!==restart.chatHistoryId)
  fail('PG_AUTH_IDENTITY_CHAT_ROW_OR_ORG_PROOF_INCOMPLETE')
 if(restart.sourceSha!==current||restart.before?.appPid===restart.after?.appPid||
    !(Number(restart.after?.appStartedAt)>Number(restart.before?.appStartedAt))||
    restart.before?.sessionId!==restart.after?.sessionId||
    restart.before?.chatHistoryId!==restart.after?.chatHistoryId||
    restart.after?.readbackConfirmed!==true)
  fail('RESTART_RELOAD_PERSISTENCE_AND_PROCESS_CHANGE_NOT_PROVEN')
 // Independent verification hashes *each actual ZIP file* from the protected
 // downloaded CI bundle, then cross-checks true Playwright JSON status and
 // exact signed repository/run/job/attempt/source/test IDs. JSON alone is not proof.
 const verified=verifyArtifactBundle({report:results,manifest:trace,artifactRoot:evidenceRoot,
  sourceArtifactRoot:evidenceRoot,acceptedIds:a.evidence.acceptedIds,sourceSha:current,run})
 if(verified.verifiedIds.length!==a.evidence.acceptedIds.length)
  fail('ACCEPTANCE_SET_NOT_MATCHED_TO_REAL_ZIP_AND_PLAYWRIGHT')
 // This is an independent-chain eligibility check only. W327 final integration,
 // required GitHub branch protection and complete 344 rows remain separate.
 console.log('W327_PROTECTED_TRUST_CHAIN_VERIFIED_PENDING_FINAL_CONTROLLER_ADMISSION')
}catch(e){fail('PROTECTED_ATTESTATION_NOT_VERIFIED:'+String(e?.message||e))}
