// Extracted V21 transport semantics: generation fences, QR lifecycle, account identity,
// provider message IDs, and physical send. No CRM, delivery engine, or transport DB.
import crypto from 'node:crypto';
import { downloadMediaMessage, DisconnectReason } from '@whiskeysockets/baileys';

const QR_TTL_MS=60_000, MAX_MEDIA_BYTES=16*1024*1024;
const JID=/^(?:[0-9]{6,20}@(s\.whatsapp\.net|lid)|[0-9]{5,20}(?:-[0-9]{5,20})?@g\.us)$/;
function checkJid(jid){if(typeof jid!=='string'||!JID.test(jid)) throw Error('INVALID_CANONICAL_JID');return jid;}
const shortError=e=>String(e?.code||'TRANSPORT_ERROR').slice(0,80);
function messageBody(info) {
  let m=info?.message||{};
  for(let i=0;i<3;i++){
    const nested=m?.ephemeralMessage?.message||m?.viewOnceMessage?.message||m?.viewOnceMessageV2?.message;
    if(!nested) break;
    m=nested;
  }
  const fields=['imageMessage','videoMessage','audioMessage','documentMessage','stickerMessage'];
  const kind=fields.find(k=>m[k])||'text';
  const media=m[kind]||null;
  return {kind, text:String(m.conversation||m.extendedTextMessage?.text||media?.caption||'').slice(0,65536),
    mime:media?.mimetype||null,fileName:media?.fileName||null};
}
function dedupe(account,key){return crypto.createHash('sha256')
  .update(JSON.stringify([account,key.remoteJid,key.id,key.participant||'',!!key.fromMe])).digest('hex');}
export function createTransport({account,baileys,vault,emit,schedule=setTimeout,unschedule=clearTimeout,logger}) {
  if(!/^[A-Za-z0-9_-]{1,128}$/.test(account)) throw Error('INVALID_ACCOUNT_ID');
  let socket=null,state='disconnected',generation=0,retries=0,stopped=true,qrTimer=null,reconnectTimer=null;
  let user=null,reason=null,lastQr=null;let auth=null;
  const mediaCache=new Map(),receiptMap=new Map(),egressMap=new Map(),seenInbound=new Set();
  const report=(status,code)=>{state=status;reason=code||null;emit({event:'health',accountId:account,status,reasonCode:reason,generation});};
  const clearQr=()=>{if(qrTimer) unschedule(qrTimer);qrTimer=null;lastQr=null;};
  const clearReconnect=()=>{if(reconnectTimer) unschedule(reconnectTimer);reconnectTimer=null;};
  const endSocket=()=>{const old=socket;socket=null;generation++;try{old?.end?.(new Error('CLIENT_SESSION_ENDED'));}catch{}};
  const isCurrent=(sock,gen)=>sock===socket&&gen===generation&&!stopped;
  const session=()=>{
    if(!auth) auth=vault.load();
    return auth;
  };
  const open=async()=>{
    if(stopped) return;
    clearReconnect();clearQr();endSocket();
    const g=generation;
    report('connecting');
    const stored=session();
    let sock;
    try{
      sock=baileys.default({auth:stored.state,printQRInTerminal:false,markOnlineOnConnect:false,
        syncFullHistory:true,shouldSyncHistoryMessage:()=>true,
        logger, getMessage:async()=>undefined});
    }catch(e){report('error',shortError(e));throw e;}
    socket=sock;
    sock.ev.on('creds.update',async()=>{if(!isCurrent(sock,g)) return;
      try{await stored.saveCreds();}catch{report('error','AUTH_PERSIST_FAILED');endSocket();}
    });
    sock.ev.on('connection.update',update=>{
      if(!isCurrent(sock,g)) return;
      if(update.qr){
        clearQr();lastQr=update.qr;
        report('connecting','QR_AWAITING_USER_SCAN');
        const expireAt=Date.now()+QR_TTL_MS;
        emit({event:'qr',accountId:account,qr:update.qr,expiresAt:new Date(expireAt).toISOString(),generation:g});
        qrTimer=schedule(()=>{
          if(isCurrent(sock,g)&&lastQr===update.qr) {
            clearQr();report('degraded','QR_EXPIRED');endSocket();
          }
        },QR_TTL_MS);
      }
      if(update.connection==='open'){
        if(!sock.user?.id){report('error','CONNECTED_WITHOUT_VERIFIED_USER');endSocket();return;}
        clearQr();retries=0;user={jid:String(sock.user.id),name:String(sock.user.name||'')};
        report('connected');
        emit({event:'identity',accountId:account,user,generation:g});
      }
      if(update.connection==='close'){
        clearQr();
        const code=update.lastDisconnect?.error?.output?.statusCode||update.lastDisconnect?.error?.statusCode||0;
        const revoked=code===(baileys.DisconnectReason||DisconnectReason).loggedOut;
        endSocket();user=null;
        if(revoked){stopped=true;report('error','PROVIDER_LOGGED_OUT');return;}
        report('degraded','PROVIDER_DISCONNECTED');
        if(!stopped){
          if(retries>=6){report('error','RECONNECT_EXHAUSTED');return;}
          const delay=Math.min(30000,1000*(2**retries++));
          reconnectTimer=schedule(()=>{void open().catch(()=>report('error','RECONNECT_FAILED'));},delay);
        }
      }
    });
    sock.ev.on('messages.upsert',batch=>{
      if(!isCurrent(sock,g)) return;
      for(const info of batch?.messages||[]){
        const key=info?.key||{};
        if(!key.id||!key.remoteJid||!info.message) continue;
        const id=dedupe(account,key);
        if(seenInbound.has(id)) continue;
        seenInbound.add(id);if(seenInbound.size>4096) seenInbound.delete(seenInbound.values().next().value);
        const body=messageBody(info);
        const isMedia=body.kind!=='text';
        if(isMedia){
          mediaCache.set(id,{info,sock,g,storedAt:Date.now()});
          if(mediaCache.size>64) mediaCache.delete(mediaCache.keys().next().value);
        }
        emit({event:'inbound',accountId:account,externalAccountId:user?.jid||null,
          externalConversationId:key.remoteJid,externalMessageId:key.id,
          idempotencyKey:id,providerChannel:'whatsapp-personal',participant:key.participant||null,
          fromMe:!!key.fromMe,source:batch.type==='append'?'history':'live',
          timestamp:typeof info.messageTimestamp==='number'?info.messageTimestamp:null,
          text:body.text,kind:body.kind,mime:body.mime,fileName:body.fileName,
          mediaRef:isMedia?id:null});
      }
    });
    sock.ev.on('messages.update',updates=>{
      if(!isCurrent(sock,g)) return;
      for(const update of updates||[]){
        const providerMessageId=String(update?.key?.id||'');
        if(!providerMessageId) continue;
        const rawStatus=update?.update?.status;
        const status=({1:'pending',2:'server_ack',3:'delivered',4:'read',5:'played'})[rawStatus]||'unknown';
        receiptMap.set(providerMessageId,status);
        if(receiptMap.size>4096) receiptMap.delete(receiptMap.keys().next().value);
        emit({event:'receipt',accountId:account,providerMessageId,status,
          externalConversationId:update?.key?.remoteJid||null});
      }
    });
  };
  const api={
    async connect(){
      if(!stopped) return api.status();
      stopped=false;
      try{await open();}catch(e){stopped=true;throw e;}
      return api.status();
    },
    async disconnect(){
      stopped=true;clearQr();clearReconnect();endSocket();user=null;
      report('disconnected');return api.status();
    },
    async reconnect(){
      await api.disconnect();return api.connect();
    },
    async cancel(){return api.disconnect();},
    async logout(){
      stopped=true;clearQr();clearReconnect();
      const target=socket;
      try {
        if(!target?.logout) throw Error('LOGOUT_REQUIRES_ACTIVE_SESSION');
        await target.logout();
        endSocket();vault.erase();user=null;auth=null;
        report('disconnected','USER_LOGOUT');return api.status();
      } catch {
        endSocket();user=null;report('error','LOGOUT_UNVERIFIED');
        throw Error('LOGOUT_UNVERIFIED');
      }
    },
    status(){return {status:state,reasonCode:reason,user,generation,qrPending:!!lastQr};},
    async send(cmd){
      if(state!=='connected'||!socket||!user) throw Error('PERSONAL_WHATSAPP_NOT_CONNECTED');
      const jid=checkJid(cmd.to);
      const key=String(cmd.idempotencyKey||'');
      if(!/^[a-zA-Z0-9:_-]{8,200}$/.test(key)) throw Error('CANONICAL_EGRESS_IDEMPOTENCY_REQUIRED');
      const fingerprint=crypto.createHash('sha256').update(JSON.stringify({to:jid,kind:cmd.kind,
        text:cmd.text||'',mime:cmd.mime||'',data:cmd.data||'',caption:cmd.caption||'',
        fileName:cmd.fileName||'',ptt:!!cmd.ptt})).digest('hex');
      if(egressMap.has(key)){
        const previous=egressMap.get(key);
        if(previous.fingerprint!==fingerprint) throw Error('EGRESS_IDEMPOTENCY_PAYLOAD_CONFLICT');
        return previous.receipt;
      }
      const sock=socket,g=generation;
      let content;
      if(cmd.kind==='text'){
        const text=String(cmd.text||'');
        if(!text.trim()||text.length>65536) throw Error('INVALID_TEXT_PAYLOAD');
        content={text};
      }else if(['image','video','audio','document'].includes(cmd.kind)){
        if(typeof cmd.data!=='string'||!cmd.data.length) throw Error('INVALID_MEDIA_BYTES');
        if(cmd.data.length>MAX_MEDIA_BYTES*1.4) throw Error('MEDIA_TOO_LARGE');
        const data=Buffer.from(cmd.data,'base64');
        if(!data.length||data.length>MAX_MEDIA_BYTES||data.toString('base64')!==cmd.data.replace(/\s/g,'')) throw Error('INVALID_MEDIA_BYTES');
        const mime=String(cmd.mime||'');
        if(!/^[a-zA-Z0-9.+_-]+\/[a-zA-Z0-9.+_-]+$/.test(mime)) throw Error('INVALID_MEDIA_MIME');
        if((cmd.kind==='image'&&!mime.startsWith('image/'))||
           (cmd.kind==='video'&&!mime.startsWith('video/'))||
           (cmd.kind==='audio'&&!mime.startsWith('audio/')))
          throw Error('MEDIA_KIND_MIME_MISMATCH');
        content={[cmd.kind]:data,mimetype:mime};
        if(cmd.kind==='document') content.fileName=String(cmd.fileName||'attachment').replace(/[\\/]/g,'_').slice(0,120);
        if(cmd.caption&&['image','video','document'].includes(cmd.kind))content.caption=String(cmd.caption).slice(0,2048);
        if(cmd.kind==='audio') content.ptt=!!cmd.ptt;
      }else throw Error('UNSUPPORTED_MESSAGE_KIND');
      // No implicit egress retries; canonical message_delivery owns physical attempt.
      const result=await sock.sendMessage(jid,content);
      if(!isCurrent(sock,g)||state!=='connected') throw Error('EGRESS_SOCKET_GENERATION_STALE');
      const providerMessageId=String(result?.key?.id||'');
      if(!providerMessageId) throw Error('PROVIDER_ACCEPTANCE_NOT_PROVEN');
      const receipt={messageId:key,providerMessageId,status:'accepted'};
      egressMap.set(key,{fingerprint,receipt});
      if(egressMap.size>1024) egressMap.delete(egressMap.keys().next().value);
      receiptMap.set(providerMessageId,'accepted');
      return receipt;
    },
    receipt(id){return {messageId:String(id),providerMessageId:String(id),status:receiptMap.get(String(id))||'unknown'};},
    async media(ref){
      const row=mediaCache.get(String(ref));
      if(!row||row.sock!==socket||row.g!==generation||Date.now()-row.storedAt>600000)
        throw Error('MEDIA_REFERENCE_EXPIRED');
      const bytes=await downloadMediaMessage(row.info,'buffer',{}, {logger,reuploadRequest:row.sock.updateMediaMessage});
      if(!Buffer.isBuffer(bytes)||bytes.length>MAX_MEDIA_BYTES) throw Error('MEDIA_TOO_LARGE');
      return {data:bytes.toString('base64'),byteLength:bytes.length};
    },
    async rotateKey(){vault.rotateKey();return {rotated:true};},
    backfill(){throw Error('BACKFILL_REQUIRES_CANONICAL_HISTORY_BRIDGE');}
  };
  return api;
}
