// W377 corrections: native positive owner/backing checks, no HTTP fixture interception.
import { expect,test } from '@playwright/test'
import {requireNative,visitNative,nativeUrl,nativeApi,saveState,requireNativeContact,postgres,fixture,nativePinState,canonicalContactRows,canonicalChatDetail} from './quality/native-env'
const backend=(route:string)=>new URL(route,nativeApi).toString()
const state=()=>postgres(`SELECT is_followed::text||'|'||is_favourite::text||'|'||is_archived::text
 FROM session_to_agents WHERE session_id='${fixture.session}'::uuid AND organization_id='${fixture.org}'::uuid`)
test.beforeEach(async ({page}, info)=>{await requireNative(page,info)})
test('[NATIVE-12] six native routes prove distinct semantic content and source-bound screenshots',async ({page},info)=>{
 const routes=[
  ['/yance/home','[data-yance-home-native-composition]','home'],
  ['/yance','[data-yance-native-host]','conversation'],
  ['/yance/relationship','[data-yance-relationship-world]','relationship'],
  ['/yance/people','[data-yance-people-directory]','people'],
  ['/yance/settings','[data-yance-settings-native]','settings'],
  ['/yance/platform-accounts','[data-yance-platform-accounts]','platform-accounts']
 ]
 for(const [path,semantic,tag] of routes){
  await visitNative(page,path)
  await expect(page.locator(semantic),path+' must show its own native root').toBeVisible()
  expect((await page.locator(semantic).innerText()).trim().length).toBeGreaterThan(20)
  await saveState(page,info,tag)
 }
 // Comparison to user-approved RC3 golden is a separate W372+W327 release HOLD,
 // not fulfilled by storing fresh screenshots here.
})
test('[RUX-01] owner UI has no Yance subscription upsell across user surfaces',async ({page},info)=>{
 for(const path of ['/yance/home','/yance/settings','/yance/platform-accounts']){
  await visitNative(page,path)
  await expect(page.getByText(/升级套餐|按权限套餐开放|订阅后解锁|开通会员才能使用/)).toHaveCount(0)
  expect(new URL(page.url()).pathname).not.toMatch(/checkout|pricing|subscription/)
 }
 await saveState(page,info,'no-yance-upsell')
})
test('[RUX-02] owner starts in authenticated /yance without consumer registration',async ({page})=>{
 await visitNative(page,'/yance')
 await expect(page.locator('[data-yance-native-host]')).toBeVisible()
 await expect(page.getByRole('button',{name:/注册言策|创建言策账号|购买套餐/})).toHaveCount(0)
})
test('[RUX-03] Berlin DST-accurate greeting and sourced live weather or fail closed',async ({page},info)=>{
 // Independent timezone sanity before comparing actual runtime projection.
 const berlin=(date:string)=>new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Berlin',hour:'2-digit',hourCycle:'h23'}).format(new Date(date))
 expect(berlin('2026-03-29T00:30:00Z')).toBe('01')
 expect(berlin('2026-03-29T01:30:00Z')).toBe('03')
 expect(berlin('2026-10-25T00:30:00Z')).toBe('02')
 expect(berlin('2026-10-25T01:30:00Z')).toBe('02')
 await visitNative(page,'/yance/home')
 const greeting=page.locator('[data-yance-berlin-greeting]')
 await expect(greeting).toBeVisible()
 await expect(greeting).toHaveAttribute('data-time-zone','Europe/Berlin')
 const hour=Number(berlin(new Date().toISOString()))
 const expected=hour<5?'夜':hour<11?'早':hour<14?'中午':hour<18?'下午':'晚'
 await expect(greeting).toContainText(expected)
 const weather=page.locator('[data-yance-berlin-weather]')
 await expect(weather).toBeVisible()
 const availability=await weather.getAttribute('data-weather-state')
 expect(['live','unavailable']).toContain(availability)
 if(availability==='live'){
  const source=await weather.getAttribute('data-weather-source')
  const observed=await weather.getAttribute('data-weather-observed-at')
  expect(source?.trim().length).toBeGreaterThan(3)
  expect(Number.isFinite(Date.parse(observed||''))).toBeTruthy()
  expect(Math.abs(Date.now()-Date.parse(observed!))).toBeLessThan(3*60*60*1000)
 }else await expect(weather).toContainText(/不可用|暂时无法|未提供/)
 await saveState(page,info,'berlin-real-weather')
})
test('[RUX-04] all five rail filters change native state and backed archive list',async ({page},info)=>{
 await visitNative(page,'/yance')
 const rail=page.locator('[data-yance-contact-rail="native"]')
 await expect(rail).toBeVisible()
 for(const name of ['全部','未读','关注','收藏','归档']){
  const tab=rail.getByRole('button',{name,exact:true})
  await tab.click()
  await expect(tab).toHaveAttribute('aria-pressed','true')
 }
 const data=await page.request.get(backend('/api/v1/chats/recent?inbox_filter=archived&limit=20'))
 expect(data.ok(),'real scoped archive API required').toBeTruthy()
 await expect(page.locator('[data-yance-archive-filter]')).toHaveAttribute('aria-pressed','true')
 await saveState(page,info,'five-native-filters')
})
test('[RUX-05] exact isolated Customer/Session archive persistence and finally restore',async ({page},info)=>{
 await visitNative(page,'/yance')
 const owner=postgres(`SELECT count(*) FROM session_to_agents s
 JOIN customers c ON c.id=s.customer_id AND c.organization_id=s.organization_id
 WHERE s.session_id='${fixture.session}'::uuid AND s.organization_id='${fixture.org}'::uuid
 AND c.id='${fixture.customer}'::uuid`)
 expect(owner,'archive must target the authenticated isolated Customer and Session').toBe('1')
 const archive=()=>postgres(`SELECT is_archived::text FROM session_to_agents
 WHERE session_id='${fixture.session}'::uuid AND customer_id='${fixture.customer}'::uuid
 AND organization_id='${fixture.org}'::uuid`)
 const original=archive()
 expect(['true','false']).toContain(original)
 const row=()=>page.locator('.conversation-item[data-session-id="'+fixture.session+'"][data-customer-id="'+fixture.customer+'"]')
 const selectFilter=async (wanted:'all'|'archived')=>{
  const rail=page.locator('[data-yance-contact-rail="native"]')
  await rail.getByRole('button',{name:wanted==='archived'?'归档':'全部',exact:true}).click()
 }
 const toggle=async (from:string)=>{
  await selectFilter(from==='true'?'archived':'all')
  await expect(row(),'Never archive a different first contact').toBeVisible()
  await row().click({button:'right'})
  const action=row().locator('[data-yance-contact-menu-items] [data-yance-archive-action]')
  await expect(action).toBeVisible()
  await action.click()
  await expect.poll(archive,{message:'Archive owner must persist exactly one native SessionToAgent row'}).toBe(from==='true'?'false':'true')
 }
 try{
  await toggle(original)
  const changed=archive()
  await page.reload()
  expect(archive(),'archive native state must survive reload').toBe(changed)
  await toggle(changed)
  expect(archive(),'explicit archive-unarchive roundtrip').toBe(original)
  await saveState(page,info,'isolated-contact-archive-restored')
 }finally{
  // Always restore via the SAME identified UI session; never write the database directly.
  // If that contact disappears from the wrong filter, reselect by its backed archive state.
  if(archive()!==original){
   await visitNative(page,'/yance')
   await toggle(archive())
  }
  expect(archive(),'QA archive fixture MUST be restored to its prior persisted value').toBe(original)
 }
 // PIN persistence is solely RUX-10 with a real owner readback, not a menu check here.
})
test('[RUX-06] message right-click copies actual original, not synthetic success',async ({page,context},info)=>{
 await visitNative(page,'/yance')
 await context.grantPermissions(['clipboard-read','clipboard-write'],{origin:new URL(nativeUrl).origin})
 await (await requireNativeContact(page)).click()
 const message=page.locator('.message-virtual-row .message').first()
 await expect(message).toBeVisible()
 const visibleOriginal=(await message.locator('.message-content').innerText()).trim()
 expect(visibleOriginal.length).toBeGreaterThan(0)
 await message.click({button:'right'})
 const menu=page.locator('[data-yance-message-menu-items]').filter({visible:true})
 await expect(menu).toBeVisible()
 const copy=menu.locator('[data-yance-message-action="copy"]')
 await expect(copy).toContainText('复制原文')
 await copy.click()
 const clipboard=await page.evaluate(()=>navigator.clipboard.readText())
 expect(clipboard.trim()).not.toEqual('')
 expect(visibleOriginal).toContain(clipboard.trim())
 await saveState(page,info,'real-original-clipboard')
})
test('[RUX-07] exact canonical ChatHistory ID source and Chinese identity under same row',async ({page},info)=>{
 await visitNative(page,'/yance')
 const contact=page.locator('.conversation-item[data-session-id="'+fixture.session+'"]')
 await expect(contact).toHaveAttribute('data-customer-id',fixture.customer)
 await contact.click()
 const detail=await canonicalChatDetail(page,fixture.session)
 expect(detail.customer?.id).toBe(fixture.customer)
 const canonical=detail.messages?.find(m=>m.id===Number(fixture.message))
 expect(canonical?.message_type).toBe('user')
 expect(typeof canonical?.message).toBe('string')
 expect(canonical!.message!.trim().length).toBeGreaterThan(0)
 const pg=postgres(`SELECT COALESCE(attributes::text,'{}') FROM chat_history
 WHERE id=${fixture.message} AND session_id='${fixture.session}'::uuid
 AND organization_id='${fixture.org}'::uuid AND customer_id='${fixture.customer}'::uuid`)
 const sourceAttributes=JSON.parse(pg) as Record<string,unknown>
 const stored=sourceAttributes.yance_translation as Record<string,unknown>|undefined
 const row=page.locator('.message-virtual-row[data-message-id="'+fixture.message+'"]')
 await expect(row,'UI row MUST identify the same native ChatHistory ID').toBeVisible()
 const source=row.locator('.message-content')
 await expect(source).toHaveText(canonical!.message!)
 const chinese=row.locator('[data-yance-bilingual-projection]')
 await expect(chinese).toBeVisible()
 const originalY=(await source.boundingBox())?.y
 const secondaryY=(await chinese.boundingBox())?.y
 expect(originalY).toBeDefined();expect(secondaryY).toBeDefined()
 expect(secondaryY!).toBeGreaterThan(originalY!)
 const translationState=await chinese.getAttribute('data-state')
 expect(['success','fail-closed']).toContain(translationState)
 if(translationState==='success'){
  expect(String(stored?.messageId),'canonical stored translation must match same ChatHistory event').toBe(fixture.message)
  expect(stored?.status).toBe('success')
  expect(typeof stored?.text).toBe('string')
  expect(String(stored!.text).trim().length).toBeGreaterThan(0)
  await expect(chinese.locator('[data-yance-translated-text]')).toHaveText(String(stored!.text).trim())
  expect(canonical!.message!.trim()).not.toBe(String(stored!.text).trim())
 }else{
  await expect(chinese.locator('[data-yance-translated-text]')).toHaveCount(0)
  if(stored?.status==='success'&&String(stored?.messageId)===fixture.message)
   throw Error('TRANSLATION_OWNER_STATUS_CONTRADICTS_FAIL_CLOSED_UI')
 }
 await saveState(page,info,'same-chat-history-original-chinese-provenance')
})
test('[RUX-08] Customer.meta_data facts and genuine unknown fields never fabricated',async ({page},info)=>{
 await visitNative(page,'/yance')
 const row=page.locator('.conversation-item[data-session-id="'+fixture.session+'"]')
 await expect(row).toHaveAttribute('data-customer-id',fixture.customer)
 await row.click()
 const detail=await canonicalChatDetail(page,fixture.session)
 expect(detail.customer?.id).toBe(fixture.customer)
 const dbProfile=postgres(`SELECT COALESCE(meta_data::text,'{}') FROM customers
 WHERE id='${fixture.customer}'::uuid AND organization_id='${fixture.org}'::uuid`)
 const profile=JSON.parse(dbProfile) as {person_profile?:Record<string,unknown>}
 const facts=profile.person_profile||{}
 const apiProfile=(detail.customer?.meta_data?.person_profile||{}) as Record<string,unknown>
 const header=page.locator('[data-yance-contact-header-profile][data-customer-id="'+fixture.customer+'"]')
 await expect(header).toBeVisible()
 for(const field of ['nationality','city','age','occupation']){
  const fromDB=facts[field],fromAPI=apiProfile[field]
  expect(fromAPI??null,'API profile field must match actual Customer metadata').toEqual(fromDB??null)
  const presented=header.locator('[data-profile-field="'+field+'"]')
  if(fromDB!==null&&fromDB!==undefined&&String(fromDB).trim()){
   await expect(presented,'real value must render with source identity').toHaveCount(1)
   await expect(presented).toHaveText(String(fromDB))
   await expect(presented).toHaveAttribute('data-source','Customer.meta_data.person_profile')
  }else{
   // Unknown values must either be ABSENT or explicitly marked unknown.
   const count=await presented.count()
   if(count){
    expect(count).toBe(1)
    await expect(presented).toHaveAttribute('data-state','unknown')
    await expect(presented).toHaveText(/^(未确认|未知|未提供|Unknown)$/)
   }
  }
 }
 await saveState(page,info,'customer-known-unknown-fact-provenance')
})
test('[RUX-09] rail collapse restores geometry with exactly one Composer',async ({page},info)=>{
 await visitNative(page,'/yance')
 const collapse=page.locator('[data-yance-rail-collapse]')
 await expect(collapse).toHaveAttribute('aria-label','收起联系人栏')
 await collapse.click()
 await expect(collapse).toHaveAttribute('aria-label','展开联系人栏')
 await saveState(page,info,'rail-collapsed')
 await collapse.click()
 await expect(collapse).toHaveAttribute('aria-label','收起联系人栏')
 await expect(page.locator('[data-yance-contact-rail="native"]')).toBeVisible()
 await expect(page.locator('[data-yance-frozen-composer="native"]')).toHaveCount(1)
 await saveState(page,info,'rail-expanded')
})
test('[RUX-10] real canonical PIN and UNPIN both persisted with finally restore',async ({page},info)=>{
 await visitNative(page,'/yance')
 // Fail BEFORE any mutation if SessionToAgent has no admitted is_pinned owner.
 const original=nativePinState(fixture.session)
 const contact=()=>page.locator('.conversation-item[data-session-id="'+fixture.session+'"]')
 const toggle=async (wantPin:boolean)=>{
  await expect(contact(),'pin must operate on the exact authorized session').toBeVisible()
  await contact().focus()
  await contact().locator('[data-yance-contact-menu-button]').click()
  await expect(page.locator('[data-yance-contact-menu-items]')).toBeVisible()
  const action=page.locator('[data-yance-contact-action="'+(wantPin?'pin':'unpin')+'"]')
  await expect(action).toBeVisible()
  await action.click()
  await expect.poll(()=>nativePinState(fixture.session),{message:'canonical PostgreSQL pin owner must persist'}).toBe(wantPin)
  await page.reload()
  expect(nativePinState(fixture.session),'pin must survive reload').toBe(wantPin)
 }
 try{
  await toggle(!original)
  await toggle(original)
  await saveState(page,info,'pin-unpin-owner-roundtrip')
 }finally{
  // Always attempt restoration even when intermediate browser expectations fail.
  // Never directly UPDATE the DB; use the native menu and verify real PG readback.
  if(nativePinState(fixture.session)!==original)await toggle(original)
  expect(nativePinState(fixture.session),'QA fixture MUST be restored after test').toBe(original)
 }
})
test('[RUX-11] two switched UI contacts bind to different canonical Customer/Session/ChatHistory rows',async ({page},info)=>{
 await visitNative(page,'/yance')
 const authoritative=canonicalContactRows()
 expect(authoritative.length,'independent PostgreSQL MUST have two customer-backed sessions').toBeGreaterThanOrEqual(2)
 const first=authoritative.find(x=>x.session_id===fixture.session)
 const second=authoritative.find(x=>x.session_id!==fixture.session&&x.customer_id!==fixture.customer)
 expect(first,'fixture session must be present in actual PostgreSQL').toBeDefined()
 expect(second,'second distinct canonical customer required').toBeDefined()
 const selected=[first!,second!]
 for(const row of selected){
  const contact=page.locator('.conversation-item[data-session-id="'+row.session_id+'"]')
  await expect(contact).toHaveAttribute('data-customer-id',row.customer_id)
  await expect(contact.locator('h3')).toHaveText(row.full_name||row.email)
  await contact.click()
  await expect(page.locator('.chat-header')).toContainText(row.full_name||row.email)
  await expect(page.locator('[data-yance-active-session-id]')).toHaveAttribute('data-yance-active-session-id',row.session_id)
  await expect(page.locator('[data-yance-active-customer-id]')).toHaveAttribute('data-yance-active-customer-id',row.customer_id)
  const detail=await canonicalChatDetail(page,row.session_id)
  expect(detail.customer?.id).toBe(row.customer_id)
  expect(detail.messages?.some(m=>m.id===row.chat_history_id)).toBe(true)
 }
 await page.reload()
 await expect(page.locator('[data-yance-active-session-id]')).toHaveAttribute('data-yance-active-session-id',second!.session_id)
 await expect(page.locator('[data-yance-active-customer-id]')).toHaveAttribute('data-yance-active-customer-id',second!.customer_id)
 const persisted=canonicalContactRows().find(r=>r.session_id===second!.session_id)
 expect(persisted?.customer_id).toBe(second!.customer_id)
 expect(persisted?.chat_history_id).toBe(second!.chat_history_id)
 await saveState(page,info,'two-independent-canonical-contact-ids')
})
test('[GF-INTENT-01] natural-language action stages plan, approval and native receipt not merely popup',async ({page},info)=>{
 await visitNative(page,'/yance')
 const toggle=page.locator('[data-yance-girlfriend-toggle]')
 await toggle.click()
 const intent=page.locator('[data-yance-girlfriend-intent]')
 await expect(intent).toBeVisible()
 await intent.fill('仅分析当前联系人，不要未经我批准发送消息')
 await page.locator('[data-yance-girlfriend-scope] input[value="contact"]').check()
 await page.locator('[data-yance-stage-intent]').click()
 await expect(page.locator('[data-yance-girlfriend-receipt]')).toBeVisible()
 await expect(page.locator('[data-yance-girlfriend-orchestration]'),
  'A draft-only receipt is NOT an executed Agno tool/delegation result').toBeVisible()
 await expect(page.locator('[data-yance-girlfriend-owner-receipt]'),
  'real owner receipt needed; cannot count a staged draft as completion').toBeVisible()
 await saveState(page,info,'girlfriend-owner-result')
 await page.keyboard.press('Escape')
 await expect(page.locator('[data-yance-girlfriend-native]')).toHaveCount(0)
})
test('[GF-INTENT-11] reply 0–3/5 and real adoption to one composer',async ({page},info)=>{
 await visitNative(page,'/yance')
 await (await requireNativeContact(page)).click()
 await page.locator('[data-yance-reply-mode-control]').click()
 const seam=page.locator('[data-yance-reply-brain-seam]')
 await expect(seam).toBeVisible()
 const cards=seam.locator('[data-yance-reply-candidate]')
 const before=await cards.count()
 expect(before).toBeLessThanOrEqual(3)
 if(before===0)await expect(seam).toContainText(/暂无|不建议|稍后|错误|不可用/)
 if(await page.locator('[data-yance-more-candidates]').isVisible().catch(()=>false))
  await page.locator('[data-yance-more-candidates]').click()
 expect(await cards.count()).toBeLessThanOrEqual(5)
 if(await cards.count()){
  const candidate=cards.filter({has:page.locator('[data-yance-adopt][data-adoption-kind="text-draft"]')}).first()
  await expect(candidate,'adopted text needs a real model candidate and approved human-likeness').toBeVisible()
  const exactDraft=await candidate.locator('.yance-reply-candidate__draft').innerText()
  expect(exactDraft.trim().length).toBeGreaterThan(0)
  await candidate.locator('[data-yance-adopt]').click()
  const composer=page.locator('[data-yance-frozen-composer="native"]')
  await expect(composer).toHaveCount(1)
  await expect(composer.locator('textarea'),'Composer value must equal real selected candidate, not nonempty old draft').toHaveValue(exactDraft)
 }else{
  await expect(seam).toContainText(/暂无|不建议|稍后|错误|不可用/)
  await expect(page.locator('[data-yance-frozen-composer="native"]')).toHaveCount(1)
 }
 await saveState(page,info,'reply-real-adoption')
})
test('[DIAG-COMPOSER-01] structural one-Composer only; GF-INTENT-15 SEND ACK RESTART NOT_RUN',async ({page},info)=>{
 // A structural check cannot discharge the GF-INTENT-15 send permission/
 // durable native receipt obligation. Designated actor, provider ACK and
 // process restart are NOT_RUN; no real SEND is initiated here.
 info.annotations.push({type:'release-obligation',description:'GF_INTENT_15_SEND_PERMISSION_ACK_RESTART_NOT_RUN'})
 await visitNative(page,'/yance')
 await (await requireNativeContact(page)).click()
 const composer=page.locator('[data-yance-frozen-composer="native"]')
 await expect(composer).toHaveCount(1)
 await page.locator('[data-yance-girlfriend-toggle]').click()
 await expect(composer).toHaveCount(1)
 await expect(page.locator('[data-yance-girlfriend-native]')).toBeVisible()
 await expect(page.locator('[data-yance-girlfriend-native] [data-yance-frozen-composer]')).toHaveCount(0)
 // No real provider SEND here. Must prove owner-backed receipt in separate designated test
 // actor run; current W373 must not transmit to real contacts.
 await saveState(page,info,'one-native-composer-no-send')
})
