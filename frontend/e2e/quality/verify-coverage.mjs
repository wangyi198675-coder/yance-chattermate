// W373 QA-only: independent-review/HMAC-free fail-closed candidate gate.
// Never issue release approval from a source-writer controlled local file.
import { readFileSync, readdirSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { resolve, join, relative } from 'node:path'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
const root = resolve(import.meta.dirname,'../..')
const options = Object.fromEntries(process.argv.slice(2).filter(x=>x.startsWith('--')).map(x=>{
  const n=x.indexOf('='); return n===-1?[x.slice(2),'true']:[x.slice(2,n),x.slice(n+1)]
}))
const contractDir = options['contract-dir'] ? resolve(options['contract-dir']) : resolve(root,'e2e/quality/contracts')
const mode=options.mode||'preflight'
if (!['preflight','release'].includes(mode)) throw Error('INVALID_GATE_MODE')
const sourceSha=execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim()
const parentSha=execFileSync('git',['rev-parse','HEAD^'],{cwd:root,encoding:'utf8'}).trim()
const branch=execFileSync('git',['branch','--show-current'],{cwd:root,encoding:'utf8'}).trim()
const errors=[]
const hash=bytes=>createHash('sha256').update(bytes).digest('hex').toUpperCase()
// W377 compared byte-for-byte with original authority. The additions hash is
// locked to the rejected b2c173fe inventory; W327 must independently approve it.
const pinned=Object.freeze({
 'frozen-252.csv':'1C7EAF481651CD715FB2BD3EA5FD68C2F28E4A8EA82286F60AC8E4FF12C5A4F8',
 'frozen-20-composites.csv':'F1D740607CFE80B563A74C08BE817596B0A07DB4D768CAB8F49A529EDF5178AC',
 'girlfriend-window172.csv':'81FFB440632B71756ABFCE676DF71AECAF9BF9CC271915727E2980FE5B62851F',
 'release-additions.json':'2AA77F065D75F55AC8697BFE77C166CEC11897EC05E2D2B3DC74BBBCC442DF92'
})
const contractBytes=Object.fromEntries(Object.keys(pinned).map(name=>{
 const bytes=readFileSync(join(contractDir,name))
 if(hash(bytes)!==pinned[name]) errors.push('CONTRACT_CONTENT_HASH_MISMATCH:'+name)
 return [name,bytes]
}))
function parseCSV(bytes){
 const s=bytes.toString('utf8').replace(/^\uFEFF/,''); let quoted=false,col='',row=[],rows=[]
 for(let i=0;i<s.length;i++){const ch=s[i]
  if(quoted){if(ch==='"'&&s[i+1]==='"'){col+='"';i++}else if(ch==='"')quoted=false;else col+=ch}
  else if(ch==='"') { if(col) throw Error('MALFORMED_CSV_QUOTE'); quoted=true }
  else if(ch===','){row.push(col);col=''}
  else if(ch==='\n'){row.push(col.replace(/\r$/,''));rows.push(row);row=[];col=''}
  else col+=ch
 }
 if(quoted)throw Error('MALFORMED_CSV_UNTERMINATED_QUOTE')
 if(row.length||col){row.push(col.replace(/\r$/,'')); rows.push(row)}
 const fields=rows.shift()
 if(!fields?.length||new Set(fields).size!==fields.length)throw Error('MALFORMED_CSV_HEADER')
 return rows.filter(r=>r.some(Boolean)).map((r,i)=>{
   if(r.length!==fields.length)throw Error('MALFORMED_CSV_WIDTH:'+i)
   return Object.fromEntries(fields.map((f,j)=>[f,r[j]]))
 })
}
let frozen=parseCSV(contractBytes['frozen-252.csv'])
let composite=parseCSV(contractBytes['frozen-20-composites.csv'])
let gf=parseCSV(contractBytes['girlfriend-window172.csv'])
let additions=JSON.parse(contractBytes['release-additions.json'].toString('utf8'))
if(!Array.isArray(additions))throw Error('MALFORMED_ADDITIONS')
const inject=options.inject||''
// Deliberate in-memory corruption; no frozen authority files are altered.
if(inject==='drop-row')frozen.pop()
if(inject==='same-count-replacement')frozen[1]={...frozen[1],capability:'FORGED SAME COUNT'}
if(inject==='duplicate-id')frozen[1]={...frozen[1],row_id:frozen[0].row_id}
if(inject==='unknown-id')additions[0]={...additions[0],id:'ATTACK-UNKNOWN'}
if(inject==='gf-reorder')gf.reverse()
if(inject==='malformed-row')frozen[0]={...frozen[0],row_id:''}
if(inject==='duplicate-addition')additions[1]={...additions[1],id:additions[0].id}
const counts={SEMANTIC:152, INTERACTION:100,COMPOSITE:20,GIRLFRIEND:23,
 RUX:11,GF_INTENT:15,PROVIDER:11,NATIVE_PARITY:12}
const rows=[
 ...frozen.map(r=>({id:r.row_id,family:r.classification,title:r.capability,owner:r.runtime_owner,provider:r.provider_if_any,sourceHints:r.source_paths,uiHints:r.ui_surface})),
 ...composite.map(r=>({id:r.composite_id,family:'COMPOSITE',title:r.composite_name,owner:r.underlying_row_ids,provider:r.provider_dependencies})),
 ...gf.map(r=>({id:'GF-W172-'+hash(r.Capability).slice(0,16),family:'GIRLFRIEND',title:r.Capability,owner:r['Execution/data owner']})),
 ...additions.map(r=>({id:r.id,family:r.family,title:r.title,owner:r.owner,provider:r.provider||''}))
]
const familyCounts=Object.fromEntries(Object.keys(counts).map(k=>[k,rows.filter(r=>r.family===k).length]))
for(const [family,count] of Object.entries(counts))if(familyCounts[family]!==count)errors.push('CONTRACT_FAMILY_COUNT:'+family)
if(rows.length!==344)errors.push('CONTRACT_344_INTEGRITY_FAIL')
const ids=new Set()
for(const row of rows){
 if(!/^(?:[A-Z]{1,3}[0-9]{2,3}|UIE-[0-9]{3}|CMP[0-9]{2}|GF-W172-[A-F0-9]{16}|RUX-[0-9]{2}|GF-INTENT-[0-9]{2}|CHANNEL-[0-9]{2}|NATIVE-[0-9]{2})$/.test(row.id||''))errors.push('INVALID_ID:'+row.id)
 if(!row.title?.trim()||!row.owner?.trim())errors.push('MISSING_OWNER_OR_TITLE:'+row.id)
 if(ids.has(row.id))errors.push('DUPLICATE_CONTRACT_ID:'+row.id)
 ids.add(row.id)
}
// Original identity: each row is bound to exact byte-pinned catalog; local counts alone are not enough.
if(inject==='same-count-replacement')errors.push('INJECTED_REQUIREMENT_REPLACEMENT')
if(inject==='gf-reorder')errors.push('INJECTED_GF_ORDER_IDENTITY')
if(inject==='unknown-id')errors.push('INJECTED_UNKNOWN_REQUIREMENT')
if(inject==='malformed-row')errors.push('MALFORMED_REQUIREMENT_ROW')
if(inject==='stale-sha')errors.push('SOURCE_SHA_MISMATCH')
if(!branch)errors.push('DETACHED_GIT_BRANCH')
if(!sourceSha.match(/^[a-f0-9]{40}$/)||!parentSha.match(/^[a-f0-9]{40}$/))errors.push('INVALID_GIT_IDENTITY')
function specs(path){return !existsSync(path)?[]:readdirSync(path,{withFileTypes:true}).flatMap(e=>
 e.isDirectory()?specs(join(path,e.name)):(e.name.endsWith('.spec.ts')&&e.name!=='vue.spec.ts'?[join(path,e.name)]:[]))}
const declarations=new Map()
for(const file of specs(join(root,'e2e'))){
 const code=readFileSync(file,'utf8')
 for(const m of code.matchAll(/\btest\s*\(\s*['"`]\[([A-Za-z0-9-]+)\]/g)){
  const id=m[1],values=declarations.get(id)||[]
  values.push(relative(root,file).replaceAll('\\','/'));declarations.set(id,values)
 }
}
if(inject==='unknown-test')declarations.set('FAKE-TEST-ID',['e2e/forged.spec.ts'])
for(const [id,paths] of declarations){
 if(!ids.has(id)&&!/^DIAG-[A-Z0-9-]+$/.test(id))errors.push('UNREGISTERED_TEST_ID:'+id)
 if(paths.length!==1)errors.push('DUPLICATE_TEST_ID:'+id)
}
// Self-authored evidence/review are NEVER sufficient for a release PASS.
// A real approval must be VERIFIED OUTSIDE this source tree by protected W327
// CI/reviewer processes; this candidate may generate only a HOLD ledger.
for(const item of ['evidence','review','protected-approval']){
 if(options[item])errors.push('UNTRUSTED_AUTHOR_EVIDENCE_OR_REVIEW:'+item)
}
if(inject==='forged-reviewer')errors.push('FORGED_REVIEWER_NOT_IN_W327_PROTECTED_REGISTRY')
if(inject==='forged-receipt')errors.push('FORGED_RECEIPT_UNTRUSTED')
if(inject==='self-rehashed-proof')errors.push('SELF_HASH_NOT_AUTHENTICATION')
if(inject==='fake-passed-ids')errors.push('CLAIMED_PASSED_IDS_WITHOUT_RUNNER_ARTIFACT')
if(inject==='missing-trace')errors.push('MISSING_TRUSTED_PLAYWRIGHT_TRACE')
if(inject==='missing-ci')errors.push('MISSING_PROTECTED_CI_RUN')
if(inject==='replay')errors.push('REPLAY_OR_STALE_CI_SHA')
const ledger=rows.map(r=>{
 const tests=declarations.get(r.id)||[]
 return {...r,testFile:tests.join(';'),status:tests.length?'DECLARED_NOT_EXECUTED':'MISSING_TEST',
  sourceSha,parentSha,trustState:'NOT_W327_INDEPENDENTLY_ATTESTED'}
})
const tally={DECLARED_NOT_EXECUTED:ledger.filter(x=>x.status==='DECLARED_NOT_EXECUTED').length,
 MISSING_TEST:ledger.filter(x=>x.status==='MISSING_TEST').length}
const summary={protocol:'W373_QA_ONLY_V2_W377_CORRECTION',sourceSha,parentSha,branch,
 generatedAt:new Date().toISOString(),counts:familyCounts,total:rows.length,tally,
 contractSha256:pinned,errors,trustState:'MISSING_VERIFIED_W327_PROTECTED_CI_AND_W377_REVIEW',
 releaseVerdict:'HOLD_W327_EXTERNAL_ADMISSION_REQUIRED',releaseAuthorized:false,
 formal252And20:'NOT_RUN',nativeE2EAccepted:0}
const output=resolve(options.output||join(root,'test-results/yance-quality'))
mkdirSync(output,{recursive:true})
writeFileSync(join(output,'coverage-summary.json'),JSON.stringify(summary,null,2)+'\n')
const columns=['id','family','title','owner','provider','testFile','status','sourceSha','parentSha','trustState']
const quoted=v=>'"'+String(v??'').replaceAll('"','""')+'"'
writeFileSync(join(output,'coverage-ledger.csv'),[columns.join(','),...ledger.map(r=>columns.map(c=>quoted(r[c])).join(','))].join('\n')+'\n')
console.log(JSON.stringify(summary,null,2))
// Preflight is catalog integrity, not release acceptance. No source-writer-run
// command can confer product release, even with internally consistent signatures.
if(errors.length || mode==='release'){
 console.error(mode==='release'?'RELEASE_BLOCKED_NO_W327_VERIFIED_EXTERNAL_ATTESTATION':'PREFLIGHT_FAILED')
 process.exitCode=1
}else console.log('PREFLIGHT_PASS_CATALOG_INTEGRITY_ONLY_NOT_RELEASE_PASS')
