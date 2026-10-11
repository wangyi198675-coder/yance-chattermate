<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ChatDetail, Conversation, Message } from '@/types/chat'
import ConversationsView from '@/views/ConversationsView.vue'
import { chatService } from '@/services/chat'
import YanceEmptyConversation from './components/YanceEmptyConversation.vue'
import YanceBilingualMessageProjection from './components/YanceBilingualMessageProjection.vue'
import YanceGirlfriendBrainNativeComposition from './components/YanceGirlfriendBrainNativeComposition.vue'
import YanceReplyBrainCandidateCard from './components/YanceReplyBrainCandidateCard.vue'
import YancePersonaStudio from './components/YancePersonaStudio.vue'
import YanceReplyBrainRuntimeComposition from './components/YanceReplyBrainRuntimeComposition.vue'
import type {
  YanceGirlfriendIntentDraft,
  YanceGirlfriendOrchestrationProjection,
  YanceReplyBrainCandidate,
  YanceReplyBrainStateProjection,
  YanceScopedTurnIntent,
  YanceTranslationProjection,
} from './semanticTypes'
import {
  FROZEN_UI_CAPABILITY_ROUTES,
  FROZEN_VOICE_MEDIA_UI_READINESS,
  type FrozenCapabilityRoute,
} from './capabilityWiring'

const props = withDefaults(defineProps<{
  translationsByMessageId?: Record<string, YanceTranslationProjection>
  replyCandidates?: YanceReplyBrainCandidate[]
  replyState?: YanceReplyBrainStateProjection
  girlfriendOrchestration?: YanceGirlfriendOrchestrationProjection
}>(), {
  translationsByMessageId: () => ({}),
  replyCandidates: () => [],
  replyState: undefined,
  girlfriendOrchestration: undefined,
})

const emit = defineEmits<{
  (event: 'capability-route', route: FrozenCapabilityRoute): void
  (event: 'reply-recompute'): void
  (event: 'girlfriend-undo-request'): void
  (event: 'girlfriend-permission-decision', decision: 'allow-once' | 'cancel'): void
}>()

const nativeEmptyConversations = ref(false)
const nativeEmptyLoading = ref(false)
const refreshNativeConversationEmpty = async () => {
  nativeEmptyLoading.value = true
  try {
    const conversations = await chatService.getRecentChats({ limit: 1, status: 'all' })
    nativeEmptyConversations.value = Array.isArray(conversations) && conversations.length === 0 && !new URLSearchParams(window.location.search).has('session')
  } catch { nativeEmptyConversations.value = false }
  finally { nativeEmptyLoading.value = false }
}
const replyBrainOpen = ref(false)
const expanded = ref(false)
const hasExternalReplyProjection = computed(
  () => props.replyState !== undefined || props.replyCandidates.length > 0,
)
const girlfriendBrainOpen = ref(false)
const personaStudioChat = ref<ChatDetail | null>(null)
type ActiveTurn = { sessionId: string; customerId: string; agentId: string; sourceMessageId: number | null }
const activeTurn = ref<ActiveTurn | null>(null)
const girlfriendTarget = ref<ActiveTurn | null>(null)
const personaTarget = ref<ActiveTurn | null>(null)
const stagedTurnIntent = ref<YanceScopedTurnIntent | null>(null)
const girlfriendFeedback = ref<{ state: 'pending' | 'ready' | 'error'; detail: string; undoAvailable?: boolean } | null>(null)
const personaFeedback = ref('')
let intentNonce = 0

const sourceTurn = (chat: ChatDetail): ActiveTurn => {
  const inbound = chat.messages.filter(m => m.message_type === 'user' && typeof m.id === 'number')
  return {
    sessionId: chat.session_id, customerId: chat.customer.id, agentId: chat.agent.id,
    sourceMessageId: inbound.length ? Number(inbound[inbound.length - 1].id) : null,
  }
}
const sameTurn = (left: ActiveTurn | null, right: ActiveTurn | null) =>
  !!left && !!right && left.sessionId === right.sessionId
  && left.customerId === right.customerId && left.agentId === right.agentId
  && left.sourceMessageId !== null && left.sourceMessageId === right.sourceMessageId
const receiveActiveTurn = (identity: ActiveTurn) => {
  if (activeTurn.value && !sameTurn(activeTurn.value, identity)) {
    stagedTurnIntent.value = null
    girlfriendFeedback.value = null
    personaFeedback.value = ''
    girlfriendTarget.value = null
    personaTarget.value = null
    girlfriendBrainOpen.value = false
    personaStudioChat.value = null
  }
  activeTurn.value = identity
}
const receiveIntentReceipt = (receipt: { nonce: number; accepted: boolean; undone?: boolean; detail: string }) => {
  if (receipt.nonce !== stagedTurnIntent.value?.nonce) return
  girlfriendFeedback.value = {
    state: receipt.accepted ? 'ready' : 'error', detail: receipt.detail,
    undoAvailable: receipt.accepted && !receipt.undone,
  }
  personaFeedback.value = receipt.detail
  if (!receipt.accepted || receipt.undone) stagedTurnIntent.value = null
}
const requestTurnIntent = (identity: ActiveTurn | null, persona: string, goal?: string, doNotLearn?: boolean) => {
  if (!identity || !sameTurn(activeTurn.value, identity)) return '联系人或回合已变化，未应用。'
  if (!persona.trim() || persona.length > 1600 || /[\u0000-\u001f\u007f]/.test(persona)) return '内容为空、超限或包含无效控制字符。'
  if (goal && goal.length > 600) return '当前目标超过原生 600 字限制。'
  if (hasExternalReplyProjection.value) return '当前使用外部只读建议投影，原生 Reply Brain 不可接收本轮意图。'
  stagedTurnIntent.value = {
    nonce: ++intentNonce, action: 'apply', sessionId: identity.sessionId,
    customerId: identity.customerId, agentId: identity.agentId,
    sourceMessageId: identity.sourceMessageId!, currentTurnPersona: persona,
    currentGoal: goal, doNotLearn,
  }
  replyBrainOpen.value = true
  girlfriendFeedback.value = { state: 'pending', detail: '正在交给当前 Reply Brain…' }
  return ''
}

const boundedCandidates = computed(() => props.replyCandidates.slice(0, 5))
const visibleCandidates = computed(() => boundedCandidates.value.slice(0, expanded.value ? 5 : 3))
const canExpand = computed(() => !expanded.value && boundedCandidates.value.length > 3)

const effectiveReplyState = computed<YanceReplyBrainStateProjection>(() => {
  if (props.replyState) return props.replyState
  if (boundedCandidates.value.length > 0) {
    return { state: 'ready' as const }
  }
  return {
    state: 'empty' as const,
    title: '暂无合适建议',
    detail: '你仍然可以直接在输入框里手动回复。',
  }
})

const replyStateLabel = computed(() => {
  const projected = effectiveReplyState.value
  if (projected.title) return projected.title
  return {
    idle: '建议尚未开始',
    loading: '正在准备建议',
    ready: '建议已就绪',
    empty: '暂无合适建议',
    'no-reply': '当前不建议发送',
    defer: '建议稍后再回复',
    'platform-switch': '建议切换发送平台',
    stale: '建议已过期',
    recomputing: '正在根据最新消息重新整理',
    error: '建议暂不可用',
  }[projected.state]
})

const projectionFor = (message: Message) => {
  if (message.id === undefined || message.id === null) return undefined
  return props.translationsByMessageId[String(message.id)]
}

const canonicalMessageId = (message: Message): string | number => message.id ?? ''

const railProjectionFor = (conversation: Conversation) => {
  const messageId = conversation.last_message_id
  if (messageId === undefined || messageId === null) return undefined
  return props.translationsByMessageId[String(messageId)]
}

const canonicalRailMessageId = (conversation: Conversation): string | number =>
  conversation.last_message_id ?? ''

const routeCapability = (key: keyof typeof FROZEN_UI_CAPABILITY_ROUTES) => {
  emit('capability-route', FROZEN_UI_CAPABILITY_ROUTES[key])
}

const toggleReplyBrain = () => {
  replyBrainOpen.value = !replyBrainOpen.value
  if (!replyBrainOpen.value) expanded.value = false
  if (replyBrainOpen.value) routeCapability('reply-brain')
}

const openGirlfriendBrain = (chat: ChatDetail | null) => {
  girlfriendTarget.value = chat ? sourceTurn(chat) : activeTurn.value
  girlfriendFeedback.value = null
  girlfriendBrainOpen.value = true
  routeCapability('girlfriend-brain')
}

const closeGirlfriendBrain = () => {
  girlfriendBrainOpen.value = false
  girlfriendTarget.value = null
}

const onGlobalGFShortcut = (event: KeyboardEvent) => {
  if (event.ctrlKey && event.shiftKey && !event.altKey && !event.metaKey
      && event.key.toLowerCase() === 'g') {
    // Never open a second modal over an already active global task or
    // platform connection dialog. The topmost dialog owns its shortcut.
    if (document.querySelector('[data-yance-global-girlfriend], .meta-modal-content, .tg-modal-content, .cc-modal-content')) return
    event.preventDefault()
    if (girlfriendBrainOpen.value) closeGirlfriendBrain()
    else openGirlfriendBrain(null)
  }
}
onMounted(() => {
  document.addEventListener('keydown', onGlobalGFShortcut)
  void refreshNativeConversationEmpty()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onGlobalGFShortcut))

const openPersonaStudio = (chat: ChatDetail) => {
  personaTarget.value = sourceTurn(chat)
  personaStudioChat.value = chat
  routeCapability('persona')
}

const closePersonaStudio = () => {
  personaTarget.value = null
  personaStudioChat.value = null
}

const forwardPersonaTurnOverride = (payload: {
  agentId: string
  customerId: string
  sessionId: string
  seedId: string
  instructions: string[]
}) => {
  const identity: ActiveTurn = {
    sessionId: payload.sessionId, customerId: payload.customerId,
    agentId: payload.agentId, sourceMessageId: personaTarget.value?.sourceMessageId ?? null,
  }
  const failure = requestTurnIntent(identity, payload.instructions.join('\n'))
  personaFeedback.value = failure || '已提交至当前 Reply Brain；等待本轮应用回执。'
}

const stageGirlfriendIntent = (draft: YanceGirlfriendIntentDraft) => {
  if (draft.scope !== 'turn' || !draft.turnOnly) {
    girlfriendFeedback.value = {
      state: 'error',
      detail: '仅支持本轮、不学习。跨联系人、语言、关系或全局规则须使用原生 Persona 审批与持久化流程。',
    }
    return
  }
  const persona = [draft.instruction, draft.personaNote].filter(Boolean).join('\n')
  const failure = requestTurnIntent(girlfriendTarget.value, persona, draft.goalNote, true)
  if (failure) girlfriendFeedback.value = { state: 'error', detail: failure }
}
const undoGirlfriendIntent = () => {
  // Preserve the existing independent orchestration's undo owner when present.
  if (props.girlfriendOrchestration?.state === 'receipt' && props.girlfriendOrchestration.undoAvailable) {
    emit('girlfriend-undo-request')
    return
  }
  const intent = stagedTurnIntent.value
  if (!intent || intent.action !== 'apply' || !sameTurn(activeTurn.value, intent)) {
    girlfriendFeedback.value = { state: 'error', detail: '该回合已失效，无法撤销。' }
    return
  }
  stagedTurnIntent.value = { ...intent, nonce: ++intentNonce, action: 'undo' }
  girlfriendFeedback.value = { state: 'pending', detail: '正在撤销本轮覆盖…' }
}

type AdoptMediaIntent = (intent: {
  type: 'voice' | 'photo' | 'image' | 'video' | 'file'
  label: string
  prompt: string
  runtimeState: 'ready' | 'runtime-pending'
}) => void

const mediaTypes = new Set<YanceReplyBrainCandidate['type']>(['voice', 'photo', 'image', 'video', 'file'])

const adoptCandidate = (
  adoptDraft: (draft: string) => void,
  adoptAttachment: (attachmentId: number) => void,
  adoptMediaIntent: AdoptMediaIntent,
  candidate: YanceReplyBrainCandidate,
) => {
  if (candidate.type === 'text') {
    adoptDraft(candidate.draft)
    return
  }
  if (!mediaTypes.has(candidate.type)) return

  if (Number.isInteger(candidate.attachmentId) && Number(candidate.attachmentId) > 0) {
    adoptAttachment(Number(candidate.attachmentId))
    return
  }

  const runtimeState = candidate.runtimeState ?? 'runtime-pending'
  if (runtimeState === 'unavailable') return
  adoptMediaIntent({
    type: candidate.type as 'voice' | 'photo' | 'image' | 'video' | 'file',
    label: candidate.label,
    prompt: candidate.draft,
    runtimeState,
  })
}
</script>

<template>
  <div
    class="yance-master-frame"
    data-yance-master-frame
    data-frame-width="920"
    data-frame-height="620"
    data-native-window-control="hold"
  >
    <YanceEmptyConversation v-if="nativeEmptyConversations" :refreshing="nativeEmptyLoading"
      @refresh="refreshNativeConversationEmpty" />
    <ConversationsView
      v-else
      :layout-hide-header="false"
      frozen-yance
      data-yance-native-host
    >
      <template #conversation-header-actions="{ chat }">
        <div class="yance-top-actions" data-yance-top-actions aria-label="言策对话控制">
          <a class="yance-home-entry" data-yance-home-entry href="/yance/home">返回首页</a>
        <a class="yance-home-entry" data-yance-relationship-entry href="/yance/relationship">关系世界</a>
          <button
            type="button"
            v-if="chat"
            data-yance-persona-control
            data-owner-state="ready"
            :aria-pressed="personaStudioChat?.session_id === chat.session_id"
            title="打开人格种子、风格素材与范围选择"
            @click="openPersonaStudio(chat)"
          >
            人格
          </button>
          <button
            type="button"
            data-yance-reply-mode-control
            data-owner-state="ready"
            :aria-pressed="replyBrainOpen"
            title="HUMAN / AI_ASSIST / AI_AUTO"
            @click="toggleReplyBrain"
          >
            回复模式
          </button>
          <button
            type="button"
            data-yance-model-reasoning-control
            data-owner-state="unavailable"
            disabled
            title="当前暂不可切换模型或推理强度"
          >
            模型/推理
          </button>
          <button
            type="button"
            data-yance-girlfriend-toggle
            :aria-pressed="girlfriendBrainOpen"
            aria-keyshortcuts="Control+Shift+G"
            @click="openGirlfriendBrain(chat)"
          >
            闺蜜大脑
          </button>
        </div>
      </template>

      <template #conversation-secondary="{ conversation }">
        <div
          v-if="railProjectionFor(conversation)"
          class="yance-rail-translation"
          data-yance-rail-translation-secondary
        >
          <YanceBilingualMessageProjection
            :canonical-message-id="canonicalRailMessageId(conversation)"
            :translation="railProjectionFor(conversation)!"
            :source-text="conversation.last_message"
            silent-fail-closed
          />
        </div>
      </template>

      <template #message-secondary="{ message }">
        <YanceBilingualMessageProjection
          v-if="projectionFor(message)"
          :canonical-message-id="canonicalMessageId(message)"
          :translation="projectionFor(message)!"
          :source-text="message.message"
        />
      </template>

      <template #conversation-extension="{ chat, adoptDraft, adoptAttachment, adoptMediaIntent }">
        <YanceReplyBrainRuntimeComposition
          v-if="chat && !hasExternalReplyProjection"
          :chat="chat"
          :open="replyBrainOpen"
          :adopt-draft="adoptDraft"
          :adopt-attachment="adoptAttachment"
          :adopt-media-intent="adoptMediaIntent"
          :turn-intent="stagedTurnIntent"
          @active-turn="receiveActiveTurn"
          @turn-intent-receipt="receiveIntentReceipt"
          @toggle="toggleReplyBrain"
        />
        <section
          v-else
          class="yance-reply-brain-seam"
          data-yance-reply-brain-seam
          :data-yance-reply-state="replyBrainOpen ? effectiveReplyState.state : 'collapsed'"
        >
          <button
            type="button"
            class="yance-reply-brain-toggle"
            data-yance-reply-toggle
            :aria-expanded="replyBrainOpen"
            @click="toggleReplyBrain"
          >
            言策建议
          </button>

          <div v-if="replyBrainOpen" class="yance-reply-brain-content" data-yance-reply-panel>
            <section
              v-if="effectiveReplyState.state !== 'ready'"
              class="yance-reply-state-card"
              data-yance-reply-secondary-state
              :data-state="effectiveReplyState.state"
            >
              <strong>{{ replyStateLabel }}</strong>
              <p v-if="effectiveReplyState.detail">{{ effectiveReplyState.detail }}</p>
              <p v-if="effectiveReplyState.platform" class="yance-reply-state-card__platform">
                平台：{{ effectiveReplyState.platform }}
              </p>
              <details v-if="effectiveReplyState.why || effectiveReplyState.evidence?.length">
                <summary>为什么这样建议？</summary>
                <p v-if="effectiveReplyState.why">{{ effectiveReplyState.why }}</p>
                <ul v-if="effectiveReplyState.evidence?.length" data-yance-reply-state-evidence>
                  <li v-for="item in effectiveReplyState.evidence" :key="item">{{ item }}</li>
                </ul>
              </details>
              <button
                v-if="effectiveReplyState.canRecompute"
                type="button"
                data-yance-recompute
                @click="emit('reply-recompute')"
              >
                重新生成最新建议
              </button>
            </section>

            <YanceReplyBrainCandidateCard
              v-for="candidate in visibleCandidates"
              :key="candidate.id"
              :candidate="candidate"
              @adopt="adoptCandidate(adoptDraft, adoptAttachment, adoptMediaIntent, $event)"
            />

            <button
              v-if="canExpand"
              type="button"
              class="yance-more-candidates"
              data-yance-more-candidates
              @click="expanded = true"
            >
              更多建议
            </button>
          </div>
        </section>
      </template>
    </ConversationsView>

    <YanceGirlfriendBrainNativeComposition
      v-if="girlfriendBrainOpen"
      :voice-readiness="FROZEN_VOICE_MEDIA_UI_READINESS.voice"
      :image-readiness="FROZEN_VOICE_MEDIA_UI_READINESS.image"
      :video-readiness="FROZEN_VOICE_MEDIA_UI_READINESS.video"
      :orchestration="props.girlfriendOrchestration"
      :intent-feedback="girlfriendFeedback"
      @close="closeGirlfriendBrain"
      @intent-draft="stageGirlfriendIntent"
      @undo-request="undoGirlfriendIntent"
      @permission-decision="emit('girlfriend-permission-decision', $event)"
    />

    <YancePersonaStudio
      v-if="personaStudioChat"
      :chat="personaStudioChat"
      :open="true"
      :turn-intent-feedback="personaFeedback"
      @close="closePersonaStudio"
      @turn-override="forwardPersonaTurnOverride"
    />
  </div>
</template>

<style scoped>
.yance-master-frame {
  --bg:#151622;--bg2:#211e2a;--bg3:#2b2230;--text:#efe8ee;--text2:#d3c8d3;
  --text3:#ad9fae;--muted:#a69cae;--o05:#ffffff0a;--o08:#ffffff14;--o10:#ffffff19;
  --o14:#ffffff26;--accent:#bd93d2;--accent-bg-12:#79518f33;--accent-border:#9671a7;
  --warning:#efb58e;--space-xs:6px;--space-sm:10px;
  color:var(--text);font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif;
  background:radial-gradient(ellipse at 8% 0%,#432a3238,transparent 54%),#0e101b;
  border-color:#654a5d;border-radius:13px;box-shadow:0 18px 56px #0008;
}
.yance-master-frame :deep(.dashboard-layout),
.yance-master-frame :deep(.main-content),
.yance-master-frame :deep(.conversations-page) {
  background:transparent;color:var(--text);
}
.yance-master-frame :deep(.conversations-page) {min-height:0;height:100%;overflow:hidden}
.yance-master-frame :deep(.conversation-viewport){height:100%;min-height:0}
.yance-master-frame :deep(.conversations-page .page-header){
  border-bottom:1px solid #655065;background:#1d1c29}
.yance-master-frame :deep(.conversations-page .page-header h1){color:#e7c594;font-size:15px}
.yance-master-frame :deep(.conversation-list),
.yance-master-frame :deep(.conversation-sidebar),
.yance-master-frame :deep(.conversations-list){
  background:#191925;border-right:1px solid #58465d;color:#e4d7e8}
.yance-master-frame :deep(.message-bubble){border-color:#57435c}
.yance-master-frame :deep(.message-input),
.yance-master-frame :deep(textarea){background:#181723;color:#efe8ef}
.yance-master-frame :deep(.yance-reply-runtime){background:#211b2c;border-color:#805b8a}
.yance-master-frame :deep(.yance-reply-runtime__toggle){color:#eac9f0}
.yance-master-frame :deep(.yance-reply-candidate){background:#302334;border-color:#795a83}
.yance-top-actions{color:#e3d3e5}
.yance-top-actions button,.yance-home-entry{border-color:#69536d;color:#e9daec;background:#2a2331}
.yance-top-actions [data-yance-girlfriend-toggle]{background:#613e74;border-color:#a77ab3;color:#f6def7}
.yance-top-actions :is(button,a):focus-visible,
.yance-master-frame :deep(button:focus-visible){outline:2px solid #f5c783;outline-offset:2px}
.yance-reply-brain-seam{border-color:#79518f;background:#211b2c}
.yance-reply-state-card{border-color:#785778;background:#302131}
.yance-rail-translation {
  margin-left: 44px;
  min-width: 0;
}

.yance-rail-translation :deep(.yance-bilingual-projection) {
  margin-top: 0;
  font-size: 10.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.yance-master-frame {
  position: relative;
  width: min(920px, 100vw);
  height: min(620px, 100dvh);
  max-width: 100%;
  max-height: 100dvh;
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid var(--o10);
  border-radius: 14px;
  background: var(--bg);
  box-shadow: var(--shadow-lg);
}

.yance-master-frame :deep(.dashboard-layout) {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.yance-master-frame :deep(.dashboard-layout .main-content) {
  min-width: 0;
  min-height: 0;
}

.yance-top-actions {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  flex-wrap: wrap;
}

.yance-top-actions button,
.yance-home-entry,
.yance-reply-brain-toggle,
.yance-more-candidates,
.yance-reply-state-card button {
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o05);
  color: var(--text);
  padding: 6px 9px;
  font-size: 12px;
  cursor: pointer;
  text-decoration: none;
}

.yance-top-actions button:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.yance-reply-brain-seam {
  flex: 0 0 auto;
  padding: 8px 20px;
  border-top: 1px solid var(--o08);
  background: var(--bg2);
}

.yance-reply-brain-content {
  display: grid;
  gap: var(--space-xs);
  margin-top: var(--space-xs);
  max-height: 214px;
  overflow-y: auto;
}

.yance-reply-state-card {
  display: grid;
  gap: 6px;
  padding: 9px 10px;
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o04);
  font-size: 12px;
}

.yance-reply-state-card strong {
  color: var(--text);
}

.yance-reply-state-card p,
.yance-reply-state-card details {
  margin: 0;
  color: var(--muted);
  line-height: 1.4;
}

.yance-reply-state-card summary {
  color: var(--text3);
  cursor: pointer;
}

.yance-reply-state-card ul {
  margin: 5px 0 0;
  padding-left: 16px;
}

.yance-reply-state-card__platform {
  font-family: var(--font-mono);
}

@media (max-width: 920px), (max-height: 620px) {
  .yance-master-frame {
    width: 100vw;
    height: 100dvh;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }
}

@media (max-width: 768px) {
  .yance-top-actions {
    flex-wrap: nowrap;
    max-width: min(52vw, 360px);
    overflow-x: auto;
    scrollbar-width: none;
  }

  .yance-top-actions::-webkit-scrollbar {
    display: none;
  }

  .yance-top-actions button {
    flex: 0 0 auto;
    padding: 6px 8px;
  }
}
</style>
