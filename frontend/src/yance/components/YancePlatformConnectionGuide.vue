<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import type { ChannelType } from '@/services/channels'
const props=defineProps<{channel:ChannelType}>()
const emit=defineEmits<{(event:'close'):void;(event:'continue',channel:ChannelType):void}>()
type Path={name:string,description:string,supported:boolean,action?:string}
const paths: Partial<Record<ChannelType,Path[]>>={
 messenger:[
 {name:'Facebook 专页 Messenger',description:'需要 Meta 应用与专页管理员的官方授权；先核实应用和 Webhook，真实收发另测。',supported:true},
 {name:'个人 Facebook / 个人 Messenger',description:'当前没有已资格化的个人账号接入方式；不提供个人登录或虚假扫码。',supported:false}],
 whatsapp:[
 {name:'WhatsApp Business Cloud API',description:'需要 WABA / Phone Number ID / 官方 Token；平台审核和模板权限按 Meta 返回为准。',supported:true},
 {name:'个人 WhatsApp QR',description:'个人扫码多设备运行与收发未通过安全资格和 UAT，不生成二维码。',supported:false}],
 instagram:[
 {name:'Instagram 专业账号',description:'通过 Meta 官方 API、具备权限的专业账号；身份与消息权限独立核验。',supported:true},
 {name:'个人 Instagram',description:'个人身份尚无已验证的原生私信接入能力。',supported:false}],
 telegram:[
 {name:'Telegram Bot（机器人）',description:'通过 BotFather 令牌接入原生 Telegram 机器人 API；不等于个人账号。',supported:true},
 {name:'Telegram 个人账号',description:'个人 Telegram 登录尚无资格化的原生 owner；暂不可用。',supported:false}],
 line:[
 {name:'LINE 官方账号 Messaging API',description:'需要官方 Messaging API 渠道凭据及 Webhook 配置。',supported:true},
 {name:'个人 LINE 账号',description:'个人账号非当前原生连接范围，不能冒充官方账号。',supported:false}],
 email:[
 {name:'Email 服务商 / SMTP 接入',description:'使用现有 Email/SMTP 原生配置；须由有权限的人填写服务器和凭据，初次连接不证明收发。',supported:true},
 {name:'一键个人邮箱 OAuth 登录',description:'尚无已确认的原生通用 Gmail/Outlook OAuth 向导。',supported:false}],
 sms:[
 {name:'SMS 商业号码 / 服务商',description:'使用原生 SMS 服务商配置；号码归属、资费、合规及密钥须事先确认。',supported:true},
 {name:'手机个人短信同步',description:'本轮没有资格化的个人设备短信通道。',supported:false}],
 slack:[
 {name:'Slack 工作区官方安装授权',description:'跳转原生 Slack 安装 URL，由 Slack 和工作区管理员决定权限；不是个人号码登录。',supported:true},
 {name:'无需管理员权限直接读取工作区',description:'不支持绕过 Slack 官方许可或企业授权。',supported:false}],
}
const entries=paths[props.channel]||[]
const dialog=ref<HTMLElement|null>(null)
const focusables=()=>Array.from(dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled),[tabindex]:not([tabindex="-1"])')||[]).filter(e=>e.getClientRects().length>0)
const onKey=(e:KeyboardEvent)=>{
 if(e.key==='Escape'){e.preventDefault();e.stopPropagation();emit('close');return}
 if(e.key!=='Tab')return
 const items=focusables(),first=items[0],last=items[items.length-1]
 if(!first||!last){e.preventDefault();dialog.value?.focus();return}
 if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.value)){e.preventDefault();last.focus()}
 else if(!e.shiftKey&&(document.activeElement===last||document.activeElement===dialog.value)){e.preventDefault();first.focus()}
}
onMounted(async()=>{await nextTick();(focusables()[0]||dialog.value)?.focus()})
</script>
<template>
  <div class="yance-connection-guide-scrim" data-yance-connection-guide>
    <section ref="dialog" role="dialog" aria-modal="true" aria-labelledby="yance-guide-title" tabindex="-1"
      class="yance-connection-guide" @keydown="onKey">
      <header><div><small>原生连接资格 · 先区分账号类型</small><h2 id="yance-guide-title">{{ channel }} 连接方式</h2></div>
        <button type="button" aria-label="关闭连接引导" @click="emit('close')">关闭 ×</button></header>
      <p class="intro">下方状态是当前源码支持范围，并非已授权或已连通。只有你明确选择后才会进入现有 ChatterMate 原生连接流程。</p>
      <div class="guide-choices">
        <article v-for="(entry,index) in entries" :key="entry.name" :data-identity-index="index"
          :data-qualified="entry.supported?'native':'unavailable'">
          <h3>{{ entry.name }}</h3><p>{{ entry.description }}</p>
          <button v-if="entry.supported" type="button" :data-guide-native="channel" @click="emit('continue',channel)">继续原生连接配置</button>
          <span v-else role="status">未资格化 · 不可用</span>
        </article>
      </div>
      <footer>敏感凭据仍由 ChatterMate 原生服务处理。未获得授权不创建账号、不发消息、不生成 QR。</footer>
    </section>
  </div>
</template>
<style scoped>
.yance-connection-guide-scrim{position:fixed;inset:0;z-index:1002;display:grid;place-items:center;padding:14px;background:#090b16dc;color:#f1e8ef}
.yance-connection-guide{width:min(568px,calc(100vw - 30px));max-height:min(568px,94dvh);overflow:auto;border:1px solid #a58151;border-radius:12px;background:#201b2a;padding:15px;box-shadow:0 20px 65px #000b}
.yance-connection-guide header{display:flex;justify-content:space-between;align-items:start;gap:10px}
.yance-connection-guide small{color:#cbaa79;font-size:10px}.yance-connection-guide h2{font-size:17px;margin:5px 0;color:#f5e8ee}
.yance-connection-guide button{padding:7px 10px;border-radius:7px;border:1px solid #ad8a59;color:#f5eaf4;background:#4b345b;cursor:pointer}
.yance-connection-guide :is(button):focus-visible{outline:3px solid #f5c783}
.yance-connection-guide .intro{font-size:11px;color:#d4bfd5;line-height:1.6}
.guide-choices{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:12px 0}
.guide-choices article{display:flex;flex-direction:column;gap:9px;padding:12px;border:1px solid #614c66;border-radius:9px;background:#181823;min-height:178px}
.guide-choices h3{font-size:13px;margin:0;color:#f3e4ed}.guide-choices p{font-size:11px;line-height:1.6;color:#c2b4c5;margin:0}
.guide-choices button,.guide-choices span{margin-top:auto;align-self:start;font-size:10px}.guide-choices span{color:#f0ae85}
.yance-connection-guide footer{border-top:1px solid #59465d;padding-top:10px;font-size:10px;color:#a997ae}
@media(max-width:550px){.guide-choices{grid-template-columns:1fr}.guide-choices article{min-height:135px}}
</style>