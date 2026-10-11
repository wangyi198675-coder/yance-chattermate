// stdin/stdout pipe-only bridge; no HTTP listener, public port, or session data in logs.
import readline from 'node:readline';
import process from 'node:process';
import path from 'node:path';
import { EncryptedAuthVault } from './vault.mjs';
import { createTransport } from './core.mjs';
import * as baileys from '@whiskeysockets/baileys';

const account=process.argv[2],root=process.argv[3];
if(!account||!root||!path.isAbsolute(root)){process.exitCode=2;}
else {
  const vault=new EncryptedAuthVault(root,account);
  const output=value=>{const ok=process.stdout.write(JSON.stringify(value)+'\n');
    if(!ok&&process.stdout.writableLength>4*1024*1024) {process.exitCode=41;process.stdin.pause();}};
  try {
    vault.lock();
    // Actual Baileys WebSocket errors are emitted as reason codes, not secrets.
    const logger={level:'silent',trace(){},debug(){},info(){},warn(){},error(){},fatal(){},child(){return this;}};
    const transport=createTransport({account,baileys,vault,logger,emit:output});
    const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity,terminal:false});
    let active=Promise.resolve();
    const methods=new Set(['connect','disconnect','reconnect','cancel','logout','status','send','receipt','media','rotateKey']);
    const run=async line=>{
      let id=null;
      try{
        if(Buffer.byteLength(line)>24*1024*1024) throw Error('COMMAND_TOO_LARGE');
        const cmd=JSON.parse(line);
        id=cmd.id;
        if(!Number.isSafeInteger(id)||id<1||!methods.has(cmd.op)) throw Error('INVALID_BRIDGE_COMMAND');
        const value=await transport[cmd.op](...(cmd.op==='send'||cmd.op==='receipt'||cmd.op==='media'?[cmd.payload]:[]));
        output({replyTo:id,ok:true,result:value});
      }catch(e){output({replyTo:id,ok:false,error:{code:String(e?.message||'BRIDGE_ERROR').slice(0,100)}});}
    };
    rl.on('line',line=>{active=active.then(()=>run(line)).catch(()=>{output({event:'health',status:'error',reasonCode:'PIPE_COMMAND_FAILED'});});});
    rl.on('close',()=>{active.finally(async()=>{try{await transport.disconnect();}finally{vault.close();}});});
    const finish=()=>{try{vault.close();}finally{process.exit(0);}};
    process.on('SIGTERM',finish);process.on('SIGINT',finish);
    output({event:'boot',accountId:account,status:'disconnected',driver:'baileys-7.0.0-rc14',authenticated:false});
  }catch(e){
    output({event:'fatal',status:'error',reasonCode:String(e?.message||'VAULT_ERROR').slice(0,100)});
    vault.close();process.exitCode=3;
  }
}
