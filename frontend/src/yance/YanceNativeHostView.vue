<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatDetail, Conversation, Message } from '@/types/chat'
import ConversationsView from '@/views/ConversationsView.vue'
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
  (event: 'girlfriend-intent-draft', draft: YanceGirlfriendIntentDraft): void
  (event: 'reply-recompute'): void
  (event: 'girlfriend-undo-request'): void
  (event: 'girlfriend-permission-decision', decision: 'allow-once' | 'cancel'): void
  (event: 'persona-turn-override', payload: {
    agentId: string
    customerId: string
    sessionId: string
    seedId: string
    instructions: string[]
  }): void
}>()

const replyBrainOpen = ref(false)
const expanded = ref(false)
const hasExternalReplyProjection = computed(
  () => props.replyState !== undefined || props.replyCandidates.length > 0,
)
const girlfriendBrainOpen = ref(false)
const personaStudioChat = ref<ChatDetail | null>(null)

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

const openGirlfriendBrain = () => {
  girlfriendBrainOpen.value = true
  routeCapability('girlfriend-brain')
}

const closeGirlfriendBrain = () => {
  girlfriendBrainOpen.value = false
}

const openPersonaStudio = (chat: ChatDetail) => {
  personaStudioChat.value = chat
  routeCapability('persona')
}

const closePersonaStudio = () => {
  personaStudioChat.value = null
}

const forwardPersonaTurnOverride = (payload: {
  agentId: string
  customerId: string
  sessionId: string
  seedId: string
  instructions: string[]
}) => {
  emit('persona-turn-override', payload)
}

const stageGirlfriendIntent = (draft: YanceGirlfriendIntentDraft) => {
  emit('girlfriend-intent-draft', draft)
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
    <ConversationsView
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
            @click="openGirlfriendBrain"
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
      @close="closeGirlfriendBrain"
      @intent-draft="stageGirlfriendIntent"
      @undo-request="emit('girlfriend-undo-request')"
      @permission-decision="emit('girlfriend-permission-decision', $event)"
    />

    <YancePersonaStudio
      v-if="personaStudioChat"
      :chat="personaStudioChat"
      :open="true"
      @close="closePersonaStudio"
      @turn-override="forwardPersonaTurnOverride"
    />
  </div>
</template>

<style scoped>
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
