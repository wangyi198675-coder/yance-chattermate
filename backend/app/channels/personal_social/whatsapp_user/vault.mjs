// Account-scoped encrypted Signal state, never a message database.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { BufferJSON, initAuthCreds, proto } from '@whiskeysockets/baileys';

const helper = path.join(path.dirname(fileURLToPath(import.meta.url)), 'dpapi.ps1');
const MAX_ENVELOPE = 64 * 1024 * 1024;
export const hashedAccount = account => crypto.createHash('sha256').update('yance-personal-wa:' + account).digest('hex');
function dpapi(mode, bytes, account) {
  if (process.platform !== 'win32') throw Error('DPAPI_WINDOWS_ONLY');
  const raw = execFileSync('powershell.exe',
    ['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',helper,'-Mode',mode,'-Account',account],
    {input:Buffer.from(bytes).toString('base64')+'\n',encoding:'utf8',timeout:15000,windowsHide:true,maxBuffer:32768,stdio:['pipe','pipe','ignore']}).trim();
  const value = Buffer.from(raw,'base64');
  if (!value.length) throw Error('DPAPI_EMPTY_RESULT');
  return value;
}
function atomicWrite(file, data) {
  const temp = file+'.'+crypto.randomBytes(8).toString('hex')+'.tmp';
  try { fs.writeFileSync(temp,data,{flag:'wx',mode:0o600}); fs.renameSync(temp,file); }
  finally { try { fs.unlinkSync(temp); } catch {} }
}
export class EncryptedAuthVault {
  constructor(root,account,{wrap=dpapi}={}) {
    if (typeof account!=='string'|| !/^[A-Za-z0-9_-]{1,128}$/.test(account)) throw Error('INVALID_ACCOUNT_ID');
    if (!path.isAbsolute(root)) throw Error('ABSOLUTE_PRIVATE_DATA_ROOT_REQUIRED');
    this.account=account; this.dir=path.join(root,hashedAccount(account));
    this.file=path.join(this.dir,'session.auth.enc'); this.lockFile=path.join(this.dir,'session.session.lock');
    this.wrap=wrap; this.locked=false;
    fs.mkdirSync(this.dir,{recursive:true,mode:0o700});
  }
  lock(){
    try { fs.writeFileSync(this.lockFile,JSON.stringify({pid:process.pid}),{flag:'wx',mode:0o600}); }
    catch(e){
      if(e.code!=='EEXIST') throw e;
      let pid=0;
      try { pid=JSON.parse(fs.readFileSync(this.lockFile,'utf8')).pid; } catch {}
      if(!Number.isSafeInteger(pid)||pid<=0) throw Error('AUTH_LOCK_UNVERIFIABLE');
      try { process.kill(pid,0); throw Error('AUTH_ACCOUNT_ALREADY_OWNED'); }
      catch(err) { if(err.code!=='ESRCH') throw err; }
      fs.unlinkSync(this.lockFile);
      fs.writeFileSync(this.lockFile,JSON.stringify({pid:process.pid}),{flag:'wx',mode:0o600});
    }
    this.locked=true;
  }
  unlock(){
    if(!this.locked) return;
    try { const row=JSON.parse(fs.readFileSync(this.lockFile,'utf8'));
      if(row.pid===process.pid) fs.unlinkSync(this.lockFile);
    } finally { this.locked=false; }
  }
  load(){
    if(!this.locked) throw Error('VAULT_NOT_LOCKED');
    if(!fs.existsSync(this.file)){
      this.dek=crypto.randomBytes(32);
      this.wrapped=this.wrap('protect',this.dek,this.account).toString('base64');
      this.creds=initAuthCreds(); this.keyRows={}; this.persist();
    }else{
      if(fs.statSync(this.file).size>MAX_ENVELOPE) throw Error('AUTH_ENVELOPE_TOO_LARGE');
      const blob=JSON.parse(fs.readFileSync(this.file,'utf8'));
      if(blob.v!==1||!blob.wrapped||!blob.nonce||!blob.tag||!blob.ciphertext) throw Error('AUTH_ENVELOPE_INVALID');
      this.dek=this.wrap('unprotect',Buffer.from(blob.wrapped,'base64'),this.account);
      if(this.dek.length!==32) throw Error('AUTH_DEK_INVALID');
      this.wrapped=blob.wrapped;
      const cipher=crypto.createDecipheriv('aes-256-gcm',this.dek,Buffer.from(blob.nonce,'base64'));
      cipher.setAAD(Buffer.from(this.account,'utf8'));
      cipher.setAuthTag(Buffer.from(blob.tag,'base64'));
      const plaintext=Buffer.concat([cipher.update(Buffer.from(blob.ciphertext,'base64')),cipher.final()]);
      const data=JSON.parse(plaintext.toString('utf8'),BufferJSON.reviver);
      this.creds=data.creds; this.keyRows=data.keys||{};
      if(!this.creds||typeof this.keyRows!=='object') throw Error('AUTH_STATE_INVALID');
      plaintext.fill(0);
    }
    const self=this;
    return {state:{creds:this.creds,keys:{
      async get(type,ids){
        const values={};
        for(const id of ids){
          let v=(self.keyRows[type]||{})[id];
          if(type==='app-state-sync-key'&&v) v=proto.Message.AppStateSyncKeyData.fromObject(v);
          values[id]=v;
        }
        return values;
      },
      async set(rows){
        for(const [type,ids] of Object.entries(rows)){
          self.keyRows[type]||={};
          for(const [id,value] of Object.entries(ids)){
            if(value===null||value===undefined) delete self.keyRows[type][id];
            else self.keyRows[type][id]=value;
          }
        }
        self.persist();
      }
    }},saveCreds:()=>self.persist()};
  }
  persist(){
    if(!this.locked||!this.dek) throw Error('AUTH_NOT_OPEN');
    const content=Buffer.from(JSON.stringify({creds:this.creds,keys:this.keyRows},BufferJSON.replacer));
    const nonce=crypto.randomBytes(12),cipher=crypto.createCipheriv('aes-256-gcm',this.dek,nonce);
    cipher.setAAD(Buffer.from(this.account,'utf8'));
    const ciphertext=Buffer.concat([cipher.update(content),cipher.final()]);
    atomicWrite(this.file,JSON.stringify({v:1,wrapped:this.wrapped,nonce:nonce.toString('base64'),
      tag:cipher.getAuthTag().toString('base64'),ciphertext:ciphertext.toString('base64')}));
    content.fill(0);
  }
  rotateKey(){
    if(!this.locked) throw Error('VAULT_NOT_LOCKED');
    const old=this.dek,oldWrapped=this.wrapped;
    this.dek=crypto.randomBytes(32);
    try{
      this.wrapped=this.wrap('protect',this.dek,this.account).toString('base64');
      this.persist(); old.fill(0);
    }catch(e){this.dek.fill(0);this.dek=old;this.wrapped=oldWrapped;throw e;}
  }
  erase(){
    if(!this.locked) throw Error('VAULT_NOT_LOCKED');
    if(fs.existsSync(this.file)) fs.unlinkSync(this.file);
    this.dek?.fill(0);this.dek=null;
  }
  close(){this.dek?.fill(0);this.dek=null;this.unlock();}
}
