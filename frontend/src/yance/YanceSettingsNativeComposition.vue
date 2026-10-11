<script setup lang="ts">
import YanceWebShell from './components/YanceWebShell.vue'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import { useTheme, type ThemeMode } from '@/composables/useTheme'
import { useAISetup } from '@/composables/useAISetup'
import { useNotificationSettings } from '@/composables/useNotificationSettings'
import channelsService, { type ChannelAccount, type ChannelType } from '@/services/channels'
import { getApiUrl } from '@/config/api'
import { translationService, type TranslationHealth } from '@/services/translation'

type SettingsSectionId =
  | 'accounts'
  | 'ai'
  | 'persona'
  | 'memory'
  | 'translation'
  | 'voice-media'
  | 'automation'
  | 'appearance'
  | 'privacy'
  | 'diagnostics'

type ProductState =
  | 'Connected'
  | 'Needs attention'
  | 'Not configured'
  | 'Unavailable'
  | 'Loading'
  | 'Available'
  | 'Verification pending'

const productStateLabels: Record<ProductState, string> = {
  Connected: '已连接',
  'Needs attention': '需要检查',
  'Not configured': '尚未配置',
  Unavailable: '暂不可用',
  Loading: '加载中',
  Available: '已有功能',
  'Verification pending': '待验证',
}
const productStateLabel = (state: ProductState): string => productStateLabels[state]

type SettingsSection = {
  id: SettingsSectionId
  label: string
  description: string
}

const sections: SettingsSection[] = [
  { id: 'accounts', label: '账户与平台', description: '连接和管理消息平台账号。' },
  { id: 'ai', label: 'AI 与模型', description: '查看当前 AI 配置，并进入现有模型设置。' },
  { id: 'persona', label: '人格与学习', description: '管理人格、范围规则和学习记录。' },
  { id: 'memory', label: '记忆与关系', description: '查看关系记忆、推测、规则与证据。' },
  { id: 'translation', label: '翻译', description: '管理联系人语言、翻译行为和完整性状态。' },
  { id: 'voice-media', label: '语音与媒体', description: '管理语音档案、媒体与生成能力。' },
  { id: 'automation', label: '自动化与权限', description: '管理回复方式、自动处理和敏感操作。' },
  { id: 'appearance', label: '外观与通知', description: '调整外观，并查看通知设置状态。' },
  { id: 'privacy', label: '隐私 / 备份 / 更新', description: '查看文件访问、备份、导出与更新能力。' },
  { id: 'diagnostics', label: '诊断', description: '集中查看可用的连接与配置状态。' },
]

const selectedId = ref<SettingsSectionId>('accounts')
const selected = computed(
  () => sections.find((section) => section.id === selectedId.value) ?? sections[0],
)

const { mode, setTheme } = useTheme()
const themeOptions: Array<{ value: ThemeMode; label: string }> = [
  { value: 'system', label: '跟随系统' },
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
]

const {
  isLoading: aiLoading,
  error: aiError,
  setupConfig,
  providers,
  hasExistingConfig,
} = useAISetup()

const {
  settings: notificationSettings,
  isLoading: notificationLoading,
  error: notificationError,
} = useNotificationSettings()

const channelAccounts = ref<ChannelAccount[]>([])
const channelsLoading = ref(true)
const channelsError = ref('')
const runtimeHealth = ref<{ status: string; version: string } | null>(null)
const runtimeHealthLoading = ref(true)
const runtimeHealthError = ref('')
const translationHealth = ref<TranslationHealth | null>(null)
const translationLoading = ref(true)
const translationError = ref('')

const platformDefinitions: Array<{ type: ChannelType; label: string }> = [
  { type: 'whatsapp', label: 'WhatsApp' },
  { type: 'telegram', label: 'Telegram' },
  { type: 'messenger', label: 'Facebook 专页（Messenger）' },
  { type: 'instagram', label: 'Instagram' },
  { type: 'line', label: 'LINE' },
]

const loadChannelAccounts = async () => {
  channelsLoading.value = true
  channelsError.value = ''
  try {
    channelAccounts.value = await channelsService.listAccounts()
  } catch (error: any) {
    channelsError.value = error?.message || 'Unable to load platform accounts'
    channelAccounts.value = []
  } finally {
    channelsLoading.value = false
  }
}

const loadRuntimeHealth = async () => {
  runtimeHealthLoading.value = true
  runtimeHealthError.value = ''
  try {
    const apiRoot = getApiUrl().replace(/\/api\/v1\/?$/, '')
    const response = await fetch(`${apiRoot}/health`, { method: 'GET' })
    if (!response.ok) throw new Error(`health ${response.status}`)
    runtimeHealth.value = await response.json()
  } catch (error: any) {
    runtimeHealth.value = null
    runtimeHealthError.value = error?.message || 'Unable to read runtime health'
  } finally {
    runtimeHealthLoading.value = false
  }
}

const loadTranslationHealth = async () => {
  translationLoading.value = true
  translationError.value = ''
  try {
    translationHealth.value = await translationService.health()
  } catch (error: any) {
    translationError.value = error?.message || 'Unable to read translation health'
    translationHealth.value = null
  } finally {
    translationLoading.value = false
  }
}

onMounted(() => {
  void loadChannelAccounts()
  void loadRuntimeHealth()
  void loadTranslationHealth()
})

const platformCards = computed(() =>
  platformDefinitions.map((platform) => {
    const accounts = channelAccounts.value.filter(
      (account) => account.channel_type === platform.type,
    )
    const active = accounts.filter((account) => account.is_active)
    const providerReady = active.some((account) => {
      const health = account.provider_health
      return !!health && !health.reconnect_needed && !health.last_provider_error &&
        ['ready', 'connected', 'healthy'].includes((health.readiness || '').toLowerCase())
    })
    let state: ProductState = 'Not configured'

    if (channelsLoading.value) state = 'Loading'
    else if (channelsError.value) state = 'Needs attention'
    else if (providerReady) state = 'Connected'
    else if (accounts.length > 0) state = 'Needs attention'

    return {
      ...platform,
      accounts,
      active,
      state,
      detail:
        active.length > 0
          ? '已启用（连接健康状态需单独核验）：' + active
              .map((account) => platform.type === 'line'
                ? `${account.display_name || 'LINE channel'} (${account.external_account_id})`
                : account.display_name || account.external_account_id)
              .filter(Boolean)
              .join(' · ')
          : accounts.length > 0
            ? '已保存账号需要重新连接'
            : '尚未添加账号',
    }
  }),
)

const accountsState = computed<ProductState>(() => {
  if (channelsLoading.value) return 'Loading'
  if (channelsError.value) return 'Needs attention'
  if (channelAccounts.value.some((account) => {
    const health = account.provider_health
    return account.is_active && !!health && !health.reconnect_needed && !health.last_provider_error &&
      ['ready', 'connected', 'healthy'].includes((health.readiness || '').toLowerCase())
  })) return 'Connected'
  if (channelAccounts.value.length > 0) return 'Needs attention'
  return 'Not configured'
})

const aiState = computed<ProductState>(() => {
  if (aiLoading.value) return 'Loading'
  if (aiError.value) return 'Needs attention'
  // A stored AIConfig proves only configuration, not a successful model invocation.
  return hasExistingConfig.value ? 'Needs attention' : 'Not configured'
})

const selectedModelCapability = computed(() =>
  providers.value
    .find((provider) => provider.value === setupConfig.value.provider)
    ?.models.find((model) => model.value === setupConfig.value.model),
)
const fallbackState = computed<ProductState>(() => {
  if (aiLoading.value || aiError.value || !hasExistingConfig.value) return aiState.value
  return setupConfig.value.fallbackModel ? 'Verification pending' : 'Not configured'
})
const reasoningState = computed<ProductState>(() => {
  if (aiLoading.value || aiError.value || !hasExistingConfig.value) return aiState.value
  if (!selectedModelCapability.value?.reasoning_strengths?.length) return 'Unavailable'
  return setupConfig.value.reasoningStrength ? 'Verification pending' : 'Not configured'
})

const notificationState = computed<ProductState>(() => {
  if (notificationLoading.value) return 'Loading'
  if (notificationError.value) return 'Needs attention'
  // Reading preferences proves a local settings feature, not a push-service connection.
  return notificationSettings.value ? 'Available' : 'Not configured'
})

const runtimeState = computed<ProductState>(() => {
  if (runtimeHealthLoading.value) return 'Loading'
  if (runtimeHealthError.value || runtimeHealth.value?.status !== 'healthy') return 'Needs attention'
  return 'Connected'
})

const translationState = computed<ProductState>(() => {
  if (translationLoading.value) return 'Loading'
  if (translationError.value || translationHealth.value?.state === 'needs_attention') return 'Needs attention'
  if (translationHealth.value?.state === 'connected') return 'Connected'
  if (translationHealth.value?.state === 'not_configured') return 'Not configured'
  return 'Unavailable'
})

const sectionStatus = computed<Record<SettingsSectionId, ProductState>>(() => ({
  accounts: accountsState.value,
  ai: aiState.value,
  persona: 'Verification pending',
  memory: 'Available',
  translation: translationState.value,
  'voice-media': 'Verification pending',
  automation: 'Available',
  appearance: notificationState.value === 'Needs attention' ? 'Needs attention' : 'Available',
  privacy: 'Verification pending',
  diagnostics:
    channelsError.value || aiError.value || notificationError.value || runtimeHealthError.value || translationError.value || translationHealth.value?.state === 'needs_attention'
      ? 'Needs attention'
      : runtimeState.value,
}))

const stateClass = (state: ProductState) =>
  state.toLowerCase().replace(/\s+/g, '-')

const selectSection = (id: SettingsSectionId) => {
  selectedId.value = id
}
</script>

<template>
  <DashboardLayout>
    <YanceWebShell>
    <main class="yance-settings" data-yance-settings-native-composition>
      <header class="settings-heading">
        <div>
          <p class="eyebrow">言策 Yance</p>
          <h1>设置</h1>
          <p>管理连接、AI、外观和其他产品设置。不可用的功能会明确标记。</p>
        </div>
        <RouterLink class="back-home" to="/yance/home">返回首页</RouterLink>
      </header>

      <div class="settings-layout">
        <nav class="settings-nav" aria-label="言策设置">
          <button
            v-for="section in sections"
            :key="section.id"
            type="button"
            class="settings-nav-item"
            :class="{ active: selectedId === section.id }"
            :aria-current="selectedId === section.id ? 'page' : undefined"
            :data-settings-section="section.id"
            @click="selectSection(section.id)"
          >
            <span>{{ section.label }}</span>
            <span
              class="nav-state"
              :class="stateClass(sectionStatus[section.id])"
            >
              {{ productStateLabel(sectionStatus[section.id]) }}
            </span>
          </button>
        </nav>

        <section class="settings-pane" :data-active-settings-section="selected.id">
          <header class="pane-heading">
            <div>
              <h2>{{ selected.label }}</h2>
              <p>{{ selected.description }}</p>
            </div>
            <span
              class="truth-state"
              :class="stateClass(sectionStatus[selected.id])"
              :data-settings-product-state="sectionStatus[selected.id]"
            >
              {{ productStateLabel(sectionStatus[selected.id]) }}
            </span>
          </header>

          <template v-if="selectedId === 'accounts'">
            <div class="section-actions" data-native-owner="IntegrationsSettings">
              <div>
                <h3>消息平台</h3>
                <p>这里显示当前账号状态。添加、重连、切换或移除账号时，会进入现有平台管理页。</p>
              </div>
              <RouterLink class="primary-action" to="/yance/platform-accounts">
                管理平台账号
              </RouterLink>
            </div>

            <div class="status-grid platform-grid">
              <article
                v-for="platform in platformCards"
                :key="platform.type"
                class="status-card"
                :data-platform="platform.type"
              >
                <div class="card-heading">
                  <strong>{{ platform.label }}</strong>
                  <span class="state-badge" :class="stateClass(platform.state)">
                    {{ productStateLabel(platform.state) }}
                  </span>
                </div>
                <p>{{ platform.detail }}</p>
                <small v-if="platform.active.length > 1">
                  {{ platform.active.length }} 个已启用账号（连接健康需分别核验）
                </small>
                <small v-if="platform.type === 'line' && platform.accounts.length > platform.active.length">
                  {{ platform.accounts.length - platform.active.length }} 个 LINE 账号需要处理
                </small>
              </article>
            </div>

            <div v-if="channelsError" class="notice-card attention">
              <strong>平台状态暂时无法读取</strong>
              <p>打开平台管理页可重试连接或检查账号。</p>
              <button type="button" class="text-action" @click="loadChannelAccounts">重试</button>
            </div>
          </template>

          <template v-else-if="selectedId === 'ai'">
            <div class="section-actions" data-native-owner="AIConfigSettings">
              <div>
                <h3>当前 AI 配置</h3>
                <p v-if="hasExistingConfig && !aiLoading" data-yance-ai-config-state="stored-not-inference-ready">
                  已保存模型配置（推理尚未验证）：{{ setupConfig.provider || '已配置提供商' }}
                  <template v-if="setupConfig.model"> · {{ setupConfig.model }}</template>
                </p>
                <p v-else-if="aiLoading">正在读取当前配置…</p>
                <p v-else-if="aiError" data-yance-ai-config-state="error">模型配置读取失败，当前不能认定 AI 可用。</p>
                <p v-else data-yance-ai-config-state="not-configured">尚未配置默认 AI 模型（原生 AIConfig 未找到时包括 HTTP 404）；未执行推理，也没有已连接模型。</p>
              </div>
              <RouterLink class="primary-action" to="/yance/manage/ai">
                管理 AI 与模型
              </RouterLink>
            </div>

            <div class="feature-list">
              <div class="feature-row">
                <div><strong>默认模型</strong><p>用于日常回复的当前模型。</p></div>
                <span class="state-badge" :class="stateClass(aiState)">{{ productStateLabel(aiState) }}</span>
              </div>
              <div class="feature-row">
                <div><strong>Provider</strong><p>在现有 AI 设置中管理凭据与模型。</p></div>
                <span class="state-badge" :class="stateClass(aiState)">{{ productStateLabel(aiState) }}</span>
              </div>
              <div class="feature-row" data-native-owner="AIConfig.settings.reasoning_strength">
                <div><strong>推理强度</strong><p>仅对当前模型明确支持的 provider-native reasoning 参数开放。</p></div>
                <span class="state-badge" :class="stateClass(reasoningState)">{{ productStateLabel(reasoningState) }}</span>
              </div>
              <div class="feature-row">
                <div><strong>任务模型映射</strong><p>尚无任务模型映射编辑入口；请在现有 AI 设置检查默认模型。</p></div>
                <span class="state-badge unavailable">{{ productStateLabel('Unavailable') }}</span>
              </div>
              <div class="feature-row" data-native-owner="AIConfig.settings.fallback_model_name">
                <div><strong>备用模型</strong><p>同一 provider / credential 下由 Agno native fallback_models 执行。</p></div>
                <span class="state-badge" :class="stateClass(fallbackState)">{{ productStateLabel(fallbackState) }}</span>
              </div>
            </div>
          </template>

          <template v-else-if="selectedId === 'persona'">
            <div class="section-actions" data-settings-runtime-state="persona-unverified" data-native-owner="YancePersonaStudio">
              <div>
                <h3>人格与学习</h3>
                <p>基础人格继续由 Agent.instructions 保存；种子、风格素材与审核过的 guideline 复用现有 Knowledge / PgVector，历史与回滚由 SQLAlchemy-Continuum 提供。</p>
              </div>
              <RouterLink class="primary-action" to="/yance">
                打开当前对话的人格工作室
              </RouterLink>
            </div>
            <div class="feature-list">
              <div class="feature-row">
                <div><strong>全局 / 当前 Persona</strong><p>查看和保存当前基础人格，并使用版本历史回滚。当前对话读写与版本回滚需在真实账号下核验。</p></div>
                <span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span>
              </div>
              <div class="feature-row">
                <div><strong>联系人绑定</strong><p>在当前对话的人格工作室中为该联系人选择 Persona。当前对话读写与版本回滚需在真实账号下核验。</p></div>
                <span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span>
              </div>
              <div class="feature-row">
                <div><strong>会话与本轮覆盖</strong><p>会话 override 写入现有 SessionToAgent；仅本轮 override 不持久化。当前对话读写与版本回滚需在真实账号下核验。</p></div>
                <span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span>
              </div>
              <div class="feature-row">
                <div><strong>Seed / Style Corpus / 比较</strong><p>Character Card 导入、预览、2–3 个 Persona 比较及显式授权的风格素材都使用同一 Persona Studio。当前对话读写与版本回滚需在真实账号下核验。</p></div>
                <span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span>
              </div>
              <div class="feature-row">
                <div><strong>学习规则与历史</strong><p>审核过的 guideline 进入现有 ChatAgent/Reply Brain；长期学习按已有记录和明确授权持续完善。当前对话读写与版本回滚需在真实账号下核验。</p></div>
                <span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span>
              </div>
            </div>
          </template>

          <template v-else-if="selectedId === 'memory'">
            <div class="notice-card" data-settings-runtime-state="memory-readonly">
              <strong>现有关系资料可查看，记忆推理待核验</strong>
              <p>已接入现有联系人与关系世界只读入口，不新建数据表；图谱推理或自动写入没有运行验收，不能显示已连接。</p>
              <RouterLink class="secondary-action" to="/yance/relationship">查看关系世界</RouterLink>
            </div>
            <div class="feature-list">
              <div class="feature-row"><div><strong>已确认</strong><p>现有联系人事实可在关系世界只读查看；当前内容取决于真实联系人数据。</p></div><span class="state-badge available">{{ productStateLabel('Available') }}</span></div>
              <div class="feature-row"><div><strong>AI 推测 · 待确认</strong><p>需要真实模型、证据和用户批准；当前没有成功运行证明。</p></div><span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span></div>
              <div class="feature-row"><div><strong>关系洞察</strong><p>仅显示现有可核验关系资料，推测功能仍待验收。</p></div><span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span></div>
              <div class="feature-row"><div><strong>来源与证据</strong><p>只读投影保留来源，不为缺少的证据创建假内容。</p></div><span class="state-badge available">{{ productStateLabel('Available') }}</span></div>
            </div>
          </template>

          <template v-else-if="selectedId === 'translation'">
            <div
              class="settings-card"
              data-native-owner="deepl.official_translation_api"
              :data-settings-runtime-state="translationHealth?.state || 'unknown'"
            >
              <div class="card-heading">
                <div>
                  <h3>DeepL 官方翻译</h3>
                  <p>原文始终 primary，中文只作 secondary；发送前译文必须由你采用回同一个 Composer。</p>
                </div>
                <span class="state-badge" :class="stateClass(translationState)">{{ productStateLabel(translationState) }}</span>
              </div>
              <p v-if="translationHealth?.errorCode">服务状态：{{ translationHealth.errorCode }}</p>
              <p v-if="translationState === 'Not configured'">尚未配置 DeepL 凭据或授权。请完成官方翻译服务配置后重新检查；本地联系人语言与完整性检查不能替代翻译接口。</p>
              <p v-else-if="translationState === 'Needs attention'">翻译健康检查失败或服务异常；查看后端翻译日志并重试，不能判定为已连接。</p>
              <p v-else-if="translationState === 'Connected'">翻译健康接口报告已连接；实际入站、出站翻译仍须在对话中验证。</p>
              <button type="button" class="text-action" :disabled="translationLoading" @click="loadTranslationHealth">
                重新检查
              </button>
            </div>
            <div class="feature-list">
              <div class="feature-row"><div><strong>联系人语言</strong><p>联系人语言是本地设置，不是 DeepL 连接状态。可在对话中核实记录。</p></div><span class="state-badge available">{{ productStateLabel('Available') }}</span></div>
              <div class="feature-row"><div><strong>入站理解</strong><p>按精确 ChatHistory.id 生成中文 secondary，不覆盖原文。</p></div><span class="state-badge" :class="stateClass(translationState)">{{ productStateLabel(translationState) }}</span></div>
              <div class="feature-row"><div><strong>出站预览</strong><p>保留 Persona、口语程度、emoji 与聊天节奏，通过后才允许采用。</p></div><span class="state-badge" :class="stateClass(translationState)">{{ productStateLabel(translationState) }}</span></div>
              <div class="feature-row"><div><strong>完整性 / stale</strong><p>本地校验规则独立于翻译提供商健康；缺少翻译结果时不能保证可生成译文。</p></div><span class="state-badge available">{{ productStateLabel('Available') }}</span></div>
            </div>
          </template>

          <template v-else-if="selectedId === 'voice-media'">
            <div class="notice-card attention" data-settings-runtime-state="voice-media-runtime-unverified">
              <strong>现有媒体收发与生成配置分别核验</strong>
              <p>消息附件继续使用对话中的原生 FileAttachment；语音合成、转写和媒体生成尚无当前运行环境的成功凭证，须检查服务配置并完成实际试用，不能一概称为不可用或已连接。</p>
              <RouterLink class="secondary-action" to="/yance">进入对话查看附件</RouterLink>
            </div>
            <div class="feature-list">
              <div class="feature-row"><div><strong>语音档案</strong><p>语音供应商与身份配置待实际验证；没有配置时不得显示可用声音。</p></div><span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span></div>
              <div class="feature-row"><div><strong>默认语音预览</strong><p>需要服务授权与真实试听通过后才可认定可用。</p></div><span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span></div>
              <div class="feature-row"><div><strong>消息附件</strong><p>消息附件由现有 FileAttachment 保存，在对话查看；独立媒体库尚未核验。</p></div><span class="state-badge available">{{ productStateLabel('Available') }}</span></div>
              <div class="feature-row"><div><strong>生成与编辑</strong><p>供应商、授权和实际生成调用需逐项验证；不代表服务已连接。</p></div><span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span></div>
            </div>
          </template>

          <template v-else-if="selectedId === 'automation'">
            <div class="section-actions" data-native-owner="ConversationReplyMode">
              <div>
                <h3>回复方式</h3>
                <p>当前回复方式仍在对话中管理；此页不会保存另一份状态。</p>
              </div>
              <RouterLink class="primary-action" to="/yance">打开对话</RouterLink>
            </div>
            <div class="feature-list">
              <div class="feature-row"><div><strong>由我回复</strong><p>在对话 Composer 由用户手动发送；不是外部服务连接。</p></div><span class="state-badge available">{{ productStateLabel('Available') }}</span></div>
              <div class="feature-row"><div><strong>建议我</strong><p>复用已有 Reply Brain；实际生成仍依赖已配置且可推理的模型。</p></div><span class="state-badge" :class="stateClass(aiState)">{{ productStateLabel(aiState) }}</span></div>
              <div class="feature-row"><div><strong>自动处理</strong><p>已有回复模式入口；自动发送必须经账号、策略和真实运行检查。</p></div><span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span></div>
              <div class="feature-row"><div><strong>敏感动作确认</strong><p>沿用原生确认流程；端到端权限阻断还需独立测试。</p></div><span class="state-badge verification-pending">{{ productStateLabel('Verification pending') }}</span></div>
            </div>
          </template>

          <template v-else-if="selectedId === 'appearance'">
            <div class="settings-card" data-native-owner="useTheme">
              <div class="card-heading">
                <div>
                  <h3>外观模式</h3>
                  <p>立即应用到当前界面。</p>
                </div>
                <span class="state-badge available">{{ productStateLabel('Available') }}</span>
              </div>
              <div class="theme-options" role="group" aria-label="外观模式">
                <button
                  v-for="option in themeOptions"
                  :key="option.value"
                  type="button"
                  class="theme-option"
                  :class="{ active: mode === option.value }"
                  :aria-pressed="mode === option.value"
                  @click="setTheme(option.value)"
                >
                  {{ option.label }}
                </button>
              </div>
            </div>

            <div class="feature-list appearance-list">
              <div class="feature-row">
                <div><strong>界面密度</strong><p>紧凑或舒适的布局密度。</p></div>
                <span class="state-badge unavailable">{{ productStateLabel('Unavailable') }}</span>
              </div>
              <div class="feature-row">
                <div><strong>文字大小</strong><p>独立调整产品文字大小。</p></div>
                <span class="state-badge unavailable">{{ productStateLabel('Unavailable') }}</span>
              </div>
              <div class="feature-row" data-native-owner="UserSettingsNotifications">
                <div>
                  <strong>桌面通知</strong>
                  <p v-if="notificationLoading">正在读取通知偏好…</p>
                  <p v-else-if="notificationError">通知偏好当前无法读取。</p>
                  <p v-else>现有聊天事件通知在个人设置中管理。</p>
                </div>
                <span class="state-badge" :class="stateClass(notificationState)">
                  {{ productStateLabel(notificationState) }}
                </span>
              </div>
              <div class="feature-row" data-native-owner="UserNotificationSettings.sound_enabled"><div><strong>提示音</strong><p v-if="notificationLoading">正在读取提示音偏好…</p><p v-else-if="notificationError">提示音偏好当前无法读取。</p><p v-else>{{ notificationSettings?.sound_enabled ? '已启用提示音。' : '提示音已关闭。' }}</p></div><span class="state-badge" :class="stateClass(notificationState)">{{ productStateLabel(notificationState) }}</span></div>
              <div class="feature-row"><div><strong>通知预览</strong><p>当前没有可保存的预览模式。</p></div><span class="state-badge unavailable">{{ productStateLabel('Unavailable') }}</span></div>
              <div class="feature-row"><div><strong>勿扰时段</strong><p>当前没有可保存的勿扰时段。</p></div><span class="state-badge unavailable">{{ productStateLabel('Unavailable') }}</span></div>
            </div>

            <RouterLink class="secondary-action" to="/yance/manage/user">管理个人通知</RouterLink>
          </template>

          <template v-else-if="selectedId === 'privacy'">
            <div class="notice-card attention" data-settings-runtime-state="system-lifecycle-mixed">
              <strong>网页功能与安装包验收分开显示</strong>
              <p>网页上传、对话导出已有操作入口；桌面文件选择器、备份恢复和更新功能仍待最终安装包验证，不代表已连接。</p>
            </div>
            <div class="feature-list">
              <div class="feature-row" data-native-owner="FileUpload/FileAttachment">
                <div><strong>文件访问</strong><p>网页上传使用现有 FileUpload → FileAttachment；本机原生 picker 仍需最终 Tauri package UAT。</p></div>
                <span class="state-badge needs-attention">{{ productStateLabel('Needs attention') }}</span>
              </div>
              <div class="feature-row" data-native-owner="PostgreSQL pg_dump + restic 0.19.1" data-settings-runtime-state="package-uat-hold">
                <div><strong>备份 / 恢复</strong><p>既有 Windows runtime 已资格化 PostgreSQL logical backup + restic；产品不创建第二备份引擎，最终安装包入口保持 PACKAGE_UAT_HOLD。</p></div>
                <span class="state-badge needs-attention">{{ productStateLabel('Needs attention') }}</span>
              </div>
              <div class="feature-row" data-native-owner="ChatHistory/FileAttachment">
                <div><strong>对话导出</strong><p>使用现有 Conversation 导出入口；仅表示本地功能，真实数据导出仍按权限测试。</p></div>
                <span class="state-badge available">{{ productStateLabel('Available') }}</span>
              </div>
              <div class="feature-row" data-native-owner="Velopack" data-settings-runtime-state="package-uat-hold">
                <div><strong>更新</strong><p>桌面更新 owner = Velopack；C3 不安装第二 Tauri updater，installed-package 行为等待 package UAT。</p></div>
                <span class="state-badge needs-attention">{{ productStateLabel('Needs attention') }}</span>
              </div>
            </div>
          </template>

          <template v-else-if="selectedId === 'diagnostics'">
            <div class="feature-list diagnostics-list" data-native-owner="ExistingDiagnosticsOwners">
              <div class="feature-row">
                <div><strong>平台连接</strong><p>来自当前消息平台账号状态。</p></div>
                <span class="state-badge" :class="stateClass(accountsState)">{{ productStateLabel(accountsState) }}</span>
              </div>
              <div class="feature-row">
                <div><strong>AI 配置</strong><p>来自当前 AI 设置状态。</p></div>
                <span class="state-badge" :class="stateClass(aiState)">{{ productStateLabel(aiState) }}</span>
              </div>
              <div class="feature-row">
                <div><strong>通知设置</strong><p>来自当前个人通知偏好。</p></div>
                <span class="state-badge" :class="stateClass(notificationState)">{{ productStateLabel(notificationState) }}</span>
              </div>
              <div class="feature-row">
                <div><strong>翻译服务</strong><p>DeepL 官方 Translation API；状态来自实时服务健康检查，不把“已配置”误报为可用。</p></div>
                <span class="state-badge" :class="stateClass(translationState)">{{ productStateLabel(translationState) }}</span>
              </div>
              <div class="feature-row" data-native-owner="browser_profile_enrichment" data-settings-runtime-state="active-executor-not-admitted">
                <div><strong>Browser companion</strong><p>被动 profile enrichment primitive 已存在并有独立测试；active browser executor 未 admitted，因此这里只投影边界，不宣称已连接。</p></div>
                <span class="state-badge needs-attention">{{ productStateLabel('Needs attention') }}</span>
              </div>
              <div class="feature-row" data-native-owner="backend /health">
                <div><strong>运行状态证明</strong><p>按需读取现有 backend health，不创建 watchdog 或 polling daemon。</p></div>
                <span class="state-badge" :class="stateClass(runtimeState)">{{ productStateLabel(runtimeState) }}</span>
              </div>
              <div class="feature-row" data-native-owner="backend version + package lineage" data-settings-runtime-state="package-uat-hold">
                <div><strong>版本 / 构建 / 评估 lineage</strong><p>Backend version：{{ runtimeHealth?.version || 'unknown' }}。最终 package commit/build manifest 仅在安装包 UAT 后可提升为完整证据。</p></div>
                <span class="state-badge needs-attention">{{ productStateLabel('Needs attention') }}</span>
              </div>
            </div>
            <div class="inline-actions">
              <RouterLink class="secondary-action" to="/yance/platform-accounts">管理平台</RouterLink>
              <RouterLink class="secondary-action" to="/yance/manage/ai">管理 AI</RouterLink>
              <RouterLink class="secondary-action" to="/yance/manage/user">管理通知</RouterLink>
            </div>
          </template>

          <aside class="native-foundation" aria-label="其他设置">
            <div>
              <strong>个人资料</strong>
              <p>姓名、头像、密码和聊天通知。</p>
              <RouterLink to="/yance/manage/user">打开</RouterLink>
            </div>
            <div>
              <strong>工作区</strong>
              <p>时区、营业时间和工作区规则。</p>
              <RouterLink to="/yance/manage/organization">打开</RouterLink>
            </div>
          </aside>
        </section>
      </div>
    </main>
      </YanceWebShell>
  </DashboardLayout>
</template>

<style scoped>
.yance-settings {
  width: min(1120px, calc(100% - 40px));
  margin: 0 auto;
  padding: 28px 0 44px;
}

.settings-heading,
.pane-heading,
.section-actions,
.card-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-lg);
}

.settings-heading {
  margin-bottom: 22px;
}

.eyebrow {
  margin: 0 0 5px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent-ink);
}

.settings-heading h1,
.pane-heading h2,
.section-actions h3,
.settings-card h3 {
  font-family: var(--font-display);
  color: var(--text);
}

.settings-heading h1 {
  margin: 0;
  font-size: 30px;
  letter-spacing: -0.02em;
}

.settings-heading p,
.pane-heading p,
.section-actions p,
.settings-card p,
.status-card p,
.feature-row p,
.native-foundation p,
.notice-card p {
  color: var(--muted);
}

.settings-heading p {
  margin: 6px 0 0;
  font-size: 14px;
}

.settings-layout {
  display: grid;
  grid-template-columns: 238px minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}

.settings-nav {
  display: grid;
  gap: 7px;
  padding: 10px;
  border: 1px solid var(--o10);
  border-radius: var(--radius-card);
  background: var(--bg2);
  position: sticky;
  top: 18px;
}

.settings-nav-item {
  min-height: 48px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-btn);
  color: var(--muted);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.settings-nav-item:hover {
  color: var(--text);
  background: var(--o05);
}

.settings-nav-item.active {
  color: var(--text);
  border-color: var(--accent-border);
  background: var(--accent-bg-12);
}

.nav-state {
  max-width: 86px;
  font-size: 9.5px;
  line-height: 1.15;
  text-align: right;
  color: var(--muted2);
}

.settings-pane {
  min-width: 0;
}

.pane-heading {
  margin-bottom: 16px;
}

.pane-heading h2 {
  margin: 0;
  font-size: 25px;
}

.pane-heading p {
  max-width: 620px;
  margin: 6px 0 0;
  font-size: 13.5px;
  line-height: 1.5;
}

.truth-state,
.state-badge {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  border-radius: var(--radius-pill);
  border: 1px solid var(--o12);
  padding: 5px 9px;
  font-size: 10.5px;
  white-space: nowrap;
  color: var(--muted);
  background: var(--o04);
}

.truth-state.connected,
.state-badge.connected,
.nav-state.connected,
.truth-state.available,
.state-badge.available,
.nav-state.available {
  color: var(--c-teal);
}

.truth-state.needs-attention,
.state-badge.needs-attention,
.nav-state.needs-attention,
.truth-state.verification-pending,
.state-badge.verification-pending,
.nav-state.verification-pending {
  color: var(--c-coral);
}

.truth-state.unavailable,
.state-badge.unavailable,
.nav-state.unavailable {
  color: var(--muted2);
}

.truth-state.loading,
.state-badge.loading,
.nav-state.loading {
  color: var(--accent-ink);
}

.section-actions,
.settings-card,
.status-card,
.feature-list,
.notice-card,
.native-foundation > div {
  border: 1px solid var(--o10);
  border-radius: var(--radius-card);
  background: var(--surface);
}

.section-actions,
.settings-card,
.notice-card {
  padding: 19px 20px;
  margin-bottom: 13px;
}

.section-actions h3,
.settings-card h3 {
  margin: 0 0 6px;
  font-size: 17px;
}

.section-actions p,
.settings-card p,
.notice-card p {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.5;
}

.notice-card.unavailable {
  background: var(--bg2);
}

.notice-card.attention {
  border-color: var(--coral-border);
  background: var(--coral-bg);
}

.notice-card strong {
  display: block;
  margin-bottom: 5px;
  color: var(--text);
}

.back-home,
.primary-action,
.secondary-action,
.native-foundation a {
  text-decoration: none;
}

.back-home,
.secondary-action,
.native-foundation a,
.text-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 11px;
  border: 1px solid var(--o12);
  border-radius: var(--radius-btn);
  color: var(--text3);
  background: var(--o04);
  font: inherit;
  font-size: 13px;
}

.back-home {
  flex: 0 0 auto;
}

.primary-action {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 14px;
  border-radius: var(--radius-btn);
  color: var(--on-accent-solid);
  background: var(--accent-solid);
  font-size: 13px;
  font-weight: 600;
}

.text-action {
  margin-top: 10px;
  cursor: pointer;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
  margin-bottom: 13px;
}

.status-card {
  padding: 16px;
}

.card-heading {
  gap: 10px;
  align-items: center;
}

.status-card strong,
.feature-row strong,
.native-foundation strong {
  color: var(--text);
}

.status-card p {
  margin: 7px 0 0;
  font-size: 13px;
  line-height: 1.45;
}

.status-card small {
  display: block;
  margin-top: 8px;
  color: var(--muted2);
}

.feature-list {
  overflow: hidden;
  margin-bottom: 13px;
}

.feature-row {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--o08);
}

.feature-row:last-child {
  border-bottom: 0;
}

.feature-row p {
  margin: 4px 0 0;
  font-size: 12.5px;
  line-height: 1.4;
}

.theme-options,
.inline-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.theme-options {
  margin-top: 14px;
}

.theme-option {
  min-height: 36px;
  padding: 0 13px;
  border: 1px solid var(--o12);
  border-radius: var(--radius-btn);
  color: var(--text3);
  background: var(--o04);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.theme-option.active {
  color: var(--accent-ink);
  border-color: var(--accent-border);
  background: var(--accent-bg-12);
}

.inline-actions {
  margin: 4px 0 14px;
}

.native-foundation {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--o08);
}

.native-foundation > div {
  padding: 15px;
}

.native-foundation p {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.45;
}

.native-foundation a {
  margin-top: 11px;
}

@media (max-width: 900px) {
  .yance-settings {
    width: min(100% - 24px, 760px);
    padding-top: 18px;
  }

  .settings-layout {
    grid-template-columns: 1fr;
  }

  .settings-nav {
    position: static;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .pane-heading,
  .section-actions {
    flex-direction: column;
  }

  .primary-action {
    align-self: flex-start;
  }
}

@media (max-width: 560px) {
  .settings-heading {
    flex-direction: column;
  }

  .settings-nav,
  .status-grid,
  .native-foundation {
    grid-template-columns: 1fr;
  }

  .truth-state {
    align-self: flex-start;
  }

  .feature-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
