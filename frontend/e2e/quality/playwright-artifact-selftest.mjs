// Test verifier only: synthetic ZIP with Playwright-shaped JSONL, NOT an E2E PASS.
import { mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync,unlinkSync,copyFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'
import { digest,verifyArtifactBundle } from './playwright-artifact-proof.mjs'
const dir=mkdtempSync(join(tmpdir(),'w373-trace-validation-'))
const sourceDir=join(dir,'playwright-artifacts','example')
const traceDir=join(dir,'traces')
mkdirSync(traceDir,{recursive:true});mkdirSync(sourceDir,{recursive:true})
const traceZip=join(traceDir,'RUX-02.zip'),originalZip=join(sourceDir,'trace.zip')
const id='RUX-02'
const makeZip=(kind='valid')=>{
 const py=String.raw`import sys,zipfile,json
p,k,t=sys.argv[1:]
with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
 if k == 'empty': pass
 else:
  o=lambda d:json.dumps(d,separators=(',',':'))+chr(10)
  before={'type':'before','callId':'action@1','title':'Before Hooks'}
  after={'type':'after','callId':'action@1'}
  events=[{'type':'context-options','origin':'testRunner','playwrightVersion':'1.63.0'}]
  if k!='no-actions': events+=[before,after]
  z.writestr('test.trace',''.join(o(v) for v in events))
  if k!='no-browser':
   z.writestr('0-trace.trace',o({'type':'context-options','title':'test.spec.ts:1 ['+t+'] synthetic verifier fixture'}))
`
 execFileSync(process.env.YANCE_QA_PYTHON||'python',['-c',py,traceZip,kind,id],{timeout:5000,windowsHide:true})
 copyFileSync(traceZip,originalZip)
}
const run={runId:'100001',jobId:'200002',repositoryId:'300003',runAttempt:'1',jobName:'native-chromium'}
const sourceSha='0123456789abcdef0123456789abcdef01234567'
const make=()=>({
 report:{config:{metadata:{sourceSha,githubRunId:run.runId,githubJob:run.jobName,
  githubRepositoryId:run.repositoryId,githubRunAttempt:run.runAttempt}},suites:[{specs:[{
 title:'[RUX-02] synthetic verifier fixture NOT native QA',
 tests:[{projectName:'chromium-native',status:'expected',results:[{status:'passed',
  attachments:[{name:'trace',path:'C:/runner/test-results/playwright-artifacts/example/trace.zip'}]}]}]
 }]}]},
 manifest:{sourceSha,runId:run.runId,job:run.jobName,jobId:'W327_GITHUB_API_LOOKUP_REQUIRED',
 repositoryId:run.repositoryId,runAttempt:run.runAttempt,tests:[{
  id,status:'passed',projectName:'chromium-native',sourceSha,runId:run.runId,
  jobId:'W327_GITHUB_API_LOOKUP_REQUIRED',repositoryId:run.repositoryId,runAttempt:run.runAttempt,
  tracePath:'traces/RUX-02.zip',traceSha256:digest(readFileSync(traceZip)),
  attachmentOriginalPath:'example/trace.zip'
 }]},
 artifactRoot:dir,sourceArtifactRoot:dir,acceptedIds:[id],sourceSha,run
})
let negatives=0
const blocked=(name,change,part)=>{
 const data=make();change(data)
 assert.throws(()=>verifyArtifactBundle(data),e=>e.message.includes(part),name+': expected '+part)
 negatives++;console.log('TRACE_NEGATIVE_BLOCKED '+name)
}
try{
 makeZip()
 assert.equal(verifyArtifactBundle(make()).verifiedIds[0],id)
 console.log('TRACE_SYNTHETIC_SELFTEST_BASELINE_ONLY')
 // Empty archive has valid ZIP EOCD but no test records.
 makeZip('empty')
 blocked('valid-empty-zip',()=>{},'TRACE_REQUIRED_PLAYWRIGHT_CONTENT_INVALID')
 makeZip('no-actions')
 blocked('no-test-action',()=>{},'TRACE_REQUIRED_PLAYWRIGHT_CONTENT_INVALID')
 makeZip('no-browser')
 blocked('no-browser-trace',()=>{},'TRACE_REQUIRED_PLAYWRIGHT_CONTENT_INVALID')
 makeZip()
 const bytes=readFileSync(traceZip);const altered=Buffer.from(bytes);altered[12]^=0x01
 writeFileSync(traceZip,altered)
 blocked('tampered-zip-bytes',x=>{x.manifest.tests[0].traceSha256=digest(bytes)},'ACTUAL_TRACE_ZIP_SHA256_MISMATCH')
 makeZip()
 blocked('fake-attachment-path',x=>{x.report.suites[0].specs[0].tests[0].results[0].attachments[0].path='/tmp/faked.zip'},'PLAYWRIGHT_JSON_TRACE_ATTACHMENT_PATH_UNTRUSTED')
 blocked('wrong-original-to-copy-mapping',x=>{x.manifest.tests[0].attachmentOriginalPath='wrong/trace.zip'},'PLAYWRIGHT_JSON_ATTACHMENT_PATH_MAPPING_MISMATCH')
 writeFileSync(originalZip,Buffer.from('corruption'))
 blocked('source-attachment-differs-from-trace-copy',()=>{},'TRACE_NOT_ZIP_BYTES')
 makeZip()
 blocked('wrong-test-status',x=>{x.report.suites[0].specs[0].tests[0].results[0].status='failed'},'PLAYWRIGHT_JSON_NOT_TRULY_PASSED')
 blocked('skipped-test',x=>{x.report.suites[0].specs[0].tests[0].status='skipped'},'PLAYWRIGHT_JSON_NOT_TRULY_PASSED')
 blocked('duplicate-test-id',x=>{x.report.suites[0].specs.push(structuredClone(x.report.suites[0].specs[0]))},'DUPLICATE_PLAYWRIGHT_TEST_ID')
 blocked('duplicate-trace',x=>{x.manifest.tests.push(structuredClone(x.manifest.tests[0]))},'DUPLICATE_TRACE_TEST_ID')
 blocked('unknown-id',x=>{x.acceptedIds=['RUX-99']},'ACCEPTED_ID_UNKNOWN_TO_PLAYWRIGHT')
 blocked('missing-trace-manifest',x=>{x.manifest.tests=[]},'ACCEPTED_ID_MISSING_ACTUAL_TRACE_ZIP')
 blocked('wrong-run-id',x=>{x.report.config.metadata.githubRunId='999'},'PLAYWRIGHT_JSON_CI_RUN_JOB_IDENTITY_MISMATCH')
 blocked('wrong-run-attempt',x=>{x.manifest.tests[0].runAttempt='99'},'TRACE_RUN_JOB_PROVENANCE_MISMATCH')
 blocked('missing-json-attachment',x=>{x.report.suites[0].specs[0].tests[0].results[0].attachments=[]},'PLAYWRIGHT_JSON_TRACE_ATTACHMENT_MISSING_OR_DUPLICATE')
 blocked('diag-cannot-count-as-send',x=>{x.acceptedIds=['DIAG-COMPOSER-01']},'DIAGNOSTIC_OR_UNPROVEN_SEND_NOT_ACCEPTABLE')
 blocked('formal-send-not-evidenced',x=>{x.acceptedIds=['GF-INTENT-15']},'DIAGNOSTIC_OR_UNPROVEN_SEND_NOT_ACCEPTABLE')
 const missingProof=make()
 unlinkSync(traceZip)
 assert.throws(()=>verifyArtifactBundle(missingProof),e=>e.message.includes('ENOENT'),'physical ZIP absent must fail')
 negatives++;console.log('TRACE_NEGATIVE_BLOCKED physical-trace-zip-missing')
 console.log('TRACE_ADVERSARIAL_SUITE_COMPLETE negatives='+negatives+' SELFTEST_ONLY_NO_NATIVE_PASS')
}finally{rmSync(dir,{recursive:true,force:true})}
