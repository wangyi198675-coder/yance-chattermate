<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { YanceGirlfriendIntentDraft, YanceGirlfriendScope } from '../semanticTypes'

const props = withDefaults(defineProps<{
  open: boolean
  conversationAvailable?: boolean
  showLauncher?: boolean
}>(), { conversationAvailable: false, showLauncher: false })
const emit = defineEmits<{
  (event: 'update:open', value: boolean): void
  (event: 'turn-intent', draft: YanceGirlfriendIntentDraft): void
}>()
const router = useRouter()
const currentPath = () => router.currentRoute?.value?.path || window.location.pathname
const dialog = ref<HTMLElement | null>(null)
const instruction = ref('')
const scope = ref<YanceGirlfriendScope>('turn')
const persona = ref('')
const goal = ref('')
const turnOnly = ref(true)
const feedback = ref('')
let returnFocus: HTMLElement | null = null

const focusable = () => Array.from(dialog.value?.querySelectorAll<HTMLElement>(
  'button:not(:disabled),textarea:not(:disabled),input:not(:disabled),select:not(:disabled),a[href],[tabindex]:not([tabindex="-1"])',
) ?? []).filter(el => el.getClientRects().length > 0)
const close = () => emit('update:open', false)
const onDialogKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') {
    // Global Girlfriend is a higher z-index task modal; dismiss it first.
    // A native provider dialog may remain underneath and must not receive this Escape.
    event.preventDefault()
    event.stopPropagation()
    close()
    return
  }
  if (event.key !== 'Tab') return
  const items = focusable()
  if (!items.length) { event.preventDefault(); dialog.value?.focus(); return }
  const first = items[0], last = items[items.length - 1]
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) {
    event.preventDefault(); last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.value)) {
    event.preventDefault(); first.focus()
  }
}
const onGlobalShortcut = (event: KeyboardEvent) => {
  if (event.key.toLowerCase() !== 'g' || !event.ctrlKey || !event.shiftKey || event.altKey || event.metaKey) return
  // Conversation owns its current-turn native Girlfriend shortcut. Global
  // routing owns all other pages; an already-open global dialog can toggle closed.
  if (currentPath() === '/yance' && !props.open) return
  if (document.querySelector('.bm-scrim') && !props.open) return
  event.preventDefault()
  emit('update:open', !props.open)
}
watch(() => props.open, async (isOpen) => {
  if (isOpen) {
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    dialog.value?.querySelector<HTMLElement>('textarea')?.focus()
  } else {
    await nextTick()
    if (returnFocus?.isConnected) returnFocus.focus()
    else document.querySelector<HTMLElement>('[data-yance-global-girlfriend-launcher], [data-yance-girlfriend-toggle]')?.focus()
    returnFocus = null
  }
})
const submit = () => {
  if (!instruction.value.trim()) { feedback.value = '请先写下本次任务。'; return }
  if (!props.conversationAvailable || currentPath() !== '/yance') {
    feedback.value = '当前页面没有选中的对话。请先进入对话并选择联系人；未调用 AI、未发送任何消息。'
    return
  }
  if (!turnOnly.value || scope.value !== 'turn') {
    feedback.value = '当前只支持本轮、不学习；跨联系人或全局修改需要已授权的原生执行能力。'
    return
  }
  emit('turn-intent', {
    instruction: instruction.value.trim(),
    scope: scope.value,
    personaNote: persona.value.trim() || undefined,
    goalNote: goal.value.trim() || undefined,
    turnOnly: turnOnly.value,
  })
  feedback.value = '已提交本轮意图到对话 Reply Brain；等待原生回执，请在对话中确认。'
}
onMounted(() => document.addEventListener('keydown', onGlobalShortcut))
onBeforeUnmount(() => document.removeEventListener('keydown', onGlobalShortcut))
</script>

<template>
  <button v-if="showLauncher" type="button" data-yance-global-girlfriend-launcher
    class="yance-gf-global-trigger" @click="emit('update:open', true)">✦ 闺蜜大脑 · 任务</button>
  <Teleport to="body">
    <div v-if="open" class="yance-gf-scrim" data-yance-global-girlfriend
      @mousedown.self="close">
      <section ref="dialog" tabindex="-1" class="yance-gf-dialog"
        role="dialog" aria-modal="true" aria-labelledby="yance-gf-dialog-title"
        @keydown="onDialogKeydown">
        <header class="yance-gf-head">
          <div><h2 id="yance-gf-dialog-title">✦ 闺蜜大脑 · 任务</h2>
            <p>对话助手 · 先读取与规划 · 执行前由你确认</p></div>
          <button type="button" class="yance-gf-close" @click="close">关闭 ×</button>
        </header>
        <div class="yance-gf-body">
          <label for="yance-gf-task-input">你可以直接说自己的要求</label>
          <textarea id="yance-gf-task-input" v-model="instruction" data-yance-global-gf-input
            rows="4" maxlength="1600" placeholder="例如：回复时成熟自然一点，先接住对方刚才的信息。"></textarea>
          <fieldset>
            <legend>适用范围</legend>
            <label><input v-model="scope" type="radio" value="turn"> 仅本轮</label>
            <label><input v-model="scope" type="radio" value="contact"> 当前联系人</label>
            <label><input v-model="scope" type="radio" value="language"> 当前语言</label>
            <label><input v-model="scope" type="radio" value="relationship"> 当前关系</label>
            <label><input v-model="scope" type="radio" value="global"> 全局</label>
          </fieldset>
          <div class="yance-gf-fields">
            <label>本轮人格<input v-model="persona" maxlength="600" placeholder="自然、知性、有分寸"></label>
            <label>当前目标<input v-model="goal" maxlength="600" placeholder="按需填写，可为空"></label>
          </div>
          <label class="yance-gf-checkbox"><input v-model="turnOnly" type="checkbox"> 本轮临时覆盖，不学习、不写入长期规则</label>
          <div class="yance-gf-notice">执行由现有 ChatAgent / Agno 和已连接平台负责。本弹窗不创建第二 Agent，也不会直接发送消息。</div>
          <p v-if="feedback" role="status" data-yance-global-gf-feedback>{{ feedback }}</p>
        </div>
        <footer class="yance-gf-actions">
          <button type="button" class="yance-gf-outline" @click="close">取消</button>
          <button v-if="!conversationAvailable || currentPath() !== '/yance'" type="button"
            class="yance-gf-outline" @click="close();router.push('/yance')">打开当前对话</button>
          <button type="button" class="yance-gf-submit" data-yance-global-gf-submit @click="submit">整理任务意图</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style>
.yance-gf-scrim{position:fixed;inset:0;z-index:100000;background:#080811df;display:grid;place-items:center;
  padding:16px;color:#f1e9f3;font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif}
.yance-gf-dialog{width:min(525px,calc(100vw - 32px));max-height:min(540px,calc(100dvh - 24px));
  display:flex;flex-direction:column;min-height:0;background:linear-gradient(160deg,#2b1e36,#191922);
  border:1px solid #9670a8;border-radius:13px;box-shadow:0 20px 60px #000b;outline:0}
.yance-gf-head{display:flex;align-items:start;gap:10px;justify-content:space-between;padding:14px 16px;
  border-bottom:1px solid #72557a}
.yance-gf-head h2{margin:0;color:#efc9f5;font-size:16px}
.yance-gf-head p{font-size:11px;color:#bcb0c1;margin:5px 0 0}
.yance-gf-dialog button,.yance-gf-dialog textarea,.yance-gf-dialog input{font:inherit;color:inherit}
.yance-gf-dialog button{cursor:pointer;border:1px solid #80678a;border-radius:8px;background:#312640;padding:7px 10px}
.yance-gf-dialog :is(button,textarea,input):focus-visible{outline:3px solid #f5c783;outline-offset:2px}
.yance-gf-dialog .yance-gf-close{background:#211d2b}
.yance-gf-body{overflow:auto;min-height:0;flex:1;padding:13px 16px;display:grid;gap:10px;font-size:12px}
.yance-gf-body textarea,.yance-gf-fields input{background:#151723;border:1px solid #715b77;
  border-radius:8px;padding:9px;width:100%;resize:vertical;min-height:34px}
.yance-gf-body fieldset{border:1px solid #5d4c66;border-radius:8px;display:flex;gap:11px;flex-wrap:wrap;padding:8px 10px}
.yance-gf-body legend{color:#e3bfec}
.yance-gf-body label{display:block}
.yance-gf-body fieldset label,.yance-gf-checkbox{display:flex!important;gap:4px;align-items:center}
.yance-gf-fields{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.yance-gf-fields label{display:grid;gap:5px}
.yance-gf-notice{border:1px solid #806143;border-radius:7px;background:#33272a;
  color:#e8ccac;line-height:1.6;padding:8px}
.yance-gf-body [role="status"]{padding:7px;color:#e8c39d;border:1px solid #896b66;border-radius:7px}
.yance-gf-actions{display:flex;gap:8px;justify-content:flex-end;padding:11px 16px;
  border-top:1px solid #72557a}
.yance-gf-dialog .yance-gf-submit{background:#614279;border-color:#ae86c1;color:#fff2ff}
.yance-gf-global-trigger{background:#54326b;border:1px solid #ac7ed1;border-radius:8px;color:white;padding:7px}
@media(max-width:600px){.yance-gf-fields{grid-template-columns:1fr}}
</style>