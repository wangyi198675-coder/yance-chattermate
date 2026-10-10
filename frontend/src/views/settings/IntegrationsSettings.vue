<!--
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { checkJiraConnection, getJiraAuthUrl, disconnectJira } from '@/services/jira'
import { checkShopifyConnection, getShopifyShops } from '@/services/shopify'
import channelsService, { type ChannelAccount } from '@/services/channels'
import { lineAccountState } from '@/utils/lineAccountState'
import { facebookMessengerConnectionState } from '@/yance/facebookMessengerConnectionState'
import crmService, { type CrmConnection, type CrmProvider } from '@/services/crm'
import TelegramConnectModal from '@/components/integrations/TelegramConnectModal.vue'
import MetaChannelConnect from '@/components/integrations/MetaChannelConnect.vue'
import WhatsAppTemplateManager from '@/components/integrations/WhatsAppTemplateManager.vue'
import ChannelConnectModal from '@/components/integrations/ChannelConnectModal.vue'

// Import logos
import jiraLogo from '@/assets/jira-logo.svg'
import chattermateLogo from '@/assets/logo.svg'
import slackLogo from '@/assets/slack-logo.svg'
import zendeskLogo from '@/assets/zendesk-logo.svg'
import shopifyLogo from '@/assets/shopify-logo.svg'
import telegramLogo from '@/assets/telegram-logo.svg'
import whatsappLogo from '@/assets/whatsapp-logo.svg'
import messengerLogo from '@/assets/messenger-logo.svg'
import instagramLogo from '@/assets/instagram-logo.svg'
import emailLogo from '@/assets/email-logo.svg'
import smsLogo from '@/assets/sms-logo.svg'
import lineLogo from '@/assets/line-logo.svg'
import hubspotLogo from '@/assets/hubspot-logo.svg'
import pipedriveLogo from '@/assets/pipedrive-logo.svg'

// Define interface for Shopify shop
interface ShopifyShop {
  id: string
  shop_domain: string
  is_installed: boolean
  [key: string]: any
}

// Shopify state variables
const shopifyConnected = ref(false)
const shopifyShopDomain = ref('')
const shopifyLoading = ref(true)

// Messaging channel state (Telegram + Meta channels share one accounts list)
const channelAccounts = ref<ChannelAccount[]>([])
const channelsLoading = ref(true)
const showTelegramModal = ref(false)
// Which Meta connect modal is open (null = none)
const metaModalChannel = ref<'whatsapp' | 'messenger' | 'instagram' | null>(null)
const showTemplateManager = ref(false)
// Which credential connect modal is open (null = none)
const credentialModalChannel = ref<'email' | 'sms' | 'line' | 'slack' | null>(null)
// Account being managed (null = fresh connect). Also used for Telegram/Meta manage.
const credentialModalAccount = ref<ChannelAccount | null>(null)
const lineAccountToDisconnect = ref<ChannelAccount | null>(null)
const telegramModalAccount = ref<ChannelAccount | null>(null)
const metaModalAccount = ref<ChannelAccount | null>(null)
// Slack has one account per workspace. Never manage/disconnect listAccounts()[0]
// or all Slack accounts as a single integration.
const slackDisconnectAccount = ref<ChannelAccount | null>(null)
const metaReconnectAccount = ref<ChannelAccount | null>(null)
const disconnectingInstagramAccountId = ref<string | null>(null)

// WhatsApp multi-account lifecycle stays a thin UI over the canonical
// ChannelAccount routes. No client-side account registry or credential truth.
const whatsappActionAccountId = ref<string | null>(null)
const whatsappRotateAccount = ref<ChannelAccount | null>(null)
const whatsappRotateToken = ref('')
const whatsappRotateWabaId = ref('')
const whatsappDisconnectAccount = ref<ChannelAccount | null>(null)

const CREDENTIAL_CHANNELS = ['email', 'sms', 'line']
const META_CHANNELS = ['whatsapp', 'messenger', 'instagram']
const CRM_PROVIDERS: CrmProvider[] = ['hubspot', 'pipedrive']

// CRM lead-push connections
const crmConnections = ref<CrmConnection[]>([])
const crmLoading = ref(true)
// 403 from the connections endpoint = plan doesn't include crm_sync
const crmUpgradeMessage = ref<string | null>(null)

const crmFor = (provider: CrmProvider) =>
  crmConnections.value.find(c => c.provider === provider) ?? null

const fetchCrmConnections = async () => {
  try {
    crmLoading.value = true
    crmConnections.value = await crmService.listConnections()
    crmUpgradeMessage.value = null
  } catch (error: any) {
    if (error?.response?.status === 403) {
      crmUpgradeMessage.value = error.response?.data?.detail || 'CRM sync is not available in your current plan.'
    } else {
      console.error('Error loading CRM connections:', error)
    }
  } finally {
    crmLoading.value = false
  }
}

const connectCrm = (provider: CrmProvider) => {
  if (crmUpgradeMessage.value) {
    toast.error(crmUpgradeMessage.value)
    return
  }
  window.location.href = crmService.getInstallUrl(provider)
}

const testCrm = async (provider: CrmProvider) => {
  try {
    const result = await crmService.testConnection(provider)
    if (result.ok) {
      toast.success(`Connected to ${result.account_name || provider}`)
    } else {
      toast.error(result.error || `${provider} connection check failed`)
    }
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || `${provider} connection check failed`)
  }
}

const handleDisconnectCrm = async (provider: CrmProvider) => {
  try {
    crmLoading.value = true
    await crmService.disconnect(provider)
    crmConnections.value = crmConnections.value.filter(c => c.provider !== provider)
    toast.success(`${provider === 'hubspot' ? 'HubSpot' : 'Pipedrive'} disconnected successfully`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || `Error disconnecting ${provider}`)
  } finally {
    crmLoading.value = false
    showDisconnectConfirm.value = false
    disconnectingIntegration.value = null
  }
}

const crmCardWarning = (connection: CrmConnection | null): string | undefined => {
  if (!connection) return undefined
  if (connection.status !== 'active') {
    return 'Connection expired — reconnect to resume lead sync.'
  }
  if (connection.recent_failures > 0) {
    return `${connection.recent_failures} lead${connection.recent_failures === 1 ? '' : 's'} failed to sync in the last 7 days.`
  }
  return undefined
}

// "Manage" on a connected card: open the right modal for the connected account
const manageSlackAccount = (account: ChannelAccount) => {
  credentialModalAccount.value = account
  credentialModalChannel.value = 'slack'
}

const openMetaAccount = (
  channel: 'whatsapp' | 'messenger' | 'instagram',
  account: ChannelAccount | null = null,
) => {
  metaModalAccount.value = account
  metaModalChannel.value = channel
}

// "Manage" on a connected card: open the right modal for the connected account.
// Messenger renders one action row per Page below, so its generic card action is
// reserved for adding another Page rather than silently choosing accountsFor()[0].
const manageIntegration = (integration: IntegrationCard) => {
  const id = integration.id
  if (id === 'whatsapp') {
    toast.info('Select an individual WhatsApp number below.')
    return
  }
  const acc = accountsFor(id)[0] ?? null
  if (CREDENTIAL_CHANNELS.includes(id)) {
    credentialModalAccount.value = acc
    credentialModalChannel.value = id as 'email' | 'sms' | 'line'
  } else if (id === 'telegram') {
    telegramModalAccount.value = acc
    showTelegramModal.value = true
  } else if (META_CHANNELS.includes(id)) {
    metaReconnectAccount.value = null
    openMetaAccount(id as 'whatsapp' | 'messenger' | 'instagram', acc)
  } else if (id === 'slack') {
    // Only a single exact workspace can be managed at a time.
    if (accountsFor('slack').length === 1 && acc) manageSlackAccount(acc)
  } else if (CRM_PROVIDERS.includes(id as CrmProvider)) {
    // CRM Manage = read-only connectivity check, surfaced as a toast
    testCrm(id as CrmProvider)
  } else {
    // Jira/Shopify: re-run their connect/OAuth flow
    if (id === 'shopify') openShopifyInstallation()
    else integration.connectAction?.()
  }
}

const accountsFor = (channelType: string) =>
  channelAccounts.value.filter(a => a.channel_type === channelType)

// A persisted row is not evidence of a usable number. Registration/reconnect
// failures retain their ChannelAccount for repair but must never count as live.
const whatsappAccountUsable = (account: ChannelAccount): boolean => {
  if (!account.is_active) return false
  const health = account.provider_health
  if (health?.reconnect_needed || health?.credential_status === 'INVALID'
      || health?.phone_registration === 'ACTION_REQUIRED'
      || health?.waba_subscription === 'ACTION_REQUIRED') return false
  // Legacy accounts have only is_active; explicit non-READY health is never
  // silently upgraded to Connected, including DEGRADED or ACTION_REQUIRED.
  return !health?.readiness || health.readiness === 'READY'
}

const whatsappRowStatus = (account: ChannelAccount): string =>
  whatsappAccountUsable(account) ? 'Connected' : 'Needs attention'

const telegramAccounts = computed(() => accountsFor('telegram'))
const messengerState = computed(() => facebookMessengerConnectionState(accountsFor('messenger')))
const instagramAccounts = computed(() => accountsFor('instagram'))

const openInstagramAccount = (account: ChannelAccount) => {
  metaModalAccount.value = account
  metaReconnectAccount.value = null
  metaModalChannel.value = 'instagram'
}

const openInstagramReconnect = (account: ChannelAccount) => {
  metaModalAccount.value = null
  metaReconnectAccount.value = account
  metaModalChannel.value = 'instagram'
}

const openInstagramConnect = () => {
  metaModalAccount.value = null
  metaReconnectAccount.value = null
  metaModalChannel.value = 'instagram'
}

const fetchChannelAccounts = async () => {
  try {
    channelsLoading.value = true
    channelAccounts.value = await channelsService.listAccounts()
  } catch (error) {
    console.error('Error loading channel accounts:', error)
  } finally {
    channelsLoading.value = false
  }
}

// Component-local async ordering only; Meta / ChannelAccount remain the status authority.
// Both account ID and Page ID are tracked because an initial failed subscription
// may only know the external Page ID, while reconnect returns the native account.
let messengerPageEpoch = 0
const messengerPageEpochs = new Map<string, number>()
const pageEpochKeys = (id?: string, externalId?: string) => [
  ...(id ? [`account:${id}`] : []),
  ...(externalId ? [`page:${externalId}`] : []),
]
const advancePageEpoch = (id?: string, externalId?: string) => {
  const epoch = ++messengerPageEpoch
  for (const key of pageEpochKeys(id, externalId)) messengerPageEpochs.set(key, epoch)
  return epoch
}

// A failed subscribe_app may deactivate Page A without a "connected" event.
// Fail-close exact A immediately, reconcile with native ChannelAccount rows,
// and leave sibling Page B intact even if refresh fails.
const onMetaConnectionFailed = async (target: { id?: string; externalAccountId?: string }) => {
  if (!target.id && !target.externalAccountId) return
  const failureEpoch = advancePageEpoch(target.id, target.externalAccountId)
  const failureKeys = pageEpochKeys(target.id, target.externalAccountId)
  const matchesTarget = (account: ChannelAccount) =>
    account.channel_type === 'messenger' && (
      (Boolean(target.id) && account.id === target.id) ||
      (Boolean(target.externalAccountId) && account.external_account_id === target.externalAccountId)
    )
  const failClose = (account: ChannelAccount) =>
    matchesTarget(account) ? { ...account, is_active: false } : account

  channelAccounts.value = channelAccounts.value.map(failClose)
  if (metaModalAccount.value && matchesTarget(metaModalAccount.value)) {
    metaModalAccount.value = failClose(metaModalAccount.value)
  }
  try {
    // Also picks up any Page newly staged inactive by the failed request.
    // Do not revive the failed target from a racing/stale list response.
    const nativeRows = await channelsService.listAccounts()
    // A newer exact-Page event (especially confirmed reconnect success) wins:
    // the old failed request must not re-demote its Page when this await ends.
    if (failureKeys.some(key => messengerPageEpochs.get(key) !== failureEpoch)) return
    channelAccounts.value = nativeRows.map(failClose)
    const refreshed = channelAccounts.value.find(matchesTarget)
    // A slow refresh for A must never replace an already-open B Manage modal.
    if (refreshed && metaModalChannel.value === 'messenger' &&
        (!metaModalAccount.value || matchesTarget(metaModalAccount.value))) {
      metaModalAccount.value = refreshed
    }
  } catch (error) {
    console.error('Error refreshing Facebook Page after failed subscription:', error)
    // The exact target stays Needs attention; no sibling is affected.
  }
}

const onMetaAccountUpdated = async (updated: ChannelAccount) => {
  // Invalidate only this Page's older failed-refresh continuations.
  advancePageEpoch(updated.id, updated.external_account_id)
  // Backend-confirmed subscription: project the exact native result without
  // closing the agent assignment modal, then refresh the ordinary list.
  channelAccounts.value = [
    ...channelAccounts.value.filter(account => account.id !== updated.id),
    updated,
  ]
  metaModalAccount.value = updated
  await fetchChannelAccounts()
}

const replaceChannelAccount = (updated: ChannelAccount) => {
  channelAccounts.value = channelAccounts.value.map(account =>
    account.id === updated.id ? updated : account,
  )
}

// A failed reconnect can deactivate the persisted number before returning an
// error. Invalidate only the affected row immediately, then reconcile it with
// the canonical ChannelAccount list. If that read fails, remain fail-closed;
// never keep a pre-request Connected snapshot as connection authority.
const reconcileFailedWhatsAppReconnect = async (accountId: string) => {
  const target = channelAccounts.value.find(account =>
    account.id === accountId && account.channel_type === 'whatsapp')
  if (target) {
    replaceChannelAccount({
      ...target,
      is_active: false,
      provider_health: {
        ...target.provider_health,
        readiness: 'ACTION_REQUIRED',
        reconnect_needed: true,
      },
    })
  }
  try {
    const refreshed = (await channelsService.listAccounts()).find(account =>
      account.id === accountId && account.channel_type === 'whatsapp')
    // A rejected provider revalidation cannot be overridden by a still-READY
    // snapshot (e.g. an earlier response). Adopt authoritative failure detail;
    // require a subsequent successful reconnect or reload to restore Connected.
    if (refreshed && !whatsappAccountUsable(refreshed)) {
      replaceChannelAccount(refreshed)
    }
  } catch (error) {
    console.error('Could not refresh failed WhatsApp reconnect status:', error)
  }
}

const connectAnotherWhatsApp = () => {
  metaModalAccount.value = null
  metaModalChannel.value = 'whatsapp'
}

const manageWhatsAppAccount = (account: ChannelAccount) => {
  metaModalAccount.value = account
  metaModalChannel.value = 'whatsapp'
}

const reconnectWhatsAppAccount = async (account: ChannelAccount) => {
  try {
    whatsappActionAccountId.value = account.id
    const updated = await channelsService.reconnectWhatsApp(account.id)
    replaceChannelAccount(updated)
    toast.success(`Reconnected ${updated.display_name || updated.external_account_id}`)
  } catch (error: any) {
    await reconcileFailedWhatsAppReconnect(account.id)
    toast.error(error?.response?.data?.detail || 'Could not reconnect this WhatsApp number')
  } finally {
    whatsappActionAccountId.value = null
  }
}

const openWhatsAppRotation = (account: ChannelAccount) => {
  whatsappRotateAccount.value = account
  whatsappRotateToken.value = ''
  whatsappRotateWabaId.value = ''
}

const closeWhatsAppRotation = () => {
  whatsappRotateAccount.value = null
  whatsappRotateToken.value = ''
  whatsappRotateWabaId.value = ''
}

const rotateWhatsAppAccount = async () => {
  const account = whatsappRotateAccount.value
  const accessToken = whatsappRotateToken.value.trim()
  if (!account || !accessToken) return
  try {
    whatsappActionAccountId.value = account.id
    const updated = await channelsService.rotateWhatsAppCredentials(account.id, {
      access_token: accessToken,
      ...(whatsappRotateWabaId.value.trim()
        ? { waba_id: whatsappRotateWabaId.value.trim() }
        : {}),
    })
    replaceChannelAccount(updated)
    closeWhatsAppRotation()
    toast.success(`Updated credentials for ${updated.display_name || updated.external_account_id}`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || 'Could not update this WhatsApp credential')
  } finally {
    whatsappActionAccountId.value = null
  }
}

const requestWhatsAppDisconnect = (account: ChannelAccount) => {
  whatsappDisconnectAccount.value = account
}

const cancelWhatsAppDisconnect = () => {
  whatsappDisconnectAccount.value = null
}

const disconnectWhatsAppAccount = async () => {
  const account = whatsappDisconnectAccount.value
  if (!account) return
  try {
    whatsappActionAccountId.value = account.id
    await channelsService.disconnectWhatsApp(account.id)
    channelAccounts.value = channelAccounts.value.filter(row => row.id !== account.id)
    whatsappDisconnectAccount.value = null
    toast.success(`Disconnected ${account.display_name || account.external_account_id}`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || 'Could not disconnect this WhatsApp number')
  } finally {
    whatsappActionAccountId.value = null
  }
}

const onChannelConnected = async () => {
  showTelegramModal.value = false
  metaModalChannel.value = null
  credentialModalChannel.value = null
  credentialModalAccount.value = null
  telegramModalAccount.value = null
  metaModalAccount.value = null
  metaReconnectAccount.value = null
  await fetchChannelAccounts()
}

// Shared disconnect for messaging channels; Telegram also removes its webhook
const disconnectChannelAccounts = async (channelType: string, label: string) => {
  if (channelType === 'whatsapp') {
    toast.error('Select an individual WhatsApp number to disconnect.')
    return
  }
  try {
    channelsLoading.value = true
    for (const account of accountsFor(channelType)) {
      if (channelType === 'telegram') {
        await channelsService.disconnectTelegram(account.id)
      } else if (channelType === 'slack') {
        await channelsService.disconnectSlack(account.id)
      } else if (channelType === 'email') {
        await channelsService.disconnectEmail(account.id)
      } else if (channelType === 'sms') {
        await channelsService.disconnectSms(account.id)
      } else if (channelType === 'line') {
        await channelsService.disconnectLine(account.id)
      } else {
        await channelsService.disconnectMeta(account.id)
      }
    }
    channelAccounts.value = channelAccounts.value.filter(a => a.channel_type !== channelType)
    toast.success(`${label} disconnected successfully`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || `Error disconnecting ${label}`)
  } finally {
    channelsLoading.value = false
    showDisconnectConfirm.value = false
    disconnectingIntegration.value = null
  }
}

const handleDisconnectTelegram = () => disconnectChannelAccounts('telegram', 'Telegram')
const handleDisconnectSlack = async () => {
  const account = slackDisconnectAccount.value
  if (!account || !accountsFor('slack').some(a => a.id === account.id)) return
  try {
    channelsLoading.value = true
    await channelsService.disconnectSlack(account.id)
    channelAccounts.value = channelAccounts.value.filter(a => a.id !== account.id)
    toast.success(`Disconnected ${account.display_name || account.external_account_id}`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || 'Could not disconnect Slack workspace')
  } finally {
    channelsLoading.value = false
    showDisconnectConfirm.value = false
    disconnectingIntegration.value = null
    slackDisconnectAccount.value = null
  }
}
const connectSlack = () => { window.location.href = channelsService.getSlackInstallUrl() }
const handleDisconnectWhatsApp = () => disconnectChannelAccounts('whatsapp', 'WhatsApp')
const handleDisconnectInstagram = async () => {
  const accountId = disconnectingInstagramAccountId.value
  if (!accountId || !instagramAccounts.value.some(account => account.id === accountId)) return
  try {
    channelsLoading.value = true
    await channelsService.disconnectMeta(accountId)
    await fetchChannelAccounts()
    toast.success('Instagram account disconnected')
    cancelDisconnect()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || 'Could not disconnect this Instagram account')
  } finally {
    channelsLoading.value = false
  }
}

const disconnectMessengerPage = async (account: ChannelAccount) => {
  try {
    channelsLoading.value = true
    await channelsService.disconnectMeta(account.id)
    channelAccounts.value = channelAccounts.value.filter(candidate => candidate.id !== account.id)
    toast.success(`${account.display_name || account.external_account_id || 'Facebook Page'} disconnected successfully`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || 'Error disconnecting Facebook Page')
  } finally {
    channelsLoading.value = false
    showDisconnectConfirm.value = false
    disconnectingIntegration.value = null
    disconnectingAccount.value = null
  }
}
const handleDisconnectEmail = () => disconnectChannelAccounts('email', 'Email')
const handleDisconnectSms = () => disconnectChannelAccounts('sms', 'SMS')
// LINE is account-scoped: never cascade a card-level action across sibling bots.
const manageLineAccount = (account: ChannelAccount) => {
  credentialModalAccount.value = account
  credentialModalChannel.value = 'line'
}
const addLineAccount = () => {
  credentialModalAccount.value = null
  credentialModalChannel.value = 'line'
}
const showLineDisconnect = (account: ChannelAccount) => {
  lineAccountToDisconnect.value = account
  disconnectingIntegration.value = 'line'
  showDisconnectConfirm.value = true
}
const handleDisconnectLine = async () => {
  const account = lineAccountToDisconnect.value
  if (!account) return
  try {
    channelsLoading.value = true
    await channelsService.disconnectLine(account.id)
    await fetchChannelAccounts()
    toast.success(`Disconnected LINE channel ${account.display_name || account.external_account_id}`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || 'Error disconnecting LINE channel')
  } finally {
    channelsLoading.value = false
    showDisconnectConfirm.value = false
    disconnectingIntegration.value = null
    lineAccountToDisconnect.value = null
  }
}


const route = useRoute()
const router = useRouter()

const jiraConnected = ref(false)
const jiraSiteUrl = ref('')
const isLoading = ref(true)
const showDisconnectConfirm = ref(false)
const disconnectingIntegration = ref<string | null>(null)
const disconnectingAccount = ref<ChannelAccount | null>(null)
// OAuth connect error, tagged with the integration it belongs to so the banner
// renders on that card rather than always on Jira's.
const connectionError = ref<{ integration: string; message: string } | null>(null)

// Check if Jira is connected
const fetchJiraStatus = async () => {
  try {
    isLoading.value = true
    const data = await checkJiraConnection()
    jiraConnected.value = data.connected
    jiraSiteUrl.value = data.site_url || ''
  } catch (error) {
    console.error('Error checking Jira connection:', error)
    jiraConnected.value = false
  } finally {
    isLoading.value = false
  }
}

// Connect to Jira
const connectJira = () => {
  try {
    // Clear any previous error messages
    connectionError.value = null
    window.location.href = getJiraAuthUrl()
  } catch (error) {
    console.error('Error connecting to Jira:', error)
    toast.error('Error connecting to Jira')
  }
}

const showDisconnectConfirmation = (
  integrationId: string,
  target: ChannelAccount | string | null = null,
) => {
  if (integrationId === 'instagram' && (typeof target !== 'string' || !instagramAccounts.value.some(a => a.id === target))) return
  disconnectingInstagramAccountId.value = integrationId === 'instagram' ? (target as string) : null
  const account = typeof target === 'string' ? null : target
  disconnectingIntegration.value = integrationId
  disconnectingAccount.value = account
  showDisconnectConfirm.value = true
}

const confirmSlackDisconnect = (account: ChannelAccount) => {
  slackDisconnectAccount.value = account
  showDisconnectConfirmation('slack')
}

// Cancel disconnect
const cancelDisconnect = () => {
  disconnectingInstagramAccountId.value = null
  showDisconnectConfirm.value = false
  disconnectingIntegration.value = null
  lineAccountToDisconnect.value = null
  slackDisconnectAccount.value = null
  disconnectingAccount.value = null
}

// Disconnect from Jira
const handleDisconnectJira = async () => {
  try {
    isLoading.value = true
    await disconnectJira()
    jiraConnected.value = false
    jiraSiteUrl.value = ''
    toast.success('Jira disconnected successfully')
  } catch (error: any) {
    console.error('Error disconnecting from Jira:', error)
    let errorMessage = 'Error disconnecting from Jira'
    
    // Try to extract a more detailed error message if available
    if (error.response && error.response.data && error.response.data.detail) {
      errorMessage = error.response.data.detail
    }
    
    toast.error(errorMessage)
  } finally {
    isLoading.value = false
    showDisconnectConfirm.value = false
    disconnectingIntegration.value = null
  }
}

// Check if Shopify is connected
const fetchShopifyStatus = async () => {
  try {
    shopifyLoading.value = true
    const data = await checkShopifyConnection()
    shopifyConnected.value = data.connected
    shopifyShopDomain.value = data.shop_domain || ''
  } catch (error) {
    console.error('Error checking Shopify connection:', error)
    shopifyConnected.value = false
  } finally {
    shopifyLoading.value = false
  }
}


// Open Shopify installation page
const openShopifyInstallation = () => {
  try {
    // Direct installation URL provided by Shopify
    const installUrl = 'https://admin.shopify.com/?organization_id=162380510&no_redirect=true&redirect=/oauth/redirect_from_developer_dashboard?client_id%3D280379be88b01dbdde1bcf06c027b1d4'
    
    // Open in new tab
    window.open(installUrl, '_blank')
    
    // Show helpful message
    toast.info('Redirected to Shopify for app installation. After installation, refresh this page to see the connection status.')
  } catch (error: any) {
    console.error('Error opening Shopify installation:', error)
    toast.error('Error opening Shopify installation page')
  }
}

// Disconnect from Shopify - redirect to Shopify admin to uninstall
const handleDisconnectShopify = () => {
  try {
    // Close the modal
    showDisconnectConfirm.value = false
    disconnectingIntegration.value = null

    // Open Shopify admin apps page in a new tab where user can uninstall the app
    const shopifyAdminUrl = `https://${shopifyShopDomain.value}/admin/apps`
    window.open(shopifyAdminUrl, '_blank')

    // Show a helpful toast message
    toast.info('Please uninstall the ChatterMate app from your Shopify admin to complete the disconnection.')
  } catch (error: any) {
    console.error('Error opening Shopify admin:', error)
    toast.error('Error opening Shopify admin')
    showDisconnectConfirm.value = false
    disconnectingIntegration.value = null
  }
}

// Define interface for IntegrationCard
interface IntegrationCard {
  id: string;
  name: string;
  description: string;
  logo: string;
  connected: boolean;
  needsAttention?: boolean;
  /** WhatsApp distinguishes saved inactive rows from no configuration. */
  statusLabel?: string;
  isLoading?: boolean;
  siteUrl?: string;
  shopDomain?: string;
  teamName?: string;
  comingSoon?: boolean;
  category?: string;
  color?: string;
  /** Inline warning under the description (expired connection, sync failures). */
  warning?: string;
  connectAction?: () => void;
  disconnectAction?: () => void;
  /** An extra action on the connected card, alongside Manage/Disconnect. */
  extraActionLabel?: string;
  extraAction?: () => void;
}

// List of available integrations
const availableIntegrations = computed<IntegrationCard[]>(() => [
  {
    id: 'jira',
    name: 'Jira',
    description: 'Connect to Jira to create issues directly from ChatterMate.',
    logo: jiraLogo,
    category: 'PROJECT MANAGEMENT',
    color: 'purple',
    connected: jiraConnected.value,
    siteUrl: jiraSiteUrl.value,
    isLoading: isLoading.value,
    connectAction: connectJira,
    disconnectAction: handleDisconnectJira
  },
  {
    id: 'shopify',
    name: 'Shopify',
    description: 'Install from Shopify App Store to integrate your store with ChatterMate.',
    logo: shopifyLogo,
    category: 'E-COMMERCE',
    color: 'teal',
    connected: shopifyConnected.value,
    shopDomain: shopifyShopDomain.value,
    isLoading: shopifyLoading.value,
    disconnectAction: handleDisconnectShopify
  },
  {
    id: 'slack',
    name: 'Slack',
    description: 'Connect a Slack workspace so users can chat with your AI agent via @mentions and DMs.',
    logo: slackLogo,
    category: 'MESSAGING',
    color: 'accent',
    connected: accountsFor('slack').some(a => a.is_active),
    needsAttention: accountsFor('slack').some(a => !a.is_active),
    // Exact workspace names and team ids are rendered per account below.
    teamName: undefined,
    isLoading: channelsLoading.value,
    connectAction: connectSlack,
    disconnectAction: handleDisconnectSlack
  },
  {
    id: 'telegram',
    name: 'Telegram',
    description: 'Connect a Telegram bot so customers can chat with your AI agent on Telegram.',
    logo: telegramLogo,
    category: 'MESSAGING',
    color: 'accent',
    connected: telegramAccounts.value.length > 0,
    teamName: telegramAccounts.value.map(a => a.display_name).filter(Boolean).join(', '),
    isLoading: channelsLoading.value,
    connectAction: () => { showTelegramModal.value = true },
    disconnectAction: handleDisconnectTelegram
  },
  ...(['whatsapp', 'messenger', 'instagram'] as const).map(channel => {
    const meta = {
      whatsapp: { name: 'WhatsApp', logo: whatsappLogo, color: 'teal',
        description: 'Let customers message your AI agent on WhatsApp Business.',
        disconnect: undefined },
      messenger: { name: 'Messenger', logo: messengerLogo, color: 'accent',
        description: 'Let customers chat with your AI agent on Facebook Messenger.',
        disconnect: undefined },
      instagram: { name: 'Instagram', logo: instagramLogo, color: 'purple',
        description: 'Let customers DM your AI agent on Instagram.',
        disconnect: handleDisconnectInstagram },
    }[channel]
    const accounts = accountsFor(channel)
    return {
      id: channel,
      name: meta.name,
      description: meta.description,
      logo: meta.logo,
      category: 'MESSAGING',
      color: meta.color,
      connected: channel === 'messenger'
        ? messengerState.value.connected
        : channel === 'whatsapp'
          ? accounts.some(whatsappAccountUsable)
          : channel === 'instagram'
            ? accounts.some(a => a.is_active)
            : accounts.length > 0,
      needsAttention: channel === 'instagram' && accounts.some(a => !a.is_active),
      ...(channel === 'whatsapp' ? {
        statusLabel: accounts.length ? 'Needs attention' : 'Not configured',
      } : {}),
      teamName: accounts.map(a => a.display_name).filter(Boolean).join(', '),
      isLoading: channelsLoading.value,
      connectAction: () => {
        if (channel === 'whatsapp') connectAnotherWhatsApp()
        else { metaReconnectAccount.value = null; metaModalAccount.value = null; metaModalChannel.value = channel }
      },
      disconnectAction: meta.disconnect,
      // Templates are WhatsApp-only — the other Meta channels have no equivalent.
      ...(channel === 'whatsapp' && accounts.length > 0
        ? { extraActionLabel: 'Templates', extraAction: () => { showTemplateManager.value = true } }
        : {})
    }
  }),
  ...(['email', 'sms', 'line'] as const).map(channel => {
    const meta = {
      email: { name: 'Email', logo: emailLogo, color: 'purple',
        description: 'Connect a support inbox so email conversations are answered by your AI agent.',
        disconnect: handleDisconnectEmail },
      sms: { name: 'SMS', logo: smsLogo, color: 'coral',
        description: 'Connect a Twilio number so customers can text your AI agent.',
        disconnect: handleDisconnectSms },
      line: { name: 'LINE', logo: lineLogo, color: 'teal',
        description: 'Connect LINE Official Accounts independently using their Messaging API credentials.',
        disconnect: handleDisconnectLine },
    }[channel]
    const accounts = accountsFor(channel)
    const lineState = channel === 'line' ? lineAccountState(accounts) : null
    return {
      id: channel,
      name: meta.name,
      description: meta.description,
      logo: meta.logo,
      category: 'MESSAGING',
      color: meta.color,
      connected: lineState ? lineState.connected : accounts.length > 0,
      needsAttention: lineState?.needsAttention ?? false,
      warning: lineState?.inactiveCount
        ? `${lineState.inactiveCount} LINE channel(s) need attention.`
        : undefined,
      teamName: (lineState ? accounts.filter(a => a.is_active) : accounts)
        .map(a => a.display_name).filter(Boolean).join(', '),
      isLoading: channelsLoading.value,
      connectAction: () => { credentialModalChannel.value = channel },
      disconnectAction: meta.disconnect
    }
  }),
  ...CRM_PROVIDERS.map(provider => {
    const meta = {
      hubspot: { name: 'HubSpot', logo: hubspotLogo, color: 'coral',
        description: 'Push captured leads into HubSpot as contacts, deduped by email, with the AI summary attached.' },
      pipedrive: { name: 'Pipedrive', logo: pipedriveLogo, color: 'teal',
        description: 'Push captured leads into Pipedrive as persons and leads, deduped by email, with the AI summary attached.' },
    }[provider]
    const connection = crmFor(provider)
    return {
      id: provider,
      name: meta.name,
      description: meta.description,
      logo: meta.logo,
      category: 'CRM',
      color: meta.color,
      connected: connection?.status === 'active',
      teamName: connection?.display_name || undefined,
      warning: crmCardWarning(connection),
      isLoading: crmLoading.value,
      connectAction: () => connectCrm(provider),
      disconnectAction: () => handleDisconnectCrm(provider)
    }
  }),
  // Native AI ticketing (built-in) — the card links to its settings page.
  {
    id: 'ai-ticketing',
    name: 'AI Ticketing',
    description: 'Native tickets triaged and investigated by AI — no external tracker needed.',
    logo: chattermateLogo,
    category: 'SUPPORT',
    color: 'lime',
    connected: true,
    connectAction: () => router.push('/settings/ticketing'),
    disconnectAction: () => router.push('/settings/ticketing')
  },
  // Future integrations
  {
    id: 'zendesk',
    name: 'Zendesk',
    description: 'Connect to Zendesk to manage customer support tickets.',
    logo: zendeskLogo,
    category: 'SUPPORT',
    color: 'coral',
    connected: false,
    comingSoon: true
  }
])

// Search + summary
const intQuery = ref('')

const filteredIntegrations = computed(() => {
  const q = intQuery.value.trim().toLowerCase()
  if (!q) return availableIntegrations.value
  return availableIntegrations.value.filter(it =>
    it.name.toLowerCase().includes(q) ||
    it.description.toLowerCase().includes(q) ||
    (it.category || '').toLowerCase().includes(q)
  )
})

const intEmpty = computed(() => filteredIntegrations.value.length === 0)

const intSummary = computed(() => {
  const total = availableIntegrations.value.length
  const connected = availableIntegrations.value.filter(it => it.connected).length
  return `${connected}/${total} connected`
})

// Display name for an ?integration= id, taken from the card list so a new
// integration never has to be named twice. Jira's callback predates the param,
// so a missing id means Jira.
const integrationName = (id?: string) => {
  const integrationId = id || 'jira'
  return availableIntegrations.value.find(it => it.id === integrationId)?.name || integrationId
}

onMounted(async () => {
  await Promise.all([
    fetchJiraStatus(),
    fetchShopifyStatus(),
    fetchChannelAccounts(),
    fetchCrmConnections()
  ])
  
  // Check if we're returning from an OAuth flow
  if (route.query.status) {
    if (route.query.status === 'success') {
      if (route.query.integration === 'shopify') {
        toast.success('Shopify connected successfully!')
      } 
      else if (route.query.integration === 'slack') {
        toast.success('Slack connected — choose which agent should answer.')
        // OAuth callback carries the exact installed ChannelAccount.id.
        // Never choose the first workspace as a fallback after a second install.
        const installedId = String(route.query.account_id || '')
        const slackAcc = accountsFor('slack').find(a => a.id === installedId)
        if (slackAcc) {
          credentialModalAccount.value = slackAcc
          credentialModalChannel.value = 'slack'
        }
      }
      else {
        toast.success(`${integrationName(route.query.integration as string)} connected successfully!`)
      }
      connectionError.value = null
    } else if (route.query.status === 'failure') {
      // Jira's callback omits the integration param, so a missing value means Jira.
      const failedIntegration = (route.query.integration as string) || 'jira'
      const name = integrationName(failedIntegration)
      const reason = route.query.reason as string || 'unknown'

      let errorMessage = `Failed to connect to ${name}`

      // Map common error reasons to user-friendly messages
      if (reason === 'cancelled') {
        errorMessage = `${name} connection was cancelled`
      } else if (reason === 'invalid_state') {
        errorMessage = 'Authentication session expired or is invalid'
      } else if (reason.includes('unauthorized')) {
        errorMessage = 'Authorization failed. Please check your permissions'
      } else if (reason) {
        errorMessage = `Failed to connect to ${name}: ${reason.replace(/_/g, ' ')}`
      }

      toast.error(errorMessage)
      connectionError.value = { integration: failedIntegration, message: errorMessage }
    }
    
    // Remove the query parameters to avoid showing the toast on refresh
    window.history.replaceState({}, document.title, window.location.pathname)
  }

  // Landing-page install: arriving with ?connect=slack starts the OAuth flow
  // immediately. The router guard has already ensured the user is signed in
  // (redirecting through login if needed), so this same-domain redirect carries
  // the session cookie the install endpoint requires.
  if (route.query.connect === 'slack') {
    window.history.replaceState({}, document.title, window.location.pathname)
    // A second workspace must be installable while the first is connected.
    connectSlack()
  }
})
</script>

<template>
  <DashboardLayout>
    <div class="integrations-settings">
      <!-- Page header + search -->
      <div class="int-page-header">
        <div class="int-page-titles">
          <h1 class="int-title">Integrations</h1>
          <p class="int-subtitle">Connect ChatterMate with the tools your team already uses.</p>
        </div>
        <div class="int-search">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <circle cx="11" cy="11" r="7"></circle>
            <path d="M21 21l-4-4"></path>
          </svg>
          <input
            v-model="intQuery"
            type="search"
            name="integration-search"
            autocomplete="off"
            aria-label="Search integrations"
            placeholder="Search integrations…"
          />
        </div>
      </div>

      <!-- Summary bar -->
      <div class="int-summary-bar">
        <span class="int-summary">{{ intSummary }}</span>
      </div>

      <!-- Cards grid -->
      <div class="integration-cards">
        <div
          v-for="integration in filteredIntegrations"
          :key="integration.id"
          class="integration-card"
        >
          <div class="integration-header">
            <div class="integration-tile" :class="`tile-${integration.color}`">
              <img
                v-if="integration.logo"
                :src="integration.logo"
                :alt="`${integration.name} Logo`"
                class="integration-logo"
              />
              <span v-else>{{ integration.name.charAt(0) }}</span>
            </div>
            <div class="integration-info">
              <div class="integration-name">{{ integration.name }}</div>
              <div class="integration-cat">{{ integration.category }}</div>
            </div>
            <span
              v-if="integration.connected"
              class="status-badge connected"
            >
              <span class="status-dot"></span>
              Connected
            </span>
            <span
              v-else-if="integration.id === 'messenger'"
              class="status-badge not-connected"
            >
              <span class="status-dot"></span>
              {{ messengerState.label }}
            </span>
            <span
              v-else-if="integration.needsAttention"
              class="status-badge not-connected"
            >
              <span class="status-dot"></span>
              Needs attention
            </span>
            <span
              v-else-if="!integration.comingSoon"
              class="status-badge not-connected"
            >
              <span class="status-dot"></span>
              {{ integration.statusLabel || 'Not connected' }}
            </span>
            <span
              v-else
              class="status-badge soon"
            >
              Soon
            </span>
          </div>

          <p class="integration-desc">{{ integration.description }}</p>

          <div
            v-if="integration.id === 'messenger' && accountsFor('messenger').length > 0"
            class="messenger-account-list"
            data-messenger-account-selector
          >
            <div
              v-for="account in accountsFor('messenger')"
              :key="account.id"
              class="messenger-account-row"
              :data-channel-account-id="account.id"
            >
              <div class="messenger-account-identity">
                <strong>{{ account.display_name || account.external_account_id }}</strong>
                <span
                  class="account-state"
                  :class="{ connected: account.is_active, attention: !account.is_active }"
                >
                  {{ account.is_active ? 'Connected' : 'Needs attention' }}
                </span>
              </div>
              <div class="messenger-account-actions">
                <button
                  type="button"
                  class="account-action"
                  @click="openMetaAccount('messenger', account)"
                >
                  Manage
                </button>
                <button
                  type="button"
                  class="account-action danger"
                  @click="showDisconnectConfirmation('messenger', account)"
                >
                  Disconnect
                </button>
              </div>
            </div>
          </div>

          <div v-if="integration.connected && integration.siteUrl" class="integration-meta">
            <a :href="integration.siteUrl" target="_blank" class="meta-link">↗ Visit {{ integration.name }} Site</a>
          </div>
          <div v-else-if="integration.connected && integration.shopDomain" class="integration-meta">
            <span class="meta-text">{{ integration.shopDomain }}</span>
            <a :href="`https://${integration.shopDomain}/admin`" target="_blank" class="meta-link">↗ Visit Shopify Admin</a>
          </div>
          <div v-else-if="integration.id !== 'messenger' && integration.connected && integration.teamName" class="integration-meta">
            <span class="meta-text">{{ integration.teamName }}</span>
          </div>
          <div v-else-if="!integration.connected && connectionError && connectionError.integration === integration.id" class="integration-meta">
            <span class="meta-error">⚠️ {{ connectionError.message }}</span>
          </div>
          <div v-if="integration.warning" class="integration-meta">
            <span class="meta-error">⚠️ {{ integration.warning }}</span>
          </div>

          <!-- WhatsApp is account-scoped: every real phone_number_id gets its
               own row and lifecycle actions. No "first account" fallback. -->
          <div
            v-if="integration.id === 'whatsapp' && accountsFor('whatsapp').length"
            class="wa-account-list"
          >
            <div
              v-for="account in accountsFor('whatsapp')"
              :key="account.id"
              class="wa-account-row"
            >
              <div class="wa-account-copy">
                <strong>{{ account.display_name || account.external_account_id }}</strong>
                <span>{{ account.external_account_id }}</span>
                <span
                  class="wa-account-health"
                  :class="{ 'wa-account-needs-attention': !whatsappAccountUsable(account) }"
                >{{ whatsappRowStatus(account) }}<template v-if="account.provider_health?.readiness && !whatsappAccountUsable(account)"> ({{ account.provider_health.readiness.replace(/_/g, ' ') }})</template></span>
              </div>
              <div class="wa-account-actions">
                <button
                  type="button"
                  class="int-btn int-btn-manage"
                  :disabled="whatsappActionAccountId === account.id"
                  @click="manageWhatsAppAccount(account)"
                >Manage</button>
                <button
                  type="button"
                  class="int-btn int-btn-manage"
                  :disabled="whatsappActionAccountId === account.id"
                  @click="reconnectWhatsAppAccount(account)"
                >Reconnect</button>
                <button
                  type="button"
                  class="int-btn int-btn-manage"
                  :disabled="whatsappActionAccountId === account.id"
                  @click="openWhatsAppRotation(account)"
                >Rotate token</button>
                <button
                  type="button"
                  class="int-btn int-btn-disconnect"
                  :disabled="whatsappActionAccountId === account.id"
                  @click="requestWhatsAppDisconnect(account)"
                >Disconnect</button>
              </div>
            </div>
          </div>

          <!-- Loading state -->
          <button
            v-if="integration.isLoading"
            class="int-btn int-btn-loading"
            disabled
          >
            <span class="loading-spinner"></span>
            Loading…
          </button>

          <!-- Exact LINE ChannelAccount selector; never manage/remove the first bot by default. -->
          <div v-else-if="integration.id === 'line' && accountsFor('line').length > 0" class="line-account-list" data-line-account-list>
            <div v-for="account in accountsFor('line')" :key="account.id" class="line-account-row" :data-line-account-id="account.id">
              <div class="line-account-identity">
                <strong>{{ account.display_name || 'LINE channel' }}</strong>
                <small>{{ account.external_account_id }}</small>
                <small>{{ account.is_active ? 'Connected' : 'Needs attention' }}</small>
              </div>
              <div class="int-actions">
                <button class="int-btn int-btn-manage" @click="manageLineAccount(account)">Manage</button>
                <button class="int-btn int-btn-disconnect" @click="showLineDisconnect(account)">Disconnect</button>
              </div>
            </div>
            <button class="int-btn int-btn-connect" @click="addLineAccount">Add LINE channel</button>
          </div>
          <!-- Messenger is multi-account: add a Page without choosing a hidden default. -->
          <div v-else-if="integration.id === 'messenger'" class="int-actions">
            <button
              type="button"
              class="int-btn int-btn-manage"
              data-add-facebook-page
              @click="openMetaAccount('messenger', null)"
            >
              Add Facebook Page
            </button>
          </div>
          <!-- Instagram accounts are independent, including reconnect and removal. -->
          <div v-else-if="integration.id === 'instagram'" class="instagram-account-list">
            <div v-for="ig in instagramAccounts" :key="ig.id" class="instagram-account-row">
              <div class="instagram-account-identity">
                <strong>{{ ig.display_name || ig.external_account_id }}</strong>
                <span>{{ ig.external_account_id }}</span>
                <span>{{ ig.is_active ? 'Connected' : 'Needs attention' }}</span>
              </div>
              <div class="int-actions">
                <button class="int-btn int-btn-manage" @click="openInstagramAccount(ig)">Manage</button>
                <button class="int-btn int-btn-manage" @click="openInstagramReconnect(ig)">Reconnect</button>
                <button class="int-btn int-btn-disconnect" @click="showDisconnectConfirmation('instagram', ig.id)">Disconnect</button>
              </div>
            </div>
            <button class="int-btn int-btn-connect" @click="openInstagramConnect">Connect another Instagram account</button>
          </div>

          <!-- Connected: Manage + Disconnect -->
          <!-- Slack is a list of independent, team-scoped ChannelAccounts. -->
          <div v-else-if="integration.id === 'slack' && accountsFor('slack').length > 0" class="slack-workspaces">
            <p class="meta-text">{{ accountsFor('slack').length }} configured workspace(s)</p>
            <div v-for="account in accountsFor('slack')" :key="account.id" class="slack-workspace">
              <span class="meta-text">{{ account.display_name || account.external_account_id }} ({{ account.external_account_id }})</span>
              <small>{{ account.is_active ? 'Connected' : 'Needs attention' }}</small>
              <div class="int-actions">
                <button class="int-btn int-btn-manage" @click="manageSlackAccount(account)">Manage</button>
                <button class="int-btn int-btn-disconnect" @click="confirmSlackDisconnect(account)">Disconnect</button>
              </div>
            </div>
            <button class="int-btn int-btn-connect" @click="connectSlack">+ Add workspace</button>
          </div>

          <!-- Other connected integrations retain their existing lifecycle. -->
          <!-- Connected: WhatsApp stays account-scoped; other integrations
               retain their integration-level controls. -->
          <div v-else-if="integration.connected" class="int-actions">
            <template v-if="integration.id === 'whatsapp'">
              <button class="int-btn int-btn-manage" @click="connectAnotherWhatsApp">
                Add number
              </button>
              <button
                v-if="integration.extraAction"
                class="int-btn int-btn-manage"
                @click="integration.extraAction()"
              >
                {{ integration.extraActionLabel }}
              </button>
            </template>
            <template v-else>
              <button class="int-btn int-btn-manage" @click="manageIntegration(integration)">Manage</button>
              <button
                v-if="integration.extraAction"
                class="int-btn int-btn-manage"
                @click="integration.extraAction()"
              >
                {{ integration.extraActionLabel }}
              </button>
              <button class="int-btn int-btn-disconnect" @click="showDisconnectConfirmation(integration.id)">
                Disconnect
              </button>
            </template>
          </div>

          <!-- Coming soon -->
          <button
            v-else-if="integration.comingSoon"
            class="int-btn int-btn-soon"
            disabled
          >
            Coming soon
          </button>

          <!-- Not connected: Connect / Install -->
          <button
            v-else
            class="int-btn int-btn-connect"
            @click="integration.id === 'shopify' ? openShopifyInstallation() : integration.connectAction?.()"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
              <path d="M12 5v14M5 12h14"></path>
            </svg>
            {{ integration.id === 'shopify' ? 'Install' : integration.id === 'whatsapp' ? 'Add number' : 'Connect' }}
          </button>
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="intEmpty" class="int-empty">
        No integrations match your search.
      </div>
    </div>
  </DashboardLayout>

  <!-- Exact-account WhatsApp credential rotation. The replacement token is
       held only in this input and is sent directly to the canonical route. -->
  <div v-if="whatsappRotateAccount" class="disconnect-modal">
    <div class="disconnect-modal-content">
      <div class="disconnect-modal-header">
        <h3>Rotate WhatsApp credential</h3>
        <button class="close-modal-btn" @click="closeWhatsAppRotation">
          <span>×</span>
        </button>
      </div>
      <div class="disconnect-modal-body">
        <p>
          Updating <strong>{{ whatsappRotateAccount.display_name || whatsappRotateAccount.external_account_id }}</strong>
          only. Other WhatsApp numbers are not changed.
        </p>
        <label class="wa-rotate-field">
          <span>New access token</span>
          <input
            v-model="whatsappRotateToken"
            type="password"
            autocomplete="new-password"
            class="wa-rotate-input"
            name="whatsapp-rotation-token"
          />
        </label>
        <label class="wa-rotate-field">
          <span>WhatsApp Business Account ID (optional)</span>
          <input
            v-model="whatsappRotateWabaId"
            type="text"
            autocomplete="off"
            class="wa-rotate-input"
            name="whatsapp-rotation-waba"
            placeholder="Keep empty to preserve the current WABA"
          />
        </label>
      </div>
      <div class="disconnect-modal-actions">
        <button class="btn-cancel" @click="closeWhatsAppRotation">Cancel</button>
        <button
          class="int-btn int-btn-manage"
          :disabled="!whatsappRotateToken.trim() || whatsappActionAccountId === whatsappRotateAccount.id"
          @click="rotateWhatsAppAccount"
        >
          {{ whatsappActionAccountId === whatsappRotateAccount.id ? 'Validating…' : 'Validate and update' }}
        </button>
      </div>
    </div>
  </div>

  <!-- Exact-account WhatsApp removal. This deliberately never calls the old
       integration-wide disconnect loop. -->
  <div v-if="whatsappDisconnectAccount" class="disconnect-modal">
    <div class="disconnect-modal-content">
      <div class="disconnect-modal-header">
        <h3>Disconnect WhatsApp number</h3>
        <button class="close-modal-btn" @click="cancelWhatsAppDisconnect">
          <span>×</span>
        </button>
      </div>
      <div class="disconnect-modal-body">
        <div class="warning-icon">⚠️</div>
        <p>
          Disconnect only
          <strong>{{ whatsappDisconnectAccount.display_name || whatsappDisconnectAccount.external_account_id }}</strong>?
        </p>
        <p class="warning-text">
          Other WhatsApp numbers and their conversations remain connected.
        </p>
      </div>
      <div class="disconnect-modal-actions">
        <button class="btn-cancel" @click="cancelWhatsAppDisconnect">Cancel</button>
        <button
          class="btn-disconnect"
          :disabled="whatsappActionAccountId === whatsappDisconnectAccount.id"
          @click="disconnectWhatsAppAccount"
        >
          {{ whatsappActionAccountId === whatsappDisconnectAccount.id ? 'Disconnecting…' : 'Disconnect this number' }}
        </button>
      </div>
    </div>
  </div>
  
  <!-- Disconnect Confirmation Modal -->
  <div v-if="showDisconnectConfirm" class="disconnect-modal">
    <div class="disconnect-modal-content">
      <div class="disconnect-modal-header">
        <h3>Disconnect Integration</h3>
        <button class="close-modal-btn" @click="cancelDisconnect">
          <span>×</span>
        </button>
      </div>
      <div class="disconnect-modal-body">
        <div class="warning-icon">⚠️</div>
        <template v-if="disconnectingIntegration === 'line' && lineAccountToDisconnect">
          <p>Disconnect LINE channel <strong>{{ lineAccountToDisconnect.display_name || lineAccountToDisconnect.external_account_id }}</strong>?</p>
          <p class="warning-text">Only this channel ({{ lineAccountToDisconnect.external_account_id }}) will be disconnected. Other LINE channels remain connected.</p>
        </template>
        <template v-else-if="disconnectingIntegration === 'messenger' && disconnectingAccount">
          <p>Disconnect Facebook Page <strong>{{ disconnectingAccount.display_name || disconnectingAccount.external_account_id }}</strong>?</p>
          <p class="warning-text">Only this Facebook Page will be disconnected. Other connected Pages stay unchanged.</p>
        </template>
        <template v-else>
          <p>Are you sure you want to disconnect this integration?</p>
          <p class="warning-text">This will remove all connections and configurations associated with this integration.</p>
        </template>
        
        <div v-if="disconnectingIntegration === 'jira'" class="integration-specific-warning">
          <p>Disconnecting Jira will:</p>
          <ul>
            <li>Remove all Jira configurations from your agents</li>
            <li>Disable ticket creation functionality</li>
            <li>Require you to reconnect and reconfigure Jira settings if you want to use it again</li>
          </ul>
        </div>
        
        <div v-if="disconnectingIntegration === 'shopify'" class="integration-specific-warning">
          <p>To disconnect Shopify:</p>
          <ul>
            <li>You'll be redirected to your Shopify admin</li>
            <li>Uninstall the ChatterMate app from your Shopify store</li>
            <li>This ensures the disconnection is synchronized on both platforms</li>
            <li>You'll need to reinstall the app if you want to use it again</li>
          </ul>
        </div>

        <div v-if="disconnectingIntegration === 'slack'" class="integration-specific-warning">
          <p>Disconnect {{ slackDisconnectAccount?.display_name || slackDisconnectAccount?.external_account_id }} ({{ slackDisconnectAccount?.external_account_id }})?</p>
          <p>Only this workspace's access and conversations will be removed. Other connected Slack workspaces stay connected.</p>
        </div>

        <div v-if="disconnectingIntegration === 'telegram'" class="integration-specific-warning">
          <p>Disconnecting Telegram will:</p>
          <ul>
            <li>Remove the bot's webhook so it stops receiving messages</li>
            <li>Remove the agent routing for this bot</li>
            <li>Require you to reconnect the bot token to use it again</li>
          </ul>
        </div>

        <div v-if="disconnectingIntegration === 'messenger' && disconnectingAccount" class="integration-specific-warning">
          <p>Disconnecting this Facebook Page will:</p>
          <ul>
            <li>Stop receiving and sending messages only for this Page</li>
            <li>Remove only this Page's agent routing and ChannelAccount</li>
            <li>Leave sibling Facebook Pages, credentials, and conversations untouched</li>
          </ul>
        </div>

        <div v-if="disconnectingIntegration === 'whatsapp' || disconnectingIntegration === 'instagram'" class="integration-specific-warning">
          <p>Disconnecting {{ disconnectingIntegration === 'instagram' ? 'this Instagram account' : 'this channel' }} will:</p>
          <ul>
            <li>Stop the AI agent from receiving and answering its messages</li>
            <li>Remove the agent routing for the connected account</li>
            <li>Require re-entering credentials to use it again</li>
          </ul>
        </div>

        <div v-if="disconnectingIntegration === 'hubspot' || disconnectingIntegration === 'pipedrive'" class="integration-specific-warning">
          <p>Disconnecting this CRM will:</p>
          <ul>
            <li>Stop pushing captured leads to it (queued pushes are cancelled)</li>
            <li>Revoke ChatterMate's access tokens</li>
            <li>Leave agents' "Sync to CRM" setting in place — it stays inactive until you reconnect</li>
          </ul>
        </div>
      </div>
      <div class="disconnect-modal-actions">
        <button class="btn-cancel" @click="cancelDisconnect">Cancel</button>
        <button 
          v-if="disconnectingIntegration === 'jira'" 
          class="btn-disconnect" 
          @click="handleDisconnectJira"
          :disabled="isLoading"
        >
          <span v-if="isLoading" class="loading-spinner"></span>
          <span v-else>Disconnect Jira</span>
        </button>
        <button
          v-if="disconnectingIntegration === 'shopify'"
          class="btn-disconnect"
          @click="handleDisconnectShopify"
        >
          <span class="btn-icon">↗</span>
          <span>Open Shopify Admin</span>
        </button>
        <button
          v-if="disconnectingIntegration === 'slack'"
          class="btn-disconnect"
          @click="handleDisconnectSlack"
          :disabled="channelsLoading"
        >
          <span v-if="channelsLoading" class="loading-spinner"></span>
          <span v-else>Disconnect this workspace</span>
        </button>
        <button
          v-if="disconnectingIntegration === 'telegram'"
          class="btn-disconnect"
          @click="handleDisconnectTelegram"
          :disabled="channelsLoading"
        >
          <span v-if="channelsLoading" class="loading-spinner"></span>
          <span v-else>Disconnect Telegram</span>
        </button>
        <button
          v-if="disconnectingIntegration === 'email' || disconnectingIntegration === 'sms' || (disconnectingIntegration === 'line' && lineAccountToDisconnect)"
          class="btn-disconnect"
          @click="disconnectingIntegration === 'email' ? handleDisconnectEmail() : disconnectingIntegration === 'sms' ? handleDisconnectSms() : handleDisconnectLine()"
          :disabled="channelsLoading"
        >
          <span v-if="channelsLoading" class="loading-spinner"></span>
          <span v-else>Disconnect {{ disconnectingIntegration === 'email' ? 'Email' : disconnectingIntegration === 'sms' ? 'SMS' : 'LINE' }}</span>
        </button>
        <button
          v-if="disconnectingIntegration === 'messenger' && disconnectingAccount"
          class="btn-disconnect"
          data-disconnect-facebook-page
          @click="disconnectMessengerPage(disconnectingAccount)"
          :disabled="channelsLoading"
        >
          <span v-if="channelsLoading" class="loading-spinner"></span>
          <span v-else>Disconnect Facebook Page</span>
        </button>
        <button
          v-if="disconnectingIntegration === 'whatsapp' || disconnectingIntegration === 'instagram'"
          class="btn-disconnect"
          @click="disconnectingIntegration === 'whatsapp' ? handleDisconnectWhatsApp() : handleDisconnectInstagram()"
          :disabled="channelsLoading"
        >
          <span v-if="channelsLoading" class="loading-spinner"></span>
          <span v-else>Disconnect {{ disconnectingIntegration === 'whatsapp' ? 'WhatsApp' : (instagramAccounts.find(account => account.id === disconnectingInstagramAccountId)?.display_name || 'Instagram account') }}</span>
        </button>
        <button
          v-if="disconnectingIntegration === 'hubspot' || disconnectingIntegration === 'pipedrive'"
          class="btn-disconnect"
          @click="handleDisconnectCrm(disconnectingIntegration as CrmProvider)"
          :disabled="crmLoading"
        >
          <span v-if="crmLoading" class="loading-spinner"></span>
          <span v-else>Disconnect {{ disconnectingIntegration === 'hubspot' ? 'HubSpot' : 'Pipedrive' }}</span>
        </button>
      </div>
    </div>
  </div>

  <!-- Telegram Connect Modal -->
  <TelegramConnectModal
    v-if="showTelegramModal"
    :existing-account="telegramModalAccount"
    @close="showTelegramModal = false; telegramModalAccount = null"
    @connected="onChannelConnected"
  />

  <!-- Meta Channel Connect Modal (WhatsApp / Messenger / Instagram) -->
  <MetaChannelConnect
    v-if="metaModalChannel"
    :key="metaModalAccount?.id || 'new'"
    :channel="metaModalChannel"
    :existing-account="metaModalAccount"
    :reconnect-account="metaReconnectAccount"
    @close="metaModalChannel = null; metaModalAccount = null; metaReconnectAccount = null"
    @connected="onChannelConnected"
    @account-updated="onMetaAccountUpdated"
    @connection-failed="onMetaConnectionFailed"
  />

  <!-- WhatsApp template management -->
  <WhatsAppTemplateManager
    v-if="showTemplateManager"
    :accounts="accountsFor('whatsapp')"
    @close="showTemplateManager = false"
  />

  <!-- Credential Connect Modal (Email / SMS / LINE) -->
  <ChannelConnectModal
    v-if="credentialModalChannel"
    :channel="credentialModalChannel"
    :existing-account="credentialModalAccount"
    @close="credentialModalChannel = null; credentialModalAccount = null"
    @connected="onChannelConnected"
  />

</template>

<style scoped>
:root {
  --primary-color-rgb: 59, 130, 246; /* This is a typical blue color in RGB format */
  --error-color-rgb: 220, 38, 38; /* Red color in RGB format */
}

.integrations-settings {
  padding: var(--space-lg);
  max-width: 1180px;
  margin: 0 auto;
}

/* Page header + search */
.int-page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 22px;
}

.int-title {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 30px;
  letter-spacing: -0.02em;
  color: var(--text);
  margin: 0 0 6px;
}

.int-subtitle {
  font-size: 15px;
  color: var(--muted);
  margin: 0;
}

.int-search {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn);
  min-width: 230px;
  color: var(--muted2);
}

.int-search input {
  flex: 1;
  min-width: 0;
  background: none;
  border: none;
  outline: none;
  color: var(--text);
  font-size: 14px;
  font-family: inherit;
}

.int-search input::placeholder {
  color: var(--muted2);
}

/* Summary bar */
.int-summary-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 22px;
}

.int-summary {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted2);
  flex-shrink: 0;
}

/* Cards grid */
.integration-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 18px;
}

.integration-card {
  background: var(--surface);
  border: 1px solid var(--o08);
  border-radius: 18px;
  padding: 22px;
  display: flex;
  flex-direction: column;
}

.integration-header {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 14px;
}

/* Color-coded icon tile */
.integration-tile {
  width: 44px;
  height: 44px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 18px;
}

.integration-tile .integration-logo {
  width: 26px;
  height: 26px;
  object-fit: contain;
}

.tile-purple {
  background: var(--purple-bg);
  color: var(--c-purple);
}

.tile-teal {
  background: var(--teal-bg);
  color: var(--c-teal);
}

.tile-accent {
  background: var(--accent-bg-12);
  color: var(--accent-ink);
}

.tile-coral {
  background: var(--coral-bg);
  color: var(--c-coral);
}

.integration-info {
  flex: 1;
  min-width: 0;
}

.integration-name {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 16.5px;
  color: var(--text2);
}

.integration-cat {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted2);
  margin-top: 3px;
}

/* Status badge */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: var(--radius-full);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.status-badge.connected {
  background: var(--teal-bg);
  color: var(--c-teal);
}

.status-badge.not-connected {
  background: var(--o05);
  color: var(--muted2);
}

.status-badge.soon {
  background: var(--o05);
  color: var(--faint);
}

/* Description */
.integration-desc {
  font-size: 13.5px;
  color: var(--muted);
  line-height: 1.55;
  margin: 0 0 18px;
  flex: 1;
}

.messenger-account-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: -4px 0 16px;
}

.messenger-account-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--o08);
  border-radius: 12px;
  background: var(--surface2);
}

.messenger-account-identity {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.messenger-account-identity strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-state {
  font-size: 12px;
  color: var(--text2);
}

.account-state.connected {
  color: var(--success);
}

.account-state.attention {
  color: var(--warning);
}

.messenger-account-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.account-action {
  border: 0;
  background: transparent;
  color: var(--accent-solid);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 7px;
}

.account-action.danger {
  color: var(--c-coral);
}

/* Connected meta info */
.integration-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: -8px 0 16px;
}

.meta-text {
  font-size: 13px;
  color: var(--text2);
  font-weight: 500;
}

.meta-link {
  font-size: 12.5px;
  color: var(--c-teal);
  text-decoration: none;
  width: fit-content;
}

.meta-link:hover {
  text-decoration: underline;
}

.meta-error {
  font-size: 12px;
  color: var(--c-coral);
  background: var(--coral-bg);
  border: 1px solid var(--coral-border);
  padding: 6px 10px;
  border-radius: var(--radius-md);
  word-break: break-word;
}

/* Buttons */
.int-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.line-account-list {
  display: grid;
  gap: 12px;
}
.line-account-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  border-top: 1px solid var(--border-color);
  padding-top: 12px;
}
.line-account-identity {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.line-account-identity small {
  overflow-wrap: anywhere;
  color: var(--muted);
}
.int-actions {
  display: flex;
  gap: 9px;
}

.instagram-account-list {
  display: grid;
  gap: 12px;
}

.instagram-account-row {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--o14);
  border-radius: var(--radius-chip);
}

.instagram-account-identity {
  display: grid;
  min-width: 0;
  gap: 2px;
  color: var(--text);
  font-size: 13px;
}

.instagram-account-identity span {
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}

.instagram-account-row .int-actions {
  flex-wrap: wrap;
}

.instagram-account-row .int-btn {
  flex: 1 1 auto;
}

.int-btn-connect {
  width: 100%;
  padding: 12px;
  background: var(--accent-solid);
  color: var(--on-accent-solid);
  border: none;
  border-radius: var(--radius-chip);
  font-size: 14px;
  font-weight: 600;
}

.int-btn-connect:hover {
  filter: brightness(1.05);
}

.int-btn-manage {
  flex: 1;
  padding: 11px;
  background: var(--o05);
  border: 1px solid var(--o14);
  border-radius: var(--radius-chip);
  color: var(--text);
}

.int-btn-manage:hover {
  background: var(--o10);
}

.int-btn-disconnect {
  flex-shrink: 0;
  padding: 11px 16px;
  background: transparent;
  border: 1px solid var(--coral-border);
  border-radius: var(--radius-chip);
  color: var(--c-coral);
}

.int-btn-disconnect:hover {
  background: var(--coral-bg);
}

.int-btn-soon {
  width: 100%;
  padding: 12px;
  background: var(--o03);
  border: 1px solid var(--o08);
  border-radius: var(--radius-chip);
  color: var(--faint);
  font-size: 14px;
  cursor: not-allowed;
}

.int-btn-loading {
  width: 100%;
  padding: 12px;
  background: var(--o03);
  border: 1px solid var(--o08);
  border-radius: var(--radius-chip);
  color: var(--muted);
  font-size: 14px;
  cursor: default;
}

.loading-spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid var(--o10);
  border-top-color: var(--accent-ink);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* Empty state */
.int-empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--muted2);
  font-size: 14px;
}

@media (max-width: 768px) {
  .integration-cards {
    grid-template-columns: 1fr;
  }

  .integrations-settings {
    padding: var(--space-md);
  }
}

/* Disconnect Modal Styles */
.disconnect-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.disconnect-modal-content {
  background: var(--background-color);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg, 12px);
  width: 440px;
  max-width: calc(100vw - 32px);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
  overflow: hidden;
}

.disconnect-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border-color);
}

.disconnect-modal-header h3 {
  margin: 0;
  color: var(--text-primary, var(--text));
  font-size: 16px;
  font-weight: 600;
  font-family: var(--font-display, inherit);
}

.close-modal-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 24px;
  line-height: 1;
  padding: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-modal-btn:hover {
  color: var(--text-primary);
}

.disconnect-modal-body {
  padding: 24px;
}

.warning-icon {
  width: 56px;
  height: 56px;
  margin: 4px auto 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  border-radius: 50%;
  background: var(--coral-bg, rgba(220, 38, 38, 0.12));
}

.disconnect-modal-body p {
  margin: 0 0 10px;
  text-align: center;
  color: var(--text-primary, var(--text));
}

.warning-text {
  color: var(--error-color);
  font-weight: 500;
  font-size: 13px;
}

.integration-specific-warning {
  margin-top: 20px;
  padding: 14px 16px;
  background: var(--background-soft);
  border-radius: var(--radius-md, 8px);
  border-left: 3px solid var(--warning, #f5a623);
}

.integration-specific-warning p {
  text-align: left;
  margin: 0 0 8px;
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary, var(--text));
}

.integration-specific-warning ul {
  margin: 0;
  padding-left: 20px;
}

.integration-specific-warning li {
  margin-bottom: 6px;
  color: var(--text-secondary, var(--muted));
  font-size: 13px;
}

.disconnect-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 22px;
  border-top: 1px solid var(--border-color);
  background: var(--background-soft);
}

.btn-cancel {
  background: var(--background-mute);
  color: var(--text-primary, var(--text));
  border: 1px solid var(--border-color);
  border-radius: var(--radius-btn, 8px);
  padding: 9px 16px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.btn-cancel:hover {
  background: var(--background-alt);
}

.btn-disconnect {
  background: var(--error-color);
  color: #fff;
  border: none;
  border-radius: var(--radius-btn, 8px);
  padding: 9px 16px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.btn-disconnect:hover {
  filter: brightness(1.08);
}

.btn-disconnect:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.loading-spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid var(--o30);
  border-radius: 50%;
  border-top-color: var(--text);
  animation: spin 1s linear infinite;
}

.not-connected-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.connection-error {
  font-size: var(--text-xs);
  color: var(--error-color);
  background-color: rgba(var(--error-color-rgb), 0.1);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-md);
  margin-top: var(--space-xs);
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  max-width: 100%;
  word-break: break-word;
}

.error-icon {
  font-size: 12px;
  flex-shrink: 0;
}

.shop-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin-top: var(--space-xs);
}

.shop-domain {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: 500;
}

.team-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin-top: var(--space-xs);
}

.team-name {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: 500;
}

.integration-form {
  margin-top: var(--space-sm);
  border-top: 1px solid var(--border-color);
  padding-top: var(--space-sm);
}

.form-group {
  margin-bottom: var(--space-md);
}

.form-group label {
  display: block;
  font-size: var(--text-sm);
  font-weight: 500;
  margin-bottom: var(--space-xs);
  color: var(--text-primary);
}

.input-with-label {
  display: flex;
  align-items: center;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background-color: var(--background-color);
  overflow: hidden;
}

.input-with-label input {
  flex: 1;
  padding: var(--space-sm);
  border: none;
  font-size: var(--text-sm);
  background: transparent;
  min-width: 0;
}

.input-with-label input:focus {
  outline: none;
}

.input-suffix {
  padding: var(--space-sm) var(--space-sm) var(--space-sm) 0;
  font-size: var(--text-sm);
  color: var(--text-muted);
  white-space: nowrap;
}

.form-help {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-top: var(--space-xs);
}

.form-error {
  display: block;
  font-size: var(--text-xs);
  color: var(--error-color);
  margin-top: var(--space-xs);
}
.slack-workspaces {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.slack-workspace {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow-wrap: anywhere;
}


.wa-account-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 12px 0;
}

.wa-account-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--background-soft);
}

.wa-account-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--muted);
}

.wa-account-copy strong {
  color: var(--text);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.wa-account-health {
  text-transform: lowercase;
}

.wa-account-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.wa-account-actions .int-btn {
  width: auto;
  min-width: 0;
}

.wa-rotate-field {
  display: block;
  margin-top: 12px;
  text-align: left;
}

.wa-rotate-field > span {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
}

.wa-rotate-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-btn, 8px);
  background: var(--background-soft);
  color: inherit;
}

@media (max-width: 720px) {
  .wa-account-row {
    align-items: stretch;
    flex-direction: column;
  }

  .wa-account-actions {
    justify-content: flex-start;
  }
}
</style>
