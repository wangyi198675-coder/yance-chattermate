// Native QA guard. No fixtures are created, no real user/provider mutations.
import { expect, type Page, type TestInfo } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve, isAbsolute } from 'node:path'
import { existsSync, readFileSync } from 'node:fs'
export const nativeUrl=process.env.YANCE_QA_NATIVE_URL||''
export const nativeApi=process.env.YANCE_QA_NATIVE_API_URL||''
export const fixture={
 org:process.env.YANCE_QA_ORG_ID||'',user:process.env.YANCE_QA_USER_ID||'',
 customer:process.env.YANCE_QA_CUSTOMER_ID||'',session:process.env.YANCE_QA_SESSION_ID||'',
 message:process.env.YANCE_QA_MESSAGE_ID||''
}
const isUuid=(s:string)=>/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)
function checkLoopback(url:string){
 const u=new URL(url)
 if(!['http:','https:'].includes(u.protocol)||!['127.0.0.1','localhost','[::1]'].includes(u.hostname)
   ||u.username||u.password)throw Error('QA_LOOPBACK_ONLY: no real provider or production host')
}
export function postgres(query:string):string {
 const executable=process.env.YANCE_QA_PSQL_EXE||''
 const serviceFile=process.env.YANCE_QA_PGSERVICEFILE||''
 const service=process.env.YANCE_QA_PGSERVICE||''
 if(!isAbsolute(executable)||!existsSync(executable)||!isAbsolute(serviceFile)||!existsSync(serviceFile)||!service)
  throw Error('NATIVE_PG_CLIENT_AND_PRIVATE_SERVICE_REQUIRED')
 try {
  return execFileSync(executable,['--no-psqlrc','--tuples-only','--no-align','--set=ON_ERROR_STOP=1',
   '-c',query],{encoding:'utf8',timeout:7000,windowsHide:true,env:{
    ...process.env,PGSERVICEFILE:serviceFile,PGSERVICE:service,
    PGOPTIONS:'-c default_transaction_read_only=on -c statement_timeout=5000'
   }}).trim()
 }catch{throw Error('NATIVE_POSTGRES_QUERY_FAILED_OR_NOT_AVAILABLE')}
}
export function nativePgSnapshot(){
 if(!Object.values(fixture).every(Boolean)||![fixture.org,fixture.user,fixture.customer,fixture.session].every(isUuid)
   ||!/^\d{1,12}$/.test(fixture.message))
  throw Error('NATIVE_QA_CANONICAL_ORG_USER_CUSTOMER_SESSION_CHAT_IDS_REQUIRED')
 // Read exact PostgreSQL server identity as structured SQL (not pipe-split
 // strings). A real GH Windows run exposed an ambiguous provenance projection.
 const raw=postgres("SELECT json_build_object('database',current_database(),'server',COALESCE(inet_server_addr()::text,'local'),'epoch',extract(epoch from pg_postmaster_start_time())::bigint)::text")
 let identity:{database?:unknown,server?:unknown,epoch?:unknown}
 try{identity=JSON.parse(raw) as typeof identity}catch{throw Error('NATIVE_PG_ISOLATION_OR_RUNTIME_PROVENANCE_FAILED:INVALID_POSTGRES_JSON')}
 const db=identity.database
 const server=identity.server
 const epoch=identity.epoch
 const dbQualified=typeof db==='string'&&/^(yance|chattermate)[a-z0-9_]*(_qa|_test)$/i.test(db)
 const serverQualified=typeof server==='string'&&['local','127.0.0.1','::1'].includes(server)
 const epochQualified=(typeof epoch==='number'&&Number.isSafeInteger(epoch)&&epoch>1000000000)
 if(!dbQualified||!serverQualified||!epochQualified)
  throw Error('NATIVE_PG_ISOLATION_OR_RUNTIME_PROVENANCE_FAILED:'+JSON.stringify({
   dbQualified,serverQualified,epochQualified,fieldTypes:[typeof db,typeof server,typeof epoch]}))
 const sql=`SELECT count(*) FROM customers c
 JOIN session_to_agents s ON s.customer_id=c.id AND s.organization_id=c.organization_id
 JOIN chat_history h ON h.session_id=s.session_id AND h.customer_id=c.id AND h.organization_id=c.organization_id
 JOIN users u ON u.organization_id=c.organization_id
 WHERE c.id='${fixture.customer}'::uuid AND c.organization_id='${fixture.org}'::uuid
 AND s.session_id='${fixture.session}'::uuid AND h.id=${fixture.message}
 AND u.id='${fixture.user}'::uuid`
 if(postgres(sql)!=='1')throw Error('NATIVE_PG_AUTH_CUSTOMER_SESSION_CHATHISTORY_OWNER_MISMATCH')
 return {database:db,server,dbPostmasterEpoch:Number(epoch),org:fixture.org,
  user:fixture.user,customer:fixture.customer,session:fixture.session,message:fixture.message}
}
// Exact owner readback. A hypothetical UI-only pin is NOT a persistence owner.
export function nativePinState(sessionId:string):boolean {
 if(!isUuid(sessionId))throw Error('NATIVE_PIN_SESSION_ID_REQUIRED')
 const owner=postgres("SELECT count(*) FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='session_to_agents' AND column_name='is_pinned'")
 if(owner!=='1')throw Error('NATIVE_PIN_PERSISTENCE_OWNER_NOT_QUALIFIED_HOLD')
 const stored=postgres(`SELECT CASE WHEN is_pinned THEN 'true' ELSE 'false' END
 FROM session_to_agents WHERE session_id='${sessionId}'::uuid AND organization_id='${fixture.org}'::uuid`)
 if(stored!=='true'&&stored!=='false')throw Error('NATIVE_PIN_SESSION_NOT_IN_AUTHORIZED_QA_ORG')
 return stored==='true'
}
export type CanonicalContact = {session_id:string,customer_id:string,full_name:string|null,email:string,chat_history_id:number}
export function canonicalContactRows():CanonicalContact[]{
 const sql=`SELECT COALESCE(json_agg(t),'[]'::json) FROM (
 SELECT s.session_id::text, c.id::text AS customer_id,
 c.full_name, c.email, h.id AS chat_history_id
 FROM session_to_agents s JOIN customers c ON c.id=s.customer_id
 JOIN LATERAL (
 SELECT id FROM chat_history h WHERE h.session_id=s.session_id
 AND h.customer_id=c.id AND h.organization_id=s.organization_id
 ORDER BY h.id DESC LIMIT 1
 ) h ON TRUE
 WHERE s.organization_id='${fixture.org}'::uuid
 ORDER BY s.session_id LIMIT 20
 ) t`
 const json=JSON.parse(postgres(sql)) as CanonicalContact[]
 if(!Array.isArray(json)||!json.length)throw Error('NATIVE_CONTACT_CANONICAL_READBACK_EMPTY')
 return json
}
export async function canonicalChatDetail(page:Page,sessionId:string) {
 if(!isUuid(sessionId))throw Error('INVALID_CANONICAL_SESSION_ID')
 const url=new URL('/api/v1/chats/'+sessionId,nativeApi)
 const response=await page.request.get(url.toString(),{timeout:7000})
 expect(response.ok(),'Native authenticated ChatDetail owner must reply').toBeTruthy()
 const detail=await response.json() as {session_id?:string,customer?:{id?:string,meta_data?:Record<string,unknown>},messages?:Array<{
  id?:number,message?:string,attributes?:Record<string,unknown>,message_type?:string,session_id?:string
 }>}
 expect(detail.session_id).toBe(sessionId)
 return detail
}
export async function requireNative(page:Page, info:TestInfo){
 if(process.env.YANCE_QA_ISOLATED!=='1'||process.env.YANCE_QA_FIXTURE!=='NATIVE_POSTGRES_AUTH'
  ||!nativeUrl||!nativeApi)throw Error('NATIVE_FIXTURE_REQUIRED: real app.main, private PostgreSQL, authorized QA identity')
 checkLoopback(nativeUrl);checkLoopback(nativeApi)
 await page.setViewportSize({width:920,height:620})
 const db=nativePgSnapshot() // real read-only SQL, not an env flag or HTTP 200
 const sha=execFileSync('git',['rev-parse','HEAD'],{cwd:resolve(import.meta.dirname,'../..'),encoding:'utf8'}).trim()
 info.annotations.push({type:'source-sha',description:sha})
 info.annotations.push({type:'fixture-class',description:'NATIVE_POSTGRES_AUTH_READONLY_PROBED'})
 info.annotations.push({type:'pg-server-epoch',description:String(db.dbPostmasterEpoch)})
 const health=await page.request.get(new URL('/health',nativeApi).toString(),{timeout:7000})
 expect(health.ok(),'Actual native app.main health required but is NOT proof of PG').toBeTruthy()
 // GH-hosted isolated QA creates a *real* disposable User and logs in via the
 // actual native /users/login endpoint. No pre-fabricated mock JWT or HTTP route.
 if(process.env.GITHUB_ACTIONS==='true'){
  const user=process.env.YANCE_QA_AUTH_USER||''
  const secretFile=process.env.YANCE_QA_AUTH_PASSWORD_FILE||''
  if(!user||!isAbsolute(secretFile)||!existsSync(secretFile))throw Error('HOSTED_NATIVE_REAL_LOGIN_CREDENTIAL_FILE_REQUIRED')
  const login=await page.request.post(new URL('/api/v1/users/login',nativeApi).toString(),{
   form:{username:user,password:readFileSync(secretFile,'utf8').trim()},timeout:10000})
  expect(login.ok(),'Native login returned real auth failure').toBeTruthy()
  const auth=await login.json() as {access_token?:string,user?:Record<string,unknown>}
  expect(typeof auth.access_token).toBe('string')
  expect(String(auth.user?.id)).toBe(fixture.user)
  // Preserve the real endpoint's HttpOnly Secure cookie flags. Never forge a
  // less-strict browser cookie to fabricate an authenticated native session.
  const actualCookies=await page.context().cookies(nativeApi)
  expect(actualCookies.some(c=>c.name==='access_token'&&c.httpOnly&&c.secure),
   'Actual login must set its real Secure HttpOnly cookie').toBeTruthy()
  await page.addInitScript((actualUser)=>localStorage.setItem('user_info',JSON.stringify(actualUser)),auth.user)
 }
 // A backend authenticated ChatHistory GET is required; anonymous 200 does not qualify.
 const response=await page.request.get(new URL('/api/v1/chats/'+fixture.session,nativeApi).toString(),{timeout:7000})
 expect(response.ok(),'Native auth scope must read persisted ChatHistory').toBeTruthy()
 const responseText=await response.text()
 expect(responseText,'real fixture history must contain canonical message identity').toContain(String(fixture.message))
}
export async function visitNative(page:Page,route:string){
 const r=await page.goto(new URL(route,nativeUrl).toString(),{waitUntil:'domcontentloaded'})
 expect(r?.ok(),'real Yance route').toBeTruthy()
 await expect(page.locator('body')).toBeVisible()
 expect(new URL(page.url()).pathname).not.toMatch(/login|register|signup|invite|pricing/i)
}
export async function saveState(page:Page,info:TestInfo,slug:string){
 await page.screenshot({path:info.outputPath(slug+'-920x620.png'),fullPage:false})
}
export async function requireNativeContact(page:Page){
 const target=page.locator('.conversation-item').first()
 await expect(target,'isolated PG positive fixture must contain real customer/session').toBeVisible()
 return target
}
