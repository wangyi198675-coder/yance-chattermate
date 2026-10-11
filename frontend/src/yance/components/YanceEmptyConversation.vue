<script setup lang="ts">
import { useRouter } from 'vue-router'
import YanceWebShell from './YanceWebShell.vue'
defineProps<{ loading?: boolean; refreshing?: boolean }>()
const emit=defineEmits<{ (event:'refresh'):void }>()
const router=useRouter()
</script>
<template>
  <YanceWebShell connection-summary="原生消息记录为空 · 平台状态请在账号页核对">
    <main class="w371-empty-conversation" data-w371-native-empty-conversation>
      <header>
        <p>原生空态 · 当前没有可读取的会话记录</p>
        <h1>暂无对话</h1>
      </header>
      <section class="w371-empty-conversation__panel">
        <h2>开始之前</h2>
        <div class="w371-empty-conversation__center">
          <span class="w371-empty-conversation__symbol" aria-hidden="true">◯</span>
          <h3>目前没有真实对话</h3>
          <p>连接平台并收到第一条消息后，会在这里显示联系人和聊天记录。</p>
          <button type="button" data-w371-empty-connect @click="router.push('/yance/platform-accounts')">连接平台账号</button>
          <button type="button" class="w371-empty-conversation__refresh" :disabled="refreshing"
            @click="emit('refresh')">{{ refreshing ? '正在检查…' : '检查新对话' }}</button>
        </div>
      </section>
      <section class="w371-empty-conversation__note">
        <h2>重要说明</h2>
        <p>不会为了展示旧设计而创建虚构联系人；历史 RC3 示意资料只用于有水印的设计稿。</p>
      </section>
    </main>
  </YanceWebShell>
</template>
<style scoped>
.w371-empty-conversation{padding:2px 0 10px 0;display:flex;flex-direction:column;gap:10px;overflow:hidden!important}
.w371-empty-conversation header{height:44px;flex:none}
.w371-empty-conversation header p{color:#ae8c58;font-size:11px;margin:0}
.w371-empty-conversation header h1{margin:0;font-size:20px;color:#f1e7ee}
.w371-empty-conversation__panel{border:1px solid #88633f;border-radius:11px;background:#221c22;height:330px;flex:none;padding:16px}
.w371-empty-conversation__panel h2,.w371-empty-conversation__note h2{margin:0;font-size:13px!important;color:#f2e7eb}
.w371-empty-conversation__center{display:flex;flex-direction:column;align-items:center;text-align:center;margin-top:29px}
.w371-empty-conversation__symbol{height:49px;color:#cc994c;font-size:36px;line-height:1}
.w371-empty-conversation__center h3{font-size:16px!important;font-weight:400;margin:5px 0 9px}
.w371-empty-conversation__center p{font-size:11px;color:#aca2b2;margin:0 0 18px}
.w371-empty-conversation__center button{padding:8px 14px;border-radius:7px;border:1px solid #b88a51;background:#76532b;color:#f7e9d2;cursor:pointer}
.w371-empty-conversation__center .w371-empty-conversation__refresh{background:transparent;color:#cdb7cf;border:0;font-size:10px;margin-top:4px}
.w371-empty-conversation__note{height:92px;border:1px solid #494151;background:#161924;border-radius:11px;padding:16px}
.w371-empty-conversation__note p{font-size:11px;margin:10px 0;color:#d4cad5}
</style>
