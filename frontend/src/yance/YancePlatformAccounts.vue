<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import channelsService, { type ChannelAccount, type ChannelType } from '@/services/channels'
import MetaChannelConnect from '@/components/integrations/MetaChannelConnect.vue'
import TelegramConnectModal from '@/components/integrations/TelegramConnectModal.vue'
import ChannelConnectModal from '@/components/integrations/ChannelConnectModal.vue'
import WhatsAppTemplateManager from '@/components/integrations/WhatsAppTemplateManager.vue'

const router = useRouter()
const accounts = ref<ChannelAccount[]>([])
const loading = ref(true)
const error = ref('')
const busyAccount = ref('')
const selectedChannel = ref<ChannelType | null>(null)
const selectedAccount = ref<ChannelAccount | null>(null)
// Native credential-modal reconfigure drops its existing-account identity and can POST
// a new Email/SMS/LINE account. Existing rows therefore use a safe read-only view.
const readOnlyAccount = ref<ChannelAccount | null>(null)
const isCredentialChannel = (type: ChannelType) => ['line', 'email', 'sms'].includes(type)
const showTemplates = ref(false)
const types: { type: ChannelType; title: string }[] = [
  { type: 'messenger', title: 'Facebook 专页（Messenger）' },
  { type: 'whatsapp', title: 'WhatsApp Business' },
  { type: 'instagram', title: 'Instagram' },
  { type: 'telegram', title: 'Telegram' },
  { type: 'line', title: 'LINE' },
  { type: 'email', title: 'Email' },
  { type: 'sms', title: 'SMS' },
  { type: 'slack', title: 'Slack' },
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
  if (type === 'slack') {
    if (window.confirm('接下来会打开 Slack 官方授权流程。确认前往授权页面吗？')) {
      window.location.assign(channelsService.getSlackInstallUrl())
    }
    return
  }
  openModal(type)
}
function closeModal() {
  readOnlyAccount.value = null
  selectedChannel.value = null
  selectedAccount.value = null
  void loadAccounts()
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
onMounted(() => { void loadAccounts() })
</script>
<template>
  <DashboardLayout>
    <main class="platform-manager" data-yance-platform-accounts @keydown.esc="closeModal">
      <header class="platform-head">
        <div><p>言策 Yance</p><h1>消息平台账号</h1><span>管理真实平台连接。已启用不代表外部 Webhook 或实时收发已验证。</span></div>
        <nav aria-label="平台管理导航">
          <button type="button" @click="router.push('/yance/home')">首页</button>
          <button type="button" @click="router.push('/yance/settings')">设置</button>
        </nav>
      </header>
      <p v-if="loading" role="status">正在读取平台账号…</p>
      <div v-if="error" role="alert" class="platform-error">{{ error }} <button type="button" @click="loadAccounts">重试</button></div>
      <p v-else-if="!loading && !accounts.length" class="platform-note" data-platform-empty>尚未添加消息平台账号。可选择下方平台开始连接。</p>
      <section v-for="type in types" v-if="!error" :key="type.type" class="platform-section" :data-platform-type="type.type">
        <header>
          <h2>{{ type.title }}</h2>
          <button type="button" :disabled="loading" @click="addAccount(type.type)">添加账号</button>
        </header>
        <p v-if="type.type === 'messenger'" class="platform-note">仅连接 Facebook 专页的 Messenger 消息，不是个人 Messenger。专页授权需要 Meta 应用配置，实际收发以 Webhook 验证为准。</p>
        <p v-if="type.type === 'whatsapp'" class="platform-note" data-personal-whatsapp-truth>此处连接 WhatsApp Business（官方 Cloud API）。个人 WhatsApp 扫码连接尚未通过安全及收发验收，当前不可用，不会显示虚假二维码。</p>
        <p v-if="!loading && !byChannel(type.type).length">尚未配置</p>
        <ul v-else>
          <li v-for="account in byChannel(type.type)" :key="account.id">
            <span class="account-label"><strong>{{ account.display_name || account.external_account_id || type.title }}</strong><small>{{ stateOf(account) }}</small></span>
            <button type="button" :disabled="!!busyAccount" @click="openModal(type.type, account)">{{ isCredentialChannel(type.type) ? '查看账号' : '管理' }}</button>
            <button v-if="type.type === 'whatsapp'" type="button" :disabled="!!busyAccount" @click="reconnectWhatsApp(account)">重新连接</button>
            <button type="button" class="danger" :disabled="!!busyAccount" @click="disconnect(account)">移除</button>
          </li>
        </ul>
      </section>
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
@media(max-width:560px){.platform-head nav{width:100%}}
</style>
