// Self-tests prove negative paths genuinely nonzero. No provider/production interaction.
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, readFileSync, writeFileSync, copyFileSync, mkdirSync } from 'node:fs'
import { join,resolve } from 'node:path'
import { tmpdir } from 'node:os'
import assert from 'node:assert/strict'
const root=resolve(import.meta.dirname,'../..')
const temporary=mkdtempSync(join(tmpdir(),'w373-w377-adversarial-'))
const invoke=(name,args,expected,marker)=>{
 const r=spawnSync(process.execPath,['e2e/quality/verify-coverage.mjs',...args,
  '--output='+join(temporary,'out-'+name)],{cwd:root,encoding:'utf8'})
 const out=r.stdout+r.stderr
 assert.equal(r.status,expected,name+' exit mismatch\n'+out)
 assert.ok(out.includes(marker),name+' missing expected diagnosis\n'+out)
 console.log('W377_NEGATIVE_VERIFIED '+name+' exit='+r.status)
}
try {
 invoke('clean-catalog',['--mode=preflight'],0,'PREFLIGHT_PASS_CATALOG_INTEGRITY_ONLY')
 const scenarios=[
 ['drop-row','CONTRACT_FAMILY_COUNT:INTERACTION'],
 ['stale-sha','SOURCE_SHA_MISMATCH'],
 ['same-count-replacement','INJECTED_REQUIREMENT_REPLACEMENT'],
 ['duplicate-id','DUPLICATE_CONTRACT_ID'],
 ['unknown-id','INJECTED_UNKNOWN_REQUIREMENT'],
 ['gf-reorder','INJECTED_GF_ORDER_IDENTITY'],
 ['duplicate-addition','DUPLICATE_CONTRACT_ID'],
 ['malformed-row','MALFORMED_REQUIREMENT_ROW'],
 ['unknown-test','UNREGISTERED_TEST_ID'],
 ['forged-reviewer','FORGED_REVIEWER_NOT_IN_W327_PROTECTED_REGISTRY'],
 ['forged-receipt','FORGED_RECEIPT_UNTRUSTED'],
 ['self-rehashed-proof','SELF_HASH_NOT_AUTHENTICATION'],
 ['fake-passed-ids','CLAIMED_PASSED_IDS_WITHOUT_RUNNER_ARTIFACT'],
 ['missing-trace','MISSING_TRUSTED_PLAYWRIGHT_TRACE'],
 ['missing-ci','MISSING_PROTECTED_CI_RUN'],
 ['replay','REPLAY_OR_STALE_CI_SHA']
 ]
 for (const [name,marker] of scenarios)invoke(name,['--mode=preflight','--inject='+name],1,marker)
 // Real content modifications, not just the simulated corruption switches.
 const catalog=join(temporary,'tampered');mkdirSync(catalog)
 const base=join(root,'e2e/quality/contracts')
 for(const name of ['frozen-252.csv','frozen-20-composites.csv','girlfriend-window172.csv','release-additions.json']){
  copyFileSync(join(base,name),join(catalog,name))
 }
 const substitute=(name,before,after)=>{
  const dest=join(catalog,name),s=readFileSync(dest,'utf8')
  assert.ok(s.includes(before));writeFileSync(dest,s.replace(before,after))
 }
 substitute('frozen-252.csv','HUMAN','ALIEN')
 invoke('tamper-same-row-count',['--mode=preflight','--contract-dir='+catalog],1,'CONTRACT_CONTENT_HASH_MISMATCH:frozen-252.csv')
 copyFileSync(join(base,'frozen-252.csv'),join(catalog,'frozen-252.csv'))
 substitute('release-additions.json','No owner-facing plans','Faked owner-facing plans')
 invoke('tamper-49-additions',['--mode=preflight','--contract-dir='+catalog],1,'CONTRACT_CONTENT_HASH_MISMATCH:release-additions.json')
 copyFileSync(join(base,'release-additions.json'),join(catalog,'release-additions.json'))
 const csv=join(catalog,'girlfriend-window172.csv')
 writeFileSync(csv,readFileSync(csv,'utf8').replace('OFF default,','\"BROKEN,'))
 invoke('tamper-malformed-csv',['--mode=preflight','--contract-dir='+catalog],1,'MALFORMED_CSV')
 // External JSON from source-writer must never become approved, even with recomputed sha.
 const forged=join(temporary,'self-approved.json')
 writeFileSync(forged,JSON.stringify({reviewer:'W377',authorityReceipt:'SELF-AUTHORED',
  sourceSha:'FAKE',acceptedTestIds:['RUX-01'],passedTestIds:['RUX-01'],evidenceSha256:'FAKE'}))
 invoke('self-authored-approval',['--mode=release','--review='+forged,'--evidence='+forged],1,'RELEASE_BLOCKED_NO_W327_VERIFIED_EXTERNAL_ATTESTATION')
 invoke('no-protected-ci-release',['--mode=release'],1,'RELEASE_BLOCKED_NO_W327_VERIFIED_EXTERNAL_ATTESTATION')
 for(const [scenario,marker] of [['remove-runner','CI_SOURCE_CONTRACT_MISSING:NATIVE_RUNNER_LABEL'],['remove-branch','CI_SOURCE_CONTRACT_MISSING:CURRENT_C3_BRANCH']]){
  const outcome=spawnSync(process.execPath,['e2e/quality/ci-workflow-contract.mjs','--inject='+scenario],{cwd:root,encoding:'utf8'})
  assert.equal(outcome.status,1,scenario+' must fail')
  assert.ok((outcome.stdout+outcome.stderr).includes(marker),scenario+' missing blocker')
  console.log('W377_NEGATIVE_VERIFIED ci-'+scenario+' exit=1')
 }
 console.log('W377_NEGATIVE_SUITE_COMPLETE tested='+String(1+scenarios.length+7))
} finally {rmSync(temporary,{recursive:true,force:true})}
