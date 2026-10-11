<script setup lang="ts">
import YanceWebShell from './components/YanceWebShell.vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { formatDistanceToNow } from 'date-fns'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import YanceFirstRunHome from './components/YanceFirstRunHome.vue'
import ChannelBadge from '@/components/common/ChannelBadge.vue'
import HandlerBadge from '@/components/conversations/HandlerBadge.vue'
import CustomerAvatar from '@/components/people/CustomerAvatar.vue'
import { chatService } from '@/services/chat'
import channelsService, { type ChannelAccount } from '@/services/channels'
import { useConversationsList } from '@/composables/useConversationsList'
import { userService } from '@/services/user'
import type { Conversation } from '@/types/chat'
import { personProfileLine } from '@/utils/personProfile'

const router = useRouter()
const currentUserId = userService.getUserId()
const conversations = ref<Conversation[]>([])
const loading = ref(true)
const firstRunEmpty = computed(() => !loading.value && !error.value && !channelStatusLoading.value && !channelStatusError.value && channelAccounts.value !== null && channelAccounts.value.length === 0 && conversations.value.length === 0)
const error = ref('')

const channelAccounts = ref<ChannelAccount[] | null>(null)
const channelStatusLoading = ref(true)
const channelStatusError = ref(false)

// Reuse the native Inbox unread/socket owner instead of creating Home-specific
// unread persistence. This preserves the same live unread semantics as Inbox.
const homeInboxProps = {
  get conversations() { return conversations.value },
  get loading() { return loading.value },
  get error() { return error.value },
  hasMore: false,
  loadingMore: false,
}
const homeInboxEmit = ((..._args: unknown[]) => {}) as Parameters<typeof useConversationsList>[1]
const { unreadMessages } = useConversationsList(homeInboxProps, homeInboxEmit)

const activeConversations = computed(() =>
  conversations.value.filter((conversation) => conversation.status !== 'closed')
)
const continueConversations = computed(() =>
  (activeConversations.value.length ? activeConversations.value : conversations.value).slice(0, 3)
)
const recentConversations = computed(() => conversations.value.slice(0, 6))
const unreadConversationCount = computed(() =>
  conversations.value.reduce(
    (count, conversation) => count + ((unreadMessages[conversation.session_id] ?? 0) > 0 ? 1 : 0),
    0,
  )
)
const inactiveAccounts = computed(() =>
  (channelAccounts.value ?? []).filter((account) => !account.is_active)
)
const activeAccountCount = computed(() =>
  (channelAccounts.value ?? []).filter((account) => account.is_active).length
)

const connectionStatusLabel = computed(() => {
  if (channelStatusLoading.value) return '平台连接读取中'
  if (channelStatusError.value) return '平台连接状态暂不可用'
  if (!channelAccounts.value?.length) return '尚未连接消息平台'
  return `${activeAccountCount.value}/${channelAccounts.value.length} 个平台账号已启用`
})

async function loadHomeProjection() {
  loading.value = true
  error.value = ''
  try {
    // One native Inbox query feeds every Home conversation projection below.
    conversations.value = await chatService.getRecentChats({ limit: 12, status: 'all' })
  } catch {
    error.value = '暂时无法加载最近对话'
  } finally {
    loading.value = false
  }
}

async function loadChannelStatus() {
  channelStatusLoading.value = true
  channelStatusError.value = false
  try {
    channelAccounts.value = await channelsService.listAccounts()
  } catch {
    channelAccounts.value = null
    channelStatusError.value = true
  } finally {
    channelStatusLoading.value = false
  }
}

function openConversation(sessionId: string) {
  router.push({ path: '/yance', query: { session: sessionId } })
}

function openRelationshipWorld(customerId?: string | null) {
  router.push(customerId ? `/yance/relationship/${customerId}` : '/yance/relationship')
}

function displayName(conversation: Conversation): string {
  return conversation.customer.full_name || conversation.customer.email || '未命名联系人'
}

function profileLine(conversation: Conversation): string {
  return personProfileLine(conversation.customer.profile, 'zh-CN')
}

function timeAgo(updatedAt: string): string {
  try {
    return formatDistanceToNow(new Date(updatedAt), { addSuffix: true })
  } catch {
    return ''
  }
}

function statusLabel(status: Conversation['status']): string {
  if (status === 'transferred') return '需要人工处理'
  if (status === 'closed') return '已结束'
  return '进行中'
}

function accountLabel(account: ChannelAccount): string {
  return account.display_name || account.channel_type
}

onMounted(() => {
  void loadHomeProjection()
  void loadChannelStatus()
})
</script>

<template>
  <DashboardLayout>
    <YanceWebShell :connection-summary="connectionStatusLabel">
    <main class="yance-home-native" data-yance-home-native-composition>
      <header class="home-heading">
        <div>
          <p class="eyebrow">{{ firstRunEmpty ? '真实空账号场景 · 交互设计' : '言策 Yance' }}</p>
          <h1>{{ firstRunEmpty ? '今天的工作台' : '首页' }}</h1>
          <p v-if="!firstRunEmpty" class="home-subtitle">把近期对话、值得关注的事项和平台状态集中在这里。</p>
        </div>
        <div class="home-heading-actions">
          <button type="button" class="nav-link active" aria-current="page">首页</button>
          <button type="button" class="nav-link" @click="router.push('/yance')">对话</button>
          <button type="button" class="nav-link" @click="openRelationshipWorld()">关系世界</button>
          <button type="button" class="nav-link" @click="router.push('/yance/settings')">设置</button>
          <button type="button" class="nav-link secondary" @click="router.push('/yance/people')">人物</button>
        </div>
      </header>

      <YanceFirstRunHome v-if="firstRunEmpty" :supported-platforms="8" :connected-platforms="activeAccountCount" />

      <div v-show="!firstRunEmpty" class="connection-pill" :class="{ warning: channelStatusError || inactiveAccounts.length > 0 }">
        <span class="connection-dot" aria-hidden="true"></span>
        <span>{{ connectionStatusLabel }}</span>
      </div>

      <section v-show="!firstRunEmpty" class="home-section continue-section" aria-labelledby="continue-title">
        <div class="section-title-row">
          <div>
            <h2 id="continue-title">继续对话</h2>
            <p>回到最近的联系人和会话。</p>
          </div>
        </div>

        <div v-if="loading" class="home-state">正在加载…</div>
        <div v-else-if="error" class="home-state error">
          <span>{{ error }}</span>
          <button type="button" @click="loadHomeProjection">重试</button>
        </div>
        <div v-else-if="continueConversations.length === 0" class="home-state">暂无最近对话。</div>

        <div v-else class="continue-grid">
          <article
            v-for="conversation in continueConversations"
            :key="conversation.session_id"
            class="continue-item"
            data-native-conversation-projection
          >
            <div class="identity-row">
              <CustomerAvatar
                class="home-avatar"
                :profile="conversation.customer.profile"
                :display-name="displayName(conversation)"
                :size="40"
              />
              <div class="identity-copy">
                <strong>{{ displayName(conversation) }}</strong>
                <span v-if="profileLine(conversation)" class="profile-line">{{ profileLine(conversation) }}</span>
              </div>
              <ChannelBadge :channel="conversation.channel" />
            </div>

            <p class="last-message">{{ conversation.last_message || '暂无消息预览' }}</p>

            <div class="conversation-meta">
              <span>{{ statusLabel(conversation.status) }}</span>
              <span>{{ timeAgo(conversation.updated_at) }}</span>
              <span>{{ conversation.message_count }} 条消息</span>
              <span v-if="unreadMessages[conversation.session_id]" class="unread-state">
                {{ unreadMessages[conversation.session_id] }} 条未读
              </span>
            </div>

            <div class="item-actions">
              <HandlerBadge :chat="conversation" :current-user-id="currentUserId" />
              <div class="action-group">
                <button
                  type="button"
                  class="quiet-action"
                  @click="openRelationshipWorld(conversation.customer.id)"
                >
                  关系资料
                </button>
                <button type="button" class="primary-action" @click="openConversation(conversation.session_id)">
                  继续对话
                </button>
              </div>
            </div>
          </article>
        </div>
      </section>

      <div v-show="!firstRunEmpty" class="home-lower-grid">
        <section class="home-section recent-activity" aria-labelledby="recent-title" data-home-recent-activity>
          <div class="section-title-row">
            <div>
              <h2 id="recent-title">最近发生</h2>
              <p>只显示当前收件箱中已经发生的更新。</p>
            </div>
          </div>

          <div v-if="loading" class="home-state compact">正在读取…</div>
          <div v-else-if="recentConversations.length === 0" class="home-state compact">暂无最近活动。</div>
          <button
            v-for="conversation in recentConversations"
            v-else
            :key="conversation.session_id"
            type="button"
            class="activity-row"
            @click="openConversation(conversation.session_id)"
          >
            <CustomerAvatar
              class="recent-avatar"
              :profile="conversation.customer.profile"
              :display-name="displayName(conversation)"
              :size="32"
            />
            <span class="activity-copy">
              <strong>
                {{
                  unreadMessages[conversation.session_id]
                    ? `${unreadMessages[conversation.session_id]} 条未读消息`
                    : '对话有更新'
                }}
              </strong>
              <small>{{ displayName(conversation) }} · {{ conversation.last_message || '暂无消息预览' }}</small>
            </span>
            <span class="activity-time">{{ timeAgo(conversation.updated_at) }}</span>
          </button>
        </section>

        <div class="home-right-stack">
          <section class="home-section attention-section" aria-labelledby="attention-title" data-home-attention>
            <div class="section-title-row">
              <div>
                <h2 id="attention-title">今天值得注意</h2>
                <p>有真实来源的项目才显示数量。</p>
              </div>
            </div>

            <div class="attention-grid">
              <article class="attention-item fact">
                <span>未读对话</span>
                <strong>{{ unreadConversationCount }}</strong>
                <small>当前收件箱</small>
              </article>
              <article class="attention-item unavailable">
                <span>重要日期</span>
                <strong>暂不可用</strong>
                <small>关系能力尚未启用</small>
              </article>
              <article class="attention-item unavailable">
                <span>关系提醒</span>
                <strong>暂不可用</strong>
                <small>不生成推测数据</small>
              </article>
              <article class="attention-item unavailable">
                <span>待确认关系信息</span>
                <strong>暂不可用</strong>
                <small>暂无可信来源</small>
              </article>
            </div>
          </section>

          <section
            class="home-section exception-section"
            aria-labelledby="exception-title"
            data-home-runtime-exceptions
          >
            <div class="section-title-row">
              <div>
                <h2 id="exception-title">连接 / 运行异常</h2>
                <p>这里仅报告能够从平台账号状态确认的问题。</p>
              </div>
            </div>

            <div v-if="channelStatusLoading" class="exception-card neutral">
              正在读取平台连接状态…
            </div>
            <div v-else-if="channelStatusError" class="exception-card warning">
              <div>
                <strong>暂时无法读取平台连接状态</strong>
                <p>如果收发消息异常，可前往平台连接页检查账号。</p>
              </div>
              <button type="button" @click="router.push('/yance/platform-accounts')">打开平台连接</button>
            </div>
            <div v-else-if="!channelAccounts?.length" class="exception-card neutral">
              <div>
                <strong>尚未连接消息平台</strong>
                <p>连接平台后，这里会显示可确认的账号状态。</p>
              </div>
              <button type="button" @click="router.push('/yance/platform-accounts')">连接平台</button>
            </div>
            <div v-else-if="inactiveAccounts.length" class="exception-card warning">
              <div>
                <strong>{{ inactiveAccounts.length }} 个平台账号当前未启用</strong>
                <p>{{ inactiveAccounts.map(accountLabel).join('、') }}</p>
              </div>
              <button type="button" @click="router.push('/yance/platform-accounts')">检查连接</button>
            </div>
            <div v-else class="exception-card ok">
              <div>
                <strong>已配置的平台账号均处于启用状态</strong>
                <p>这不代表实时收发一定正常；如遇异常，可继续进入平台连接页检查。</p>
              </div>
              <button type="button" @click="router.push('/yance/platform-accounts')">查看平台连接</button>
            </div>
          </section>
        </div>
      </div>
    </main>
      </YanceWebShell>
  </DashboardLayout>
</template>

<style scoped>
.yance-home-native {
  width: min(1180px, calc(100% - 40px));
  margin: 0 auto;
  padding: 26px 0 40px;
  color: var(--text);
}
.home-heading,
.section-title-row,
.identity-row,
.conversation-meta,
.item-actions,
.exception-card {
  display: flex;
  align-items: center;
}
.home-heading,
.section-title-row,
.item-actions,
.exception-card {
  justify-content: space-between;
}
.home-heading {
  gap: 20px;
  margin-bottom: 12px;
}
.home-heading-actions,
.action-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.eyebrow {
  margin: 0 0 4px;
  color: var(--muted);
  font-size: 12px;
}
.home-heading h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 28px;
}
.home-subtitle,
.section-title-row p {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 13px;
}
.nav-link,
.item-actions button,
.home-state button,
.exception-card button {
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o05);
  color: var(--text);
  padding: 8px 12px;
  cursor: pointer;
}
.nav-link.active,
.primary-action {
  border-color: var(--accent-border, var(--o20));
  background: var(--accent-bg-12, var(--o08));
  color: var(--accent-ink, var(--text));
}
.nav-link.secondary {
  color: var(--muted);
}
.connection-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 30px;
  padding: 0 11px;
  border: 1px solid var(--o10);
  border-radius: 999px;
  color: var(--muted);
  background: var(--bg2);
  font-size: 12px;
}
.connection-pill.warning {
  color: var(--warning, #b97700);
}
.connection-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.home-section {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid var(--o08);
  border-radius: var(--radius-lg, 14px);
  background: var(--bg2);
}
.section-title-row h2 {
  margin: 0;
  font-size: 19px;
}
.continue-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.continue-item {
  min-width: 0;
  border: 1px solid var(--o08);
  border-radius: var(--radius-lg, 14px);
  background: var(--bg);
  padding: 15px;
}
.identity-row {
  gap: 10px;
  min-width: 0;
}
.identity-copy {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
}
.identity-copy strong,
.profile-line,
.last-message,
.activity-copy strong,
.activity-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.profile-line {
  margin-top: 2px;
  color: var(--muted);
  font-size: 12px;
}
.last-message {
  margin: 16px 0 8px;
  color: var(--text2, var(--text));
  font-size: 13px;
}
.conversation-meta {
  gap: 8px;
  color: var(--muted);
  font-size: 11px;
  flex-wrap: wrap;
}
.unread-state {
  color: var(--accent-ink);
  font-weight: 600;
}
.item-actions {
  gap: 8px;
  margin-top: 14px;
}
.quiet-action {
  color: var(--muted) !important;
}
.home-lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(0, .92fr);
  gap: 18px;
}
.home-right-stack {
  min-width: 0;
}
.activity-row {
  width: 100%;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 11px;
  padding: 12px 0;
  border: 0;
  border-top: 1px solid var(--o08);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.activity-row:first-of-type {
  margin-top: 12px;
}
.activity-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.activity-copy strong {
  font-size: 13px;
}
.activity-copy small,
.activity-time {
  color: var(--muted);
  font-size: 11px;
}
.attention-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
  margin-top: 14px;
}
.attention-item {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--o08);
  border-radius: 11px;
  background: var(--bg);
}
.attention-item span,
.attention-item small {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.attention-item strong {
  display: block;
  margin: 8px 0 5px;
  font-size: 18px;
}
.attention-item.unavailable strong {
  font-size: 12px;
  color: var(--muted);
}
.exception-card {
  gap: 16px;
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--o08);
  border-radius: 12px;
  background: var(--bg);
}
.exception-card.warning {
  border-color: var(--warning-border, var(--o12));
}
.exception-card.ok strong {
  color: var(--text);
}
.exception-card p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.exception-card button {
  flex: 0 0 auto;
}
.home-state {
  margin-top: 16px;
  padding: 26px;
  text-align: center;
  color: var(--muted);
}
.home-state.compact {
  padding: 18px;
}
.home-state.error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

@media (max-width: 980px) {
  .continue-grid,
  .home-lower-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 720px) {
  .yance-home-native {
    width: calc(100% - 24px);
    padding-top: 16px;
  }
  .home-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .home-heading-actions {
    justify-content: flex-start;
  }
  .attention-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .exception-card {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
