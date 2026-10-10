// Guard the P1-B/C/D regression assertions against accidental shrinkage.
// This is SOURCE-ONLY test quality self-check, NEVER a native E2E or business PASS.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'
const full=readFileSync(resolve(import.meta.dirname,'../native-critical.spec.ts'),'utf8')
// A diagnostic source test never discharges the GF-INTENT-15 send obligation.
const cases=[
 ['P1-D RUX05 exact archive owner and restore','[RUX-05]',[
  "session_id='${fixture.session}'",'data-session-id','data-customer-id',
  'await toggle(original)','finally{','QA archive fixture MUST be restored'
 ]],
 ['P1-B real pin owner','[RUX-10]',[
  'nativePinState(fixture.session)','await toggle(!original)','await toggle(original)',
  'finally{','QA fixture MUST be restored after test'
 ]],
 ['P1-C exact candidate value','[GF-INTENT-11]',[
  '.yance-reply-candidate__draft','toHaveValue(exactDraft)','[data-yance-adopt]'
 ]],
 ['P1-C send actor explicitly NOT_RUN','[DIAG-COMPOSER-01]',[
  'GF-INTENT-15 SEND ACK RESTART NOT_RUN','GF_INTENT_15_SEND_PERMISSION_ACK_RESTART_NOT_RUN'
 ]],
 ['P1-D canonical bilingual ID','[RUX-07]',[
  'canonicalChatDetail(page,fixture.session)','data-message-id','fixture.message',
  'sourceAttributes.yance_translation','data-yance-translated-text'
 ]],
 ['P1-D no invented facts','[RUX-08]',[
  'fromDB','fromAPI','toEqual(fromDB??null)','data-state','unknown'
 ]],
 ['P1-D switched independent sessions','[RUX-11]',[
  'canonicalContactRows()','x.customer_id!==fixture.customer','data-session-id',
  'data-yance-active-customer-id','row.chat_history_id'
 ]]
]
const sections=full.split(/(?=test\('\[[A-Za-z0-9-]+\])/g)
function errorsFor(source) {
 const parts=source.split(/(?=test\('\[[A-Za-z0-9-]+\])/g)
 return cases.flatMap(([label,id,required])=>{
  const section=parts.find(x=>x.startsWith("test('"+id))
  return !section?[label+':MISSING_TEST']:required.filter(s=>!section.includes(s)).map(s=>label+':MISSING_'+s)
 })
}
assert.deepEqual(errorsFor(full),[],'Original P1 B/C/D guard source must be present')
console.log('NATIVE_P1_SOURCE_CONTRACT_BASELINE_PASS_NOT_RUNTIME')
let negatives=0
for(const [label,id,required] of cases){
 const part=sections.find(s=>s.startsWith("test('"+id))
 assert.ok(part)
 const altered=full.replace(part,part.replaceAll(required[0],'DELETED_P1_GUARD'))
 const errs=errorsFor(altered)
 assert.ok(errs.some(s=>s.startsWith(label+':')),label+' must reject removed behavioral guard')
 negatives++;console.log('NATIVE_P1_SOURCE_NEGATIVE '+label+' blocked')
}
console.log('NATIVE_P1_SOURCE_REGRESSION_SELFTEST_PASS '+negatives+' mutation cases; NOT native E2E')
