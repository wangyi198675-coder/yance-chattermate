<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const visible = ref(false)
const launcher = ref<HTMLButtonElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
let opener: HTMLElement | null = null
let openEpoch = 0
let removeRouteHook: (() => void) | null = null

const capabilities = [
  { key: 'agents', title: 'AI 智能体', desc: '管理已有 ChatAgent；不创建第二运行时', path: '/ai-agents', state: 'native' },
  { key: 'knowledge', title: '知识库', desc: '使用原生 Knowledge 和检索', path: '/knowledge', state: 'native' },
  { key: 'tickets', title: '工单与收件箱', desc: '使用原生 Tickets，操作受权限约束', path: '/tickets', state: 'native' },
  { key: 'workflow', title: '工作流', desc: '当前没有已核准的原生编辑入口', path: '', state: 'blocked' },
  { key: 'analytics', title: '统计分析', desc: '原生 Analytics，可能需要授权', path: '/analytics', state: 'native' },
  { key: 'help', title: '帮助中心', desc: '原生 FAQ / Help Center 管理', path: '/faq', state: 'native' },
  { key: 'ai', title: 'AI 模型配置', desc: '读取 AIConfig；未配置不代表可推理', path: '/yance/manage/ai', state: 'native' },
  { key: 'widget', title: '嵌入式组件', desc: '原生 Widget Apps 与连接管理', path: '/settings/widget-apps', state: 'native' },
] as const

// This component owns only its dialog's focus. The global Girlfriend dialog
// takes precedence when present; native routing/RBAC remains with ChatterMate.
const globalGirlfriendOnTop = () => Boolean(document.querySelector('[data-yance-global-girlfriend]'))
const activeControls = (): HTMLElement[] => Array.from(dialog.value?.querySelectorAll<HTMLElement>(
  'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])',
) ?? []).filter(element =>
  element.getClientRects().length > 0 &&
  !element.closest('[hidden],[inert],[aria-hidden="true"]') &&
  getComputedStyle(element).visibility !== 'hidden',
)
const firstControl = () => activeControls()[0] ?? dialog.value
const restoreOpener = () => {
  const target = opener?.isConnected && !opener.matches(':disabled, [inert]') ? opener : launcher.value
  opener = null
  if (target?.isConnected && !target.matches(':disabled, [inert]')) target.focus({ preventScroll: true })
}
const close = (restore = true) => {
  if (!visible.value) return
  ++openEpoch
  visible.value = false
  if (restore) {
    // The launcher is outside the v-if, so it remains mounted while the
    // capability overlay closes. Avoid stale focus across native routes.
    void nextTick().then(restoreOpener)
  } else {
    opener = null
  }
}
const open = async () => {
  if (visible.value) return
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : launcher.value
  visible.value = true
  const epoch = ++openEpoch
  await nextTick()
  if (!visible.value || openEpoch !== epoch) return
  ;(closeButton.value ?? firstControl())?.focus({ preventScroll: true })
}
const toggle = () => { if (visible.value) close(); else void open() }

const onKeydown = (event: KeyboardEvent) => {
  if (!visible.value || globalGirlfriendOnTop()) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopImmediatePropagation()
    close()
    return
  }
  if (event.key !== 'Tab') return
  const controls = activeControls()
  const first = controls[0], last = controls[controls.length - 1]
  if (!first || !last) { event.preventDefault(); dialog.value?.focus(); return }
  if (!dialog.value?.contains(document.activeElement)) {
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus()
  } else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.value)) {
    event.preventDefault()
    first.focus()
  }
}
const onFocusIn = (event: FocusEvent) => {
  if (!visible.value || globalGirlfriendOnTop()) return
  if (dialog.value && !dialog.value.contains(event.target as Node)) firstControl()?.focus({ preventScroll: true })
}
const select = async (entry: (typeof capabilities)[number]) => {
  if (!entry.path) return
  const source = opener?.isConnected ? opener : launcher.value
  close(false)
  try {
    // The original Vue router owns any permission denial. Navigation failure
    // may leave this view mounted; only then return focus to its live launcher.
    const failure = await router.push({
      path: entry.path,
      state: { yanceNativeLaunch: true, yanceNativeReturnTo: router.currentRoute.value.fullPath },
    })
    if (failure && source?.isConnected) source.focus({ preventScroll: true })
  } catch {
    if (source?.isConnected) source.focus({ preventScroll: true })
  }
}
onMounted(() => {
  document.addEventListener('keydown', onKeydown, true)
  document.addEventListener('focusin', onFocusIn, true)
  // A route change from another native control also removes the modal; do not
  // focus a launcher belonging to the page we have just left.
  if (typeof router.afterEach === 'function') {
    removeRouteHook = router.afterEach(() => { if (visible.value) close(false) })
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown, true)
  document.removeEventListener('focusin', onFocusIn, true)
  removeRouteHook?.()
  ++openEpoch
  opener = null
})
</script>
<template>
  <button ref="launcher" type="button" class="yance-web-route yance-web-advanced" data-yance-capability-launcher
    :aria-expanded="visible" aria-haspopup="dialog" aria-controls="yance-native-capabilities" @click="toggle">✦ 原生能力中心</button>
  <div v-if="visible" class="yance-capability-scrim" data-yance-capability-scrim @mousedown.self.prevent="close()">
    <section ref="dialog" id="yance-native-capabilities" class="yance-capability-hub" data-yance-native-capability-hub
      role="dialog" aria-modal="true" aria-labelledby="yance-native-capability-title" tabindex="-1">
      <header><div><p>ChatterMate 原生能力 · 八类入口</p><h2 id="yance-native-capability-title">能力中心</h2></div>
        <button ref="closeButton" data-yance-capability-close type="button" @click="close()">关闭</button></header>
      <p class="yance-capability-caution">这些入口保留原生业务操作、账号与权限检查，并从言策工作区承载；部分原生正文仍是英文，需单独完成中文视觉验收。</p>
      <div class="yance-capability-grid">
        <article v-for="entry in capabilities" :key="entry.key" :data-capability="entry.key">
          <h3>{{ entry.title }}</h3><p>{{ entry.desc }}</p>
          <button v-if="entry.state==='native'" type="button" :data-native-route="entry.path" @click="select(entry)">进入原生功能</button>
          <span v-else class="unavailable">尚未资格化 · 不可用</span>
        </article>
      </div>
    </section>
  </div>
</template>
<style scoped>
.yance-web-advanced{width:100%;text-align:left;cursor:pointer}
.yance-capability-scrim{position:fixed;inset:0;z-index:9000;background:#090b16e9;display:grid;place-items:center;padding:12px;color:#f2e7eb}
.yance-capability-hub{width:min(820px,100%);max-height:min(596px,95dvh);overflow:auto;background:#1d1925;border:1px solid #97714e;border-radius:14px;padding:15px;box-shadow:0 22px 60px #000a}
.yance-capability-hub header{display:flex;align-items:center;justify-content:space-between}
.yance-capability-hub header p{font-size:11px;color:#bb9a6c;margin:0}
.yance-capability-hub h2{font-size:20px;margin:2px 0}
.yance-capability-hub button{border:1px solid #796485;border-radius:7px;background:#32243d;color:#f2e5f4;padding:6px 10px;cursor:pointer}
.yance-capability-hub :is(button,a,[tabindex]):focus-visible{outline:3px solid #f2c88d;outline-offset:2px}
.yance-capability-caution{padding:9px;border:1px solid #785a41;background:#30242a;color:#e8cfae;font-size:11px}
.yance-capability-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}
.yance-capability-grid article{border:1px solid #66516a;border-radius:10px;padding:13px 9px;min-height:148px;display:flex;flex-direction:column;background:#171722}
.yance-capability-grid h3{font-size:13px;margin:0 0 8px;color:#f5e5ef}
.yance-capability-grid article p{font-size:10px;color:#b9a8bd;line-height:1.55;margin:0}
.yance-capability-grid article button,.yance-capability-grid .unavailable{margin-top:auto;font-size:10px}
.yance-capability-grid .unavailable{color:#edb485}
@media(max-width:650px){.yance-capability-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
