import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import crypto from 'node:crypto';
import { EncryptedAuthVault, hashedAccount } from '../vault.mjs';
import { createTransport } from '../core.mjs';

const scratch=()=>fs.mkdtempSync(path.join(os.tmpdir(),'w398-offline-'));
const account='canonical_acct_A';
function mockTransport(name='a'){
  const vault={load:()=>({state:{creds:{registered:false},keys:{}},saveCreds:async()=>{}}),
    erase(){this.erased=true;},rotateKey(){this.rotated=true;}};
  const socks=[],events=[],timers=[];
  const lib={DisconnectReason:{loggedOut:401},default(options){
    const s={ev:new EventEmitter(),user:null,end(){this.ended=true;},
      async logout(){this.loggedOut=true;},
      async sendMessage(to,content){this.last={to,content};return {key:{id:'provider-'+name}};}};
    socks.push(s);return s;
  }};
  const tr=createTransport({account,baileys:lib,vault,logger:{},emit:e=>events.push(e),
    schedule:(fn,ms)=>{const timer={fn,ms};timers.push(timer);return timer;},unschedule:()=>{}});
  return {tr,events,socks,timers,vault};
}
test('V21 source-bound real socket event -> QR; never mock READY',async()=>{
  const {tr,events,socks,timers}=mockTransport();
  assert.equal(tr.status().status,'disconnected');
  await assert.rejects(()=>tr.send({kind:'text',to:'123456789@s.whatsapp.net',text:'Hi',idempotencyKey:'canonical-attempt-1'}),/NOT_CONNECTED/);
  await tr.connect();
  assert.equal(tr.status().status,'connecting');
  socks[0].ev.emit('connection.update',{qr:'LIBRARY_QR_FIXTURE'});
  assert.equal(events.find(e=>e.event==='qr').qr,'LIBRARY_QR_FIXTURE');
  assert.equal(events.find(e=>e.event==='qr').accountId,account);
  assert.equal(tr.status().status,'connecting');
  assert.equal(timers.at(-1).ms,60000);
  timers.at(-1).fn();
  assert.equal(tr.status().status,'degraded');
  assert.equal(tr.status().reasonCode,'QR_EXPIRED');
  assert.equal(socks[0].ended,true);
});
test('provider verified open required; canceled QR cannot later grant READY',async()=>{
  const {tr,socks}=mockTransport();
  await tr.connect();
  socks[0].ev.emit('connection.update',{connection:'open'});
  assert.equal(tr.status().status,'error');
  await tr.cancel();
  const s=socks[0];
  s.user={id:'123456789@s.whatsapp.net'};
  s.ev.emit('connection.update',{connection:'open'});
  assert.equal(tr.status().status,'disconnected');
});
test('inbound dedupe maps canonical provenance; egress requires delivery attempt id and verified socket',async()=>{
  const {tr,socks,events}=mockTransport();
  await tr.connect();
  const s=socks[0];s.user={id:'10000000@s.whatsapp.net',name:'me'};
  s.ev.emit('connection.update',{connection:'open'});
  assert.equal(tr.status().status,'connected');
  const msg={key:{remoteJid:'123456789@s.whatsapp.net',id:'AB123',fromMe:false},
    message:{conversation:'a known fixture'},messageTimestamp:42};
  s.ev.emit('messages.upsert',{messages:[msg],type:'notify'});
  s.ev.emit('messages.upsert',{messages:[msg],type:'notify'});
  const inbound=events.filter(e=>e.event==='inbound');
  assert.equal(inbound.length,1);
  assert.equal(inbound[0].externalMessageId,'AB123');
  assert.equal(inbound[0].providerChannel,'whatsapp-personal');
  assert.match(inbound[0].idempotencyKey,/^[a-f0-9]{64}$/);
  await assert.rejects(()=>tr.send({kind:'text',to:'123456789@s.whatsapp.net',text:'hi'}),/IDEMPOTENCY_REQUIRED/);
  await assert.rejects(()=>tr.send({kind:'text',to:'https://evil.invalid',text:'hi',idempotencyKey:'canonical-attempt-1'}),/JID/);
  const receipt=await tr.send({kind:'text',to:'123456789@s.whatsapp.net',text:'Hi',idempotencyKey:'canonical-attempt-1'});
  assert.equal(receipt.providerMessageId,'provider-a');
  assert.equal(s.last.content.text,'Hi');
  assert.deepEqual(receipt,await tr.send({kind:'text',to:'123456789@s.whatsapp.net',text:'Hi',idempotencyKey:'canonical-attempt-1'}));
  s.ev.emit('messages.update',[{key:{id:'provider-a',remoteJid:'123456789@s.whatsapp.net'},update:{status:3}}]);
  assert.equal(tr.receipt('provider-a').status,'delivered');
  await assert.rejects(()=>tr.send({kind:'text',to:'123456789@s.whatsapp.net',text:'changed',idempotencyKey:'canonical-attempt-1'}),/PAYLOAD_CONFLICT/);
});
test('logout differs from disconnect; multi-account process generations fence stale events',async()=>{
  const a=mockTransport('A'),b=mockTransport('B');
  await a.tr.connect();await b.tr.connect();
  a.socks[0].user={id:'111111111@s.whatsapp.net'};
  b.socks[0].user={id:'222222222@s.whatsapp.net'};
  a.socks[0].ev.emit('connection.update',{connection:'open'});
  b.socks[0].ev.emit('connection.update',{connection:'open'});
  await a.tr.disconnect();
  a.socks[0].ev.emit('messages.upsert',{messages:[{key:{id:'STALE',remoteJid:'123456789@s.whatsapp.net'},message:{conversation:'leak'}}]});
  assert.equal(a.events.filter(e=>e.event==='inbound').length,0);
  assert.equal(b.tr.status().status,'connected');
  await b.tr.logout();
  assert.equal(b.vault.erased,true);
  assert.equal(a.vault.erased,undefined);
});
test('reconnect on transient closure, no reconnect on logged-out code',async()=>{
  const a=mockTransport();
  await a.tr.connect();
  a.socks[0].ev.emit('connection.update',{connection:'close',lastDisconnect:{error:{output:{statusCode:500}}}});
  assert.equal(a.tr.status().status,'degraded');
  assert.equal(a.timers.at(-1).ms,1000);
  a.timers.at(-1).fn();
  await Promise.resolve();await Promise.resolve();
  assert.equal(a.socks.length,2);
  a.socks[1].ev.emit('connection.update',{connection:'close',lastDisconnect:{error:{output:{statusCode:401}}}});
  assert.equal(a.tr.status().reasonCode,'PROVIDER_LOGGED_OUT');
});
test('real Windows DPAPI sealed Signal state, restart, rotation, tamper & sibling isolation',()=>{
  if(process.platform!=='win32') return;
  const root=scratch();
  try{
    const v=new EncryptedAuthVault(root,'account_one');
    v.lock();
    const one=v.load();
    one.state.creds.me={id:'111111@s.whatsapp.net'};
    v.persist();
    const file=path.join(root,hashedAccount('account_one'),'session.auth.enc');
    const before=fs.readFileSync(file,'utf8');
    assert.equal(before.includes('111111@s.whatsapp.net'),false);
    v.rotateKey();
    const after=fs.readFileSync(file,'utf8');
    assert.notEqual(JSON.parse(before).wrapped,JSON.parse(after).wrapped);
    v.close();
    const v2=new EncryptedAuthVault(root,'account_one');
    v2.lock();
    const stored=v2.load();
    assert.equal(stored.state.creds.me.id,'111111@s.whatsapp.net');
    v2.close();
    const sibling=new EncryptedAuthVault(root,'account_two');
    sibling.lock();sibling.load();
    assert.notEqual(sibling.file,v2.file);
    sibling.close();
    const row=JSON.parse(fs.readFileSync(file,'utf8'));
    row.tag=crypto.randomBytes(16).toString('base64');
    fs.writeFileSync(file,JSON.stringify(row));
    const corrupt=new EncryptedAuthVault(root,'account_one');
    corrupt.lock();
    assert.throws(()=>corrupt.load());
    corrupt.close();
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('DPAPI account binding cannot decrypt sibling encrypted key',()=>{
  if(process.platform!=='win32') return;
  const root=scratch();
  try {
    const a=new EncryptedAuthVault(root,'a');a.lock();a.load();a.close();
    const b=new EncryptedAuthVault(root,'b');b.lock();b.load();b.close();
    const ap=path.join(root,hashedAccount('a'),'session.auth.enc');
    const bp=path.join(root,hashedAccount('b'),'session.auth.enc');
    fs.writeFileSync(bp,fs.readFileSync(ap));
    const wrong=new EncryptedAuthVault(root,'b');wrong.lock();
    assert.throws(()=>wrong.load(),/./);
    wrong.close();
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('binary outbound uses provider Buffer and rejects URL/path/media type tricks',async()=>{
  const {tr,socks}=mockTransport('media');
  await tr.connect();socks[0].user={id:'10000000@s.whatsapp.net'};
  socks[0].ev.emit('connection.update',{connection:'open'});
  const data=Buffer.from([0,1,2,255]).toString('base64');
  const row=await tr.send({kind:'image',to:'123456789@s.whatsapp.net',
    idempotencyKey:'canonical-media-1',mime:'image/png',data,caption:'image'});
  assert.equal(row.status,'accepted');
  assert.deepEqual(socks[0].last.content.image,Buffer.from([0,1,2,255]));
  await assert.rejects(()=>tr.send({kind:'image',to:'123456789@s.whatsapp.net',
    idempotencyKey:'canonical-media-2',mime:'text/html',data:'not-base64###'}),/INVALID_MEDIA_BYTES/);
  await assert.rejects(()=>tr.send({kind:'document',to:'123456789@s.whatsapp.net',
    idempotencyKey:'canonical-media-3',mime:'invalid',data}),/INVALID_MEDIA_MIME/);
  await assert.rejects(()=>tr.send({kind:'image',to:'123456789@s.whatsapp.net',
    idempotencyKey:'canonical-media-4',mime:'image/png',url:'https://evil.invalid'}),/INVALID_MEDIA_BYTES/);
  await assert.rejects(()=>tr.send({kind:'image',to:'123456789@s.whatsapp.net',
    idempotencyKey:'canonical-media-5',mime:'text/html',data}),/MEDIA_KIND_MIME_MISMATCH/);
});
test('in-flight provider send from old socket generation never emits accepted',async()=>{
  const {tr,socks}=mockTransport('race');
  await tr.connect();socks[0].user={id:'10000000@s.whatsapp.net'};
  socks[0].ev.emit('connection.update',{connection:'open'});
  let deliver;
  socks[0].sendMessage=()=>new Promise(resolve=>{deliver=resolve;});
  const work=tr.send({kind:'text',to:'123456789@s.whatsapp.net',
    idempotencyKey:'canonical-generation-1',text:'testing'});
  await tr.disconnect();
  deliver({key:{id:'provider-stale'}});
  await assert.rejects(work,/GENERATION_STALE/);
});

test('real Windows encrypted Signal key store survives restart without plaintext key material',async()=>{
  if(process.platform!=='win32') return;
  const root=scratch();
  try {
    const v=new EncryptedAuthVault(root,'signal_one');v.lock();
    const first=v.load();
    await first.state.keys.set({session:{'signal-device-one':Buffer.from('SENSITIVE_SIGNAL_TEST_KEY')}});
    const bytes=fs.readFileSync(v.file,'utf8');
    assert.equal(bytes.includes('SENSITIVE_SIGNAL_TEST_KEY'),false);
    v.close();
    const restored=new EncryptedAuthVault(root,'signal_one');restored.lock();
    const second=restored.load();
    const result=await second.state.keys.get('session',['signal-device-one']);
    assert.equal(Buffer.from(result['signal-device-one']).toString('utf8'),'SENSITIVE_SIGNAL_TEST_KEY');
    restored.close();
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});
