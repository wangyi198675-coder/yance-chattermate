<script setup lang="ts">
import YanceWebShell from './components/YanceWebShell.vue'
import { computed, onBeforeUnmount, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import channelsService, { type ChannelAccount, type ChannelType } from '@/services/channels'
import MetaChannelConnect from '@/components/integrations/MetaChannelConnect.vue'
import TelegramConnectModal from '@/components/integrations/TelegramConnectModal.vue'
import ChannelConnectModal from '@/components/integrations/ChannelConnectModal.vue'
import WhatsAppTemplateManager from '@/components/integrations/WhatsAppTemplateManager.vue'
import YancePlatformConnectionGuide from './components/YancePlatformConnectionGuide.vue'

const router = useRouter()
const accounts = ref<ChannelAccount[]>([])
const loading = ref(true)
const error = ref('')
const busyAccount = ref('')
const selectedChannel = ref<ChannelType | null>(null)
const guideChannel = ref<ChannelType | null>(null)
let guideLauncher: HTMLElement | null = null
const selectedAccount = ref<ChannelAccount | null>(null)
// Native credential-modal reconfigure drops its existing-account identity and can POST
// a new Email/SMS/LINE account. Existing rows therefore use a safe read-only view.
const readOnlyAccount = ref<ChannelAccount | null>(null)
// Reuse native channel dialogs; one W370 host-owned keyboard and return-focus lifecycle.
type FocusChannel = 'messenger' | 'whatsapp' | 'instagram' | 'telegram' | 'line' | 'email' | 'sms'
let launchFocus: HTMLElement | null = null
let launchChannel: FocusChannel | null = null
let closingModal = false
const nativeDialogSelectors: Record<FocusChannel, string> = {
  messenger: '.meta-modal-content', whatsapp: '.meta-modal-content',
  instagram: '.meta-modal-content', telegram: '.tg-modal-content',
  line: '.cc-modal-content', email: '.cc-modal-content', sms: '.cc-modal-content',
}
const activeDialog = () => selectedChannel.value && selectedChannel.value in nativeDialogSelectors
  ? document.querySelector<HTMLElement>(nativeDialogSelectors[selectedChannel.value as FocusChannel])
  : null
const focusableIn = (dialog: HTMLElement) => Array.from(dialog.querySelectorAll<HTMLElement>(
  'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex]:not([tabindex="-1"])',
)).filter(item => item.getClientRects().length > 0 && !item.closest('[hidden],[inert]'))
const onNativeModalKeys = (event: KeyboardEvent) => {
  const dialog = activeDialog()
  if (!dialog || closingModal) return
  // Top-level Girlfriend task modal outranks underlying native provider
  // dialogs. Do not capture its Escape or Tab at the document level.
  if (document.querySelector('[data-yance-global-girlfriend]')) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopImmediatePropagation()
    void closeModal()
    return
  }
  if (event.key !== 'Tab') return
  const items = focusableIn(dialog)
  if (!items.length) { event.preventDefault(); dialog.focus(); return }
  const first = items[0]!, last = items[items.length - 1]!
  if (!dialog.contains(document.activeElement)) {
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus()
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault(); last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault(); first.focus()
  }
}
const onNativeModalFocus = (event: FocusEvent) => {
  if (closingModal || document.querySelector('[data-yance-global-girlfriend]')) return
  const dialog = activeDialog()
  if (dialog && !dialog.contains(event.target as Node)) (focusableIn(dialog)[0] ?? dialog).focus()
}
const restoreLaunchFocus = async () => {
  await nextTick()
  const original = launchFocus
  const channel = launchChannel
  const fallback = channel
    ? document.querySelector<HTMLElement>('[data-yance-channel-launcher="' + channel + '"]:not(:disabled)')
    : null
  const target = original?.isConnected && !original.hasAttribute('disabled') ? original : fallback
  if (target?.isConnected) target.focus({ preventScroll: true })
  launchFocus = null
  launchChannel = null
}
watch(selectedChannel, async current => {
  if (!current || !(current in nativeDialogSelectors)) return
  await nextTick()
  if (selectedChannel.value !== current) return
  const dialog = activeDialog()
  if (!dialog) return
  const title = dialog.querySelector<HTMLElement>('.meta-modal-header h3,.tg-modal-header h3,.cc-modal-header h3')
  if (title) {
    title.id = 'yance-native-' + current + '-dialog-title'
    dialog.setAttribute('aria-labelledby', title.id)
  }
  dialog.setAttribute('role', 'dialog')
  dialog.setAttribute('aria-modal', 'true')
  dialog.setAttribute('tabindex', '-1')
  ;(focusableIn(dialog)[0] ?? dialog).focus()
}, { flush: 'post' })
const isCredentialChannel = (type: ChannelType) => ['line', 'email', 'sms'].includes(type)
const showTemplates = ref(false)
const types: { type: ChannelType; title: string; icon: string; description: string }[] = [
  { type: 'messenger', title: 'Facebook 专页', icon: 'f', description: '专页官方授权 · 个人私信未接通' },
  { type: 'whatsapp', title: 'WhatsApp Business', icon: 'W', description: '企业账号 · 官方授权待配置' },
  { type: 'instagram', title: 'Instagram', icon: '◎', description: '专业账号' },
  { type: 'telegram', title: 'Telegram', icon: '➤', description: '个人连接待批 | 机器人另选' },
  { type: 'line', title: 'LINE', icon: 'L', description: '官方账号' },
  { type: 'email', title: 'Email', icon: '@', description: '选择邮箱服务商' },
  { type: 'sms', title: 'SMS', icon: '#', description: '按支持方式接入号码' },
  { type: 'slack', title: 'Slack', icon: 'S', description: '工作区授权' },
]
const metaTypes = ['messenger', 'whatsapp', 'instagram']
const byChannel = (type: ChannelType) => accounts.value.filter(account => account.channel_type === type)
const whatsappAccounts = computed(() => byChannel('whatsapp'))
function stateOf(account: ChannelAccount): string {
  // Provider failure is authoritative even if a stale readiness field says ready.
  if (account.provider_health?.reconnect_needed || account.provider_health?.last_provider_error) return '需要检查'
  if (!account.is_active) return '需要处理'
  const readiness = account.provider_health?.readiness
  if (readiness && ['ready', 'connected', 'healthy'].includes(readiness.toLowerCase())) return '提供商就绪'
  return '已启用 · 未验证实时收发'
}
async function loadAccounts() {
  loading.value = true
  error.value = ''
  try { accounts.value = await channelsService.listAccounts() }
  catch { accounts.value = []; error.value = '无法读取平台账号，请检查本机服务后重试。' }
  finally { loading.value = false }
}
function openModal(type: ChannelType, account: ChannelAccount | null = null) {
  launchFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  launchChannel = type in nativeDialogSelectors ? type as FocusChannel : null
  if (account && isCredentialChannel(type)) {
    // No update-by-account-id credential path exists in the native modal.
    // Never let "manage existing" fall into connectEmail/Sms/Line POST.
    selectedChannel.value = null
    selectedAccount.value = null
    readOnlyAccount.value = account
    return
  }
  readOnlyAccount.value = null
  selectedChannel.value = type
  selectedAccount.value = account
}
function addAccount(type: ChannelType) {
  // The approved first step is a truthful identity/authorization qualification
  // surface. It does not persist account state or invoke the provider.
  guideLauncher = document.activeElement instanceof HTMLElement ? document.activeElement : null
  guideChannel.value = type
}
const closeGuide = async () => {
  guideChannel.value = null
  await nextTick()
  if (guideLauncher?.isConnected && !guideLauncher.hasAttribute('disabled')) guideLauncher.focus({preventScroll:true})
  guideLauncher = null
}
const proceedGuide = (type: ChannelType) => {
  if (guideChannel.value !== type) return
  guideChannel.value = null
  if (type === 'slack') {
    guideLauncher = null
    // Native Slack account installation URL remains owned by channelsService.
    window.location.assign(channelsService.getSlackInstallUrl())
    return
  }
  // Keep original launcher identity, not focus on the guide's Continue button.
  const trigger = guideLauncher
  guideLauncher = null
  openModal(type)
  if (trigger?.isConnected) {
    launchFocus = trigger
    launchChannel = type as FocusChannel
  }
}
async function closeModal() {
  if (closingModal) return
  closingModal = true
  readOnlyAccount.value = null
  selectedChannel.value = null
  selectedAccount.value = null
  try {
    // Native refresh disables launchers; restore only after their real state returns.
    await loadAccounts()
  } finally {
    await restoreLaunchFocus()
    closingModal = false
  }
}
function onConnected() { closeModal() }
async function disconnect(account: ChannelAccount) {
  if (!window.confirm(`确定移除“${account.display_name || account.external_account_id}”吗？这会断开该账号，可能影响消息收发。`)) return
  busyAccount.value = account.id
  error.value = ''
  try {
    switch (account.channel_type) {
      case 'messenger': case 'instagram': await channelsService.disconnectMeta(account.id); break
      case 'whatsapp': await channelsService.disconnectWhatsApp(account.id); break
      case 'telegram': await channelsService.disconnectTelegram(account.id); break
      case 'line': await channelsService.disconnectLine(account.id); break
      case 'email': await channelsService.disconnectEmail(account.id); break
      case 'sms': await channelsService.disconnectSms(account.id); break
      case 'slack': await channelsService.disconnectSlack(account.id); break
      default: throw new Error('当前平台不支持从此处断开')
    }
    await loadAccounts()
  } catch { error.value = '断开失败，账号可能仍在连接中。请重试或检查平台。' }
  finally { busyAccount.value = '' }
}
async function reconnectWhatsApp(account: ChannelAccount) {
  busyAccount.value = account.id
  error.value = ''
  try { await channelsService.reconnectWhatsApp(account.id); await loadAccounts() }
  catch { error.value = '此 WhatsApp 账号重新连接失败，请检查该账号凭据与提供商状态。' }
  finally { busyAccount.value = '' }
}
onMounted(() => {
  void loadAccounts()
  document.addEventListener('keydown', onNativeModalKeys, true)
  document.addEventListener('focusin', onNativeModalFocus, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onNativeModalKeys, true)
  document.removeEventListener('focusin', onNativeModalFocus, true)
})
</script>
<template>
  <DashboardLayout>
    <YanceWebShell :connection-summary="error ? '平台状态读取失败' : loading ? '正在读取平台账号' : !accounts.length ? '尚未配置平台账号' : '账号记录已读取，收发健康待验证'">
    <main class="platform-manager" data-yance-platform-accounts :class="{ 'w370-email-active': selectedChannel==='email' }" @keydown.esc="closeModal">
      <header class="platform-head">
        <div><p>平台连接 · 当前没有实际登录账号</p><h1>平台账号</h1></div>
        <nav aria-label="平台管理导航">
          <button type="button" @click="router.push('/yance/home')">首页</button>
          <button type="button" @click="router.push('/yance/settings')">设置</button>
        </nav>
      </header>
      <p v-if="loading" role="status">正在读取平台账号…</p>
      <div v-if="error" role="alert" class="platform-error">{{ error }} <button type="button" @click="loadAccounts">重试</button></div>
      <p v-else-if="!loading && !accounts.length" class="platform-note" data-platform-empty>尚未添加消息平台账号。以下为可选连接入口，实际授权状态以平台返回为准。</p>
      <div class="w371-platform-grid" data-w371-platform-cards>
      <section v-for="type in types" v-if="!error" :key="type.type" class="platform-section" :data-platform-type="type.type">
        <header class="w371-platform-card-heading"><span class="w371-platform-icon" aria-hidden="true">{{ type.icon }}</span>
          <h2>{{ type.title }}</h2><button v-if="byChannel(type.type).length" type="button" :data-yance-channel-launcher="type.type" :disabled="loading" @click="addAccount(type.type)">添加账号</button></header>
        <p class="w371-platform-description">{{ type.description }}</p>
        <p v-if="!loading && !byChannel(type.type).length" class="w371-platform-status">尚未配置</p>
        <ul v-else>
          <li v-for="account in byChannel(type.type)" :key="account.id">
            <span class="account-label"><strong>{{ account.display_name || account.external_account_id || type.title }}</strong><small>{{ stateOf(account) }}</small></span>
            <button type="button" :disabled="!!busyAccount" @click="openModal(type.type, account)">{{ isCredentialChannel(type.type) ? '查看账号' : '管理' }}</button>
            <button v-if="type.type === 'whatsapp'" type="button" :disabled="!!busyAccount" @click="reconnectWhatsApp(account)">重新连接</button>
            <button type="button" class="danger" :disabled="!!busyAccount" @click="disconnect(account)">移除</button>
          </li>
        </ul>
        <button v-if="!byChannel(type.type).length" type="button" class="w371-platform-action" :data-yance-channel-launcher="type.type" :disabled="loading" @click="addAccount(type.type)">查看连接方式</button>
      </section>
      </div>
      <section v-if="!error" class="w371-platform-explainer" data-w371-platform-login-note>
        <h2>用户登录 / 消息能力核验</h2>
        <p>先选择个人、商业专页或机器人。个人 Telegram/WhatsApp 扫码尚未通过验收；专页及商业账号按官方授权。登录身份不等于有消息收发权限。</p>
      </section>
      <p v-if="!error" class="platform-note" data-personal-whatsapp-truth>个人 WhatsApp 扫码目前不可用，不展示虚假二维码。</p>
      <button v-if="!error && whatsappAccounts.length" type="button" @click="showTemplates=true">查看 WhatsApp 模板</button>
      <div v-if="readOnlyAccount" class="readonly-backdrop" @click.self="closeModal">
        <section class="readonly-account-dialog" role="dialog" aria-modal="true" aria-labelledby="readonly-account-heading" data-yance-existing-credential-safe-view>
          <h2 id="readonly-account-heading">查看现有{{ readOnlyAccount.channel_type.toUpperCase() }}账号</h2>
          <p><strong>{{ readOnlyAccount.display_name || readOnlyAccount.external_account_id }}</strong></p>
          <p>账号标识：{{ readOnlyAccount.external_account_id }}</p>
          <p>当前状态：{{ stateOf(readOnlyAccount) }}</p>
          <p class="platform-error">当前原生配置组件不支持按此账号 ID 安全更新凭据。凭据重配暂不可用，避免把已有账号误提交为新账号。若需移除，请返回列表并明确确认。</p>
          <button type="button" @click="closeModal">关闭</button>
        </section>
      </div>
      <YancePlatformConnectionGuide v-if="guideChannel" :channel="guideChannel" @close="closeGuide" @continue="proceedGuide" />
      <MetaChannelConnect
        v-if="selectedChannel && metaTypes.includes(selectedChannel)"
        :key="selectedAccount?.id || selectedChannel"
        :channel="selectedChannel as 'whatsapp' | 'messenger' | 'instagram'"
        :existing-account="selectedAccount"
        @close="closeModal" @connected="onConnected" @account-updated="onConnected" @connection-failed="loadAccounts"
      />
      <TelegramConnectModal v-if="selectedChannel === 'telegram'" :key="selectedAccount?.id || 'telegram'" :existing-account="selectedAccount" @close="closeModal" @connected="onConnected" />
      <ChannelConnectModal
        v-if="selectedChannel && ['line','email','sms','slack'].includes(selectedChannel)"
        :key="selectedAccount?.id || selectedChannel"
        :channel="selectedChannel as 'line' | 'email' | 'sms' | 'slack'"
        :existing-account="selectedAccount"
        @close="closeModal" @connected="onConnected"
      />
      <WhatsAppTemplateManager v-if="showTemplates" :accounts="whatsappAccounts" @close="showTemplates=false" />
    </main>
      </YanceWebShell>
  </DashboardLayout>
</template>
<style scoped>
.platform-manager{width:min(960px,calc(100% - 28px));margin:0 auto;padding:24px 0 36px;color:var(--text)}
.platform-head{display:flex;align-items:start;justify-content:space-between;gap:10px;flex-wrap:wrap}
.platform-head h1{margin:0;font-size:26px}
.platform-head p,.platform-head span,.platform-section p{color:var(--muted);font-size:12px}
.platform-head nav,.platform-section header{display:flex;gap:9px;align-items:center;justify-content:space-between}
button{padding:7px 12px;cursor:pointer;background:var(--bg2);color:var(--text);border:1px solid var(--o14);border-radius:8px}
button:disabled{opacity:.45;cursor:default}
.platform-section{background:var(--bg2);border:1px solid var(--o10);border-radius:12px;margin:12px 0;padding:12px}
.platform-section h2{font-size:16px;margin:0}
.platform-section ul{list-style:none;margin:10px 0 0;padding:0}
.platform-section li{display:flex;align-items:center;gap:8px;padding:9px 0;border-top:1px solid var(--o10);flex-wrap:wrap}
.account-label{flex:1;min-width:155px;display:flex;flex-direction:column;gap:4px;overflow-wrap:anywhere}
.account-label small{font-size:11px;color:var(--muted)}
.platform-error{padding:12px;color:var(--warning)}
.platform-note{color:var(--muted)}
.danger{color:var(--warning)}
 .readonly-backdrop{position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;padding:16px}
.readonly-account-dialog{width:min(480px,100%);background:var(--bg2);color:var(--text);border:1px solid var(--o14);border-radius:12px;padding:22px;overflow-wrap:anywhere}
.readonly-account-dialog h2{font-size:18px;margin:0 0 12px}
.readonly-account-dialog p{font-size:13px;line-height:1.5}
.w370-email-active :deep(.cc-modal-content){max-height:calc(100dvh - 24px);padding:14px 16px}
.w370-email-active :deep(.cc-modal-header){margin-bottom:7px}
.w370-email-active :deep(.cc-intro){font-size:11px;line-height:1.4;margin-bottom:8px}
.w370-email-active :deep(.cc-field){margin-bottom:7px}
.w370-email-active :deep(.cc-label){font-size:11px;margin-bottom:3px}
.w370-email-active :deep(.cc-input){padding:6px 9px;font-size:12px}
.w370-email-active :deep(.cc-actions){position:sticky;bottom:0;z-index:1;display:flex;justify-content:flex-end;align-items:center;background:var(--background-color,#1d1b25);padding:8px 0 2px;margin-top:8px;min-height:48px}
.w370-email-active :deep(.cc-btn){padding:7px 12px;font-size:12px}
.w370-email-active :deep(.cc-btn-primary){background:#775736;color:#fff2d7;border:1px solid #b9925f}
@media(max-width:560px){.platform-head nav{width:100%}}
</style>
