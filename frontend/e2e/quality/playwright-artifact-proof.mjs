// W373 QA-only: compare independently downloaded Playwright JSON to ACTUAL trace ZIP bytes.
// Exports a pure verifier for adversarial tests. No reviewer receipt is created here.
import { readFileSync, lstatSync, realpathSync } from 'node:fs'
import { join, resolve, relative, sep } from 'node:path'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
export const digest = bytes => createHash('sha256').update(bytes).digest('hex').toUpperCase()
const insist=(condition,code)=>{if(!condition)throw Error(code)}
const idPattern=/^[A-Za-z0-9-]+$/
function readZip(artifactRoot, tracePath, id) {
 insist(typeof tracePath==='string'&&/^(?:traces|playwright-artifacts)\/[A-Za-z0-9_.\/-]+\.zip$/.test(tracePath),'UNSAFE_TRACE_RELATIVE_PATH')
 const root=realpathSync(artifactRoot)
 const segments=tracePath.split('/')
 let walk=root
 for(const segment of segments){
  insist(segment!=='.'&&segment!=='..','TRACE_TRAVERSAL')
  walk=join(walk,segment)
  insist(!lstatSync(walk).isSymbolicLink(),'TRACE_SYMLINK_FORBIDDEN')
 }
 const actual=realpathSync(walk)
 const pathFromRoot=relative(root,actual)
 insist(pathFromRoot&& !pathFromRoot.startsWith('..'+sep)&&pathFromRoot!=='..'&&!pathFromRoot.startsWith(sep),'TRACE_OUTSIDE_INDEPENDENT_ARTIFACT_ROOT')
 const bytes=readFileSync(actual)
 insist(bytes.length>=22&&bytes[0]===0x50&&bytes[1]===0x4b,'TRACE_NOT_ZIP_BYTES')
 const py=process.env.YANCE_QA_PYTHON||'python'
 try {execFileSync(py,[fileURLToPath(new URL('./playwright-zip-check.py',import.meta.url)),actual,id],{encoding:'utf8',timeout:8000,windowsHide:true,stdio:['ignore','pipe','pipe']})}
 catch(e){throw Error('TRACE_REQUIRED_PLAYWRIGHT_CONTENT_INVALID:'+id+':'+String(e.stderr||e.message).slice(0,350))}
 return bytes
}
const suiteSpecs=(suites,acc=[])=>{
 for(const suite of suites||[]){
  acc.push(...(suite.specs||[]))
  suiteSpecs(suite.suites,acc)
 }
 return acc
}
// Original attachments are separately downloaded under sourceArtifactRoot/playwright-artifacts.
// Never trust only the manifest copy: require both real archive bytes to match.
export function verifyArtifactBundle({report,manifest,artifactRoot,sourceArtifactRoot=artifactRoot,acceptedIds,sourceSha,run}) {
 insist(report?.config?.metadata?.sourceSha===sourceSha,'PLAYWRIGHT_JSON_SOURCE_SHA_MISMATCH')
 const ctx=report.config.metadata
 insist(String(ctx.githubRunId)===String(run.runId)&&String(ctx.githubJob)===String(run.jobName||'native-chromium')
   &&String(ctx.githubRepositoryId)===String(run.repositoryId)
   &&String(ctx.githubRunAttempt)===String(run.runAttempt),'PLAYWRIGHT_JSON_CI_RUN_JOB_IDENTITY_MISMATCH')
 insist(manifest?.sourceSha===sourceSha,'TRACE_MANIFEST_SOURCE_SHA_MISMATCH')
 for(const [field,value] of [['runId',run.runId],['job',run.jobName||'native-chromium'],['jobId','W327_GITHUB_API_LOOKUP_REQUIRED'],
 ['repositoryId',run.repositoryId],['runAttempt',run.runAttempt]]){
  insist(String(manifest[field])===String(value),'TRACE_MANIFEST_CI_IDENTITY_MISMATCH:'+field)
 }
 insist(Array.isArray(acceptedIds)&&acceptedIds.length>0&&acceptedIds.every(x=>typeof x==='string'&&idPattern.test(x))
   &&new Set(acceptedIds).size===acceptedIds.length&&acceptedIds.every(id=>!id.startsWith('DIAG-')&&id!=='GF-INTENT-15'),'DIAGNOSTIC_OR_UNPROVEN_SEND_NOT_ACCEPTABLE')
 const records=new Map()
 for(const spec of suiteSpecs(report.suites)){
  const match=/^\[([A-Za-z0-9-]+)\]/.exec(spec.title||'')
  if(!match)continue
  const id=match[1]
  insist(!records.has(id),'DUPLICATE_PLAYWRIGHT_TEST_ID:'+id)
  const tests=spec.tests||[]
  insist(tests.length===1,'DUPLICATE_PLAYWRIGHT_EXECUTION:'+id)
  const test=tests[0]
  insist(test.projectName==='chromium-native','SYNTHETIC_OR_OTHER_PROJECT:'+id)
  records.set(id,{spec,test})
 }
 insist(Array.isArray(manifest.tests),'MISSING_TRACE_MANIFEST_TEST_ROWS')
 const traces=new Map()
 const paths=new Set()
 for(const entry of manifest.tests){
  insist(entry&&typeof entry.id==='string'&&idPattern.test(entry.id),'INVALID_TRACE_TEST_ID')
  insist(!traces.has(entry.id),'DUPLICATE_TRACE_TEST_ID:'+entry.id)
  insist(records.has(entry.id),'TRACE_UNKNOWN_PLAYWRIGHT_TEST_ID:'+entry.id)
  insist(entry.sourceSha===sourceSha&&entry.status==='passed'&&entry.projectName==='chromium-native',
   'TRACE_NOT_CURRENT_SHA_NATIVE_PASSED:'+entry.id)
  insist(String(entry.runId)===String(run.runId)&&entry.jobId==='W327_GITHUB_API_LOOKUP_REQUIRED'
   &&String(entry.repositoryId)===String(run.repositoryId)&&String(entry.runAttempt)===String(run.runAttempt),
   'TRACE_RUN_JOB_PROVENANCE_MISMATCH:'+entry.id)
  insist(entry.tracePath==='traces/'+entry.id+'.zip'&&!paths.has(entry.tracePath),
   'TRACE_PATH_ID_MISMATCH_OR_COLLISION:'+entry.id)
  paths.add(entry.tracePath)
  const bytes=readZip(artifactRoot,entry.tracePath,entry.id)
  insist(/^[A-Fa-f0-9]{64}$/.test(entry.traceSha256||'')&&digest(bytes)===entry.traceSha256.toUpperCase(),
   'ACTUAL_TRACE_ZIP_SHA256_MISMATCH:'+entry.id)
  const t=records.get(entry.id).test
  insist(t.status==='expected'&&t.results?.length===1&&t.results[0].status==='passed',
   'PLAYWRIGHT_JSON_NOT_TRULY_PASSED:'+entry.id)
  const attachment=(t.results[0].attachments||[]).filter(a=>a.name==='trace')
  insist(attachment.length===1&&typeof attachment[0].path==='string',
   'PLAYWRIGHT_JSON_TRACE_ATTACHMENT_MISSING_OR_DUPLICATE:'+entry.id)
  const raw=attachment[0].path.replace(/\\/g,'/')
  const marker='/test-results/playwright-artifacts/'
  const ix=raw.toLowerCase().lastIndexOf(marker)
  insist(ix>=0,'PLAYWRIGHT_JSON_TRACE_ATTACHMENT_PATH_UNTRUSTED:'+entry.id)
  const rel=raw.slice(ix+marker.length)
  insist(rel.endsWith('/trace.zip')&&!rel.split('/').some(p=>!p||p==='.'||p==='..'||!/^[-._A-Za-z0-9]+$/.test(p)),
   'PLAYWRIGHT_JSON_TRACE_ATTACHMENT_PATH_UNTRUSTED:'+entry.id)
  const sourcePath='playwright-artifacts/'+rel
  const evidenceOriginal=readZip(sourceArtifactRoot,sourcePath,entry.id)
  insist(digest(evidenceOriginal)===digest(bytes),'PLAYWRIGHT_ATTACHMENT_AND_TRACE_COPY_MISMATCH:'+entry.id)
  insist(entry.attachmentOriginalPath===rel,'PLAYWRIGHT_JSON_ATTACHMENT_PATH_MAPPING_MISMATCH:'+entry.id)
  traces.set(entry.id,entry)
 }
 for(const id of acceptedIds){
  insist(records.has(id),'ACCEPTED_ID_UNKNOWN_TO_PLAYWRIGHT:'+id)
  insist(traces.has(id),'ACCEPTED_ID_MISSING_ACTUAL_TRACE_ZIP:'+id)
  const t=records.get(id).test
  insist(t.status==='expected'&&t.results?.length===1&&t.results[0].status==='passed',
   'ACCEPTED_ID_FAIL_SKIP_OR_FAKE:'+id)
 }
 // No successful native spec can exist outside the trace manifest.
 for(const [id,{test}] of records){
  if(test.status==='expected'&&test.results?.some(r=>r.status==='passed'))
   insist(traces.has(id),'NATIVE_PASS_WITHOUT_TRACE:'+id)
 }
 return {verifiedIds:acceptedIds.slice(),actualZipCount:traces.size,sourceSha,runId:String(run.runId),jobId:String(run.jobId)}
}
