<script setup lang="ts">
import { useRouter } from 'vue-router'
defineProps<{ supportedPlatforms: number; connectedPlatforms: number }>()
const router = useRouter()
</script>
<template>
  <section class="w371-first-run" data-w371-home-zero-account>
    <div class="w371-first-run__welcome">
      <strong>欢迎使用言策</strong>
      <h2>先连接一个平台，才能收到属于你的对话。</h2>
      <p>当前隔离测试环境：未配置平台账号，联系人和消息均为空。</p>
      <div class="w371-first-run__actions">
        <button type="button" class="w371-first-run__primary" data-w371-connect-platform
          @click="router.push('/yance/platform-accounts')">去连接平台</button>
        <button type="button" @click="router.push('/yance/settings')">查看 AI 模型配置</button>
      </div>
    </div>
    <div class="w371-first-run__lower">
      <section class="w371-first-run__attention" aria-labelledby="w371-attention-heading">
        <h2 id="w371-attention-heading">今日值得关注</h2>
        <p>暂无真实会话 · 连接平台后自动呈现</p>
      </section>
      <section class="w371-first-run__runtime" aria-labelledby="w371-status-heading">
        <h2 id="w371-status-heading">平台与运行状态</h2>
        <dl>
          <div><dt>平台账号</dt><dd>{{ connectedPlatforms }}/{{ supportedPlatforms }}<small>尚未配置</small></dd></div>
          <div><dt>AI 模型</dt><dd><button type="button" @click="router.push('/yance/settings')">查看配置</button><small>状态待核对</small></dd></div>
          <div><dt>数据来源</dt><dd><small>原生账号与消息库</small><span>已读取</span></dd></div>
        </dl>
      </section>
    </div>
    <p class="w371-first-run__truth">这些图表读取账号 UI，不是浏览器验收截图；仅展示原生 API 已核实的空账号状态。</p>
  </section>
</template>
<style scoped>
.w371-first-run{display:grid;grid-template-rows:213px 228px auto;gap:10px;margin:0 4px;color:#f1e8e9;min-height:0}
.w371-first-run__welcome,.w371-first-run__attention,.w371-first-run__runtime{
  background:#201c23;border:1px solid #936c42;border-radius:11px;padding:16px}
.w371-first-run__welcome strong{display:block;font-size:13px;margin-bottom:16px}
.w371-first-run__welcome h2{font-size:14px!important;font-weight:400;line-height:1.5;margin:0}
.w371-first-run__welcome p{font-size:11px;color:#ad9fae;margin:6px 0 16px}
.w371-first-run__actions{display:flex;gap:8px}
.w371-first-run__actions button,.w371-first-run__runtime button{padding:7px 12px;background:#282530;border:1px solid #5e4d61;border-radius:7px;color:#e5d5e1;cursor:pointer;font-size:12px}
.w371-first-run__actions .w371-first-run__primary{background:#836039;border-color:#bb9058;color:#fff2d2}
.w371-first-run__lower{display:grid;grid-template-columns:1fr 1fr;gap:10px;min-height:0}
.w371-first-run__attention{border-color:#393549;background:#161923}
.w371-first-run__runtime{border-color:#694779;background:#251d30}
.w371-first-run__lower h2{font-size:13px!important;margin:0 0 17px}
.w371-first-run__attention p{color:#998e9c;font-size:11px;margin-top:38px}
.w371-first-run__runtime dl{margin:0;display:grid;gap:5px}
.w371-first-run__runtime dl div{border-bottom:1px solid #483e52;display:flex;justify-content:space-between;gap:5px;min-height:51px}
.w371-first-run__runtime dl div:last-child{border:0}
.w371-first-run__runtime dt{font-size:11px}
.w371-first-run__runtime dd{display:flex;align-items:flex-end;flex-direction:column;margin:0;color:#d5b785;font-size:11px}
.w371-first-run__runtime dd small{font-size:10px;color:#a99fae}
.w371-first-run__runtime dd button{padding:2px 6px;border:0;background:none;color:#d5b785}
.w371-first-run__truth{font-size:10px;color:#988a9a;margin:1px}
@media(max-width:600px){.w371-first-run{grid-template-rows:auto auto auto}.w371-first-run__lower{grid-template-columns:1fr}}
</style>
