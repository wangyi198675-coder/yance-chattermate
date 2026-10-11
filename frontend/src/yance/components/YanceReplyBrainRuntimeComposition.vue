<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { ChatDetail } from '@/types/chat'
import { sessionToAgentService } from '@/services/sessionToAgent'
import { yanceReplyService, type ReplyRuntimeProjection, type ReplyCandidateEnvelope } from '@/services/yanceReply'
import YanceReplyBrainCandidateCard from './YanceReplyBrainCandidateCard.vue'
import type { YanceReplyBrainCandidate, YanceReplyBrainStateProjection, YanceScopedTurnIntent } from '../semanticTypes'

type AdoptMediaIntent = (intent: {
  type: 'voice' | 'photo' | 'image' | 'video' | 'file'
  label: string
  prompt: string
  runtimeState: 'ready' | 'runtime-pending'
}) => void

const props = defineProps<{
  chat: ChatDetail
  open: boolean
  adoptDraft: (draft: string) => void
  adoptAttachment: (attachmentId: number) => void
  adoptMediaIntent: AdoptMediaIntent
  initialCurrentGoal?: string
  initialCurrentTurnPersona?: string
  initialLongTermGoal?: string
  initialDoNotLearn?: boolean
  recomputeToken?: number
  abortToken?: number
  turnIntent?: YanceScopedTurnIntent | null
}>()

const emit = defineEmits<{
  (event: 'toggle'): void
  (event: 'active-turn', identity: { sessionId: string; customerId: string; agentId: string; sourceMessageId: number | null }): void
  (event: 'turn-intent-receipt', receipt: { nonce: number; accepted: boolean; undone?: boolean; detail: string }): void
}>()

const runtime = ref<ReplyRuntimeProjection | null>(null)
const candidates = ref<YanceReplyBrainCandidate[]>([])
const replyState = ref<YanceReplyBrainStateProjection>({
  state: 'idle',
  detail: '打开后按当前会话生成建议。',
})
const sourceMessageId = ref<number | null>(null)
const contextRevision = ref('')
const expanded = ref(false)
const assist = ref(false)
const currentGoal = ref(props.initialCurrentGoal ?? '')
const currentTurnPersona = ref(props.initialCurrentTurnPersona ?? '')
const longTermGoal = ref(props.initialLongTermGoal ?? '')
const storedLongTermGoal = ref('')
const longTermGoalDirty = ref(false)
const allowSensitiveContext = ref(false)
let generationEpoch = 0
const currentTurnCorrection = ref('')
const strategy = ref('balanced')
const deepReply = ref(false)
const doNotLearn = ref(Boolean(props.initialDoNotLearn))
const busy = ref(false)
const adoptingCandidateId = ref<string | null>(null)
const error = ref('')
const durableRule = ref('')
const durableScope = ref<'global' | 'contact'>('contact')
const historyOpen = ref(false)
const history = ref<Array<{ transaction_id: number; instructions: string }>>([])
let turnIntentSnapshot: { sessionId: string; sourceMessageId: number; persona: string; goal: string; doNotLearn: boolean } | null = null
const activeTurn = () => ({
  sessionId: props.chat.session_id,
  customerId: props.chat.customer.id,
  agentId: props.chat.agent.id,
  sourceMessageId: latestInboundId(),
})
const notifyActiveTurn = () => emit('active-turn', activeTurn())
onMounted(notifyActiveTurn)

const boundedCandidates = computed(() => candidates.value.slice(0, 5))
const visibleCandidates = computed(() => boundedCandidates.value.slice(0, expanded.value ? 5 : 3))
const canExpand = computed(() =>
  !expanded.value && replyState.value.state === 'ready' && boundedCandidates.value.length === 3,
)

const mode = computed<'HUMAN' | 'AI_ASSIST' | 'AI_AUTO'>(() => {
  if (assist.value) return 'AI_ASSIST'
  if (props.chat.user_id) return 'HUMAN'
  if (props.chat.agent.ai_replies_enabled && runtime.value?.ai_auto_available) return 'AI_AUTO'
  return 'HUMAN'
})

const stateLabel = computed(() => {
  if (replyState.value.title) return replyState.value.title
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
  }[replyState.value.state]
})

const latestInboundId = () => {
  const rows = props.chat.messages
    .filter(message => message.message_type === 'user' && typeof message.id === 'number')
  return rows.length ? Number(rows[rows.length - 1].id) : null
}

const markStale = () => {
  candidates.value = []
  replyState.value = {
    state: 'stale',
    why: '会话在建议生成后已经变化。',
    detail: '旧建议不会写入输入框，请按最新上下文重新生成。',
    canRecompute: true,
  }
}

const applyEnvelope = (envelope: ReplyCandidateEnvelope) => {
  // An empty ready envelope is a legitimate zero-candidate outcome, not an invisible panel.
  candidates.value = (envelope.state === 'ready' ? envelope.candidates : []).slice(0, 5)
  sourceMessageId.value = envelope.source_message_id ?? null
  contextRevision.value = envelope.context_revision
  const mappedState = envelope.state === 'no_reply'
    ? 'no-reply'
    : envelope.state
  replyState.value = {
    state: mappedState === 'ready' && candidates.value.length === 0 ? 'empty' : mappedState,
    why: envelope.why ?? undefined,
    detail: [
      envelope.balance_strategy ? `策略：${envelope.balance_strategy}` : '',
      envelope.deep_reply ? `深度：${envelope.deep_reply}` : '',
    ].filter(Boolean).join(' · ') || undefined,
    canRecompute: envelope.can_recompute,
  }
}

let hydratingRuntime = false
let resettingSession = false
let lastHydratedTurnId: number | null = null
let pendingTurnWrites = 0
let turnWriteQueue: Promise<void> = Promise.resolve()
const refreshRuntime = async () => {
  const sessionId = props.chat.session_id
  hydratingRuntime = true
  try {
    const projection = await yanceReplyService.getRuntime(sessionId)
    if (sessionId !== props.chat.session_id) return
    runtime.value = projection
    contextRevision.value = projection.context_revision
    const turn = runtime.value.current_turn_controls
    if (turn && (turn.source_message_id !== lastHydratedTurnId || pendingTurnWrites === 0)) {
      lastHydratedTurnId = turn.source_message_id
      // A pending operator edit must not be replaced by an earlier DB snapshot.
      // The queued write still uses the canonical row/version for its CAS.
      if (pendingTurnWrites === 0) {
        currentGoal.value = turn.current_goal ?? ''
        allowSensitiveContext.value = turn.allow_sensitive_context
      }
    }
    const persisted = runtime.value.long_term_goal ?? ''
    if (!longTermGoalDirty.value || longTermGoal.value === storedLongTermGoal.value) {
      longTermGoal.value = persisted
    }
    storedLongTermGoal.value = persisted
  } finally {
    // Vue's default watcher batch flushes on the next microtask.
    await Promise.resolve()
    hydratingRuntime = false
  }
}

const queueTurnControlsWrite = () => {
  const sessionId = props.chat.session_id
  pendingTurnWrites++
  turnWriteQueue = turnWriteQueue.catch(() => {}).then(async () => {
    if (sessionId !== props.chat.session_id) return
    if (!runtime.value) await refreshRuntime()
    const turn = runtime.value?.current_turn_controls
    if (!turn) return
    if (latestInboundId() !== turn.source_message_id) {
      markStale()
      throw new Error('current_turn_changed')
    }
    const stored = await yanceReplyService.setTurnControls(sessionId, {
      source_message_id: turn.source_message_id,
      expected_version: turn.version,
      current_goal: currentGoal.value.trim() || null,
      allow_sensitive_context: allowSensitiveContext.value,
    })
    if (runtime.value && sessionId === props.chat.session_id) {
      runtime.value.current_turn_controls = stored
    }
  }).finally(() => {
    pendingTurnWrites--
  })
  void turnWriteQueue.catch(() => {
    error.value = 'current_turn_revision_conflict'
    markStale()
  })
  return turnWriteQueue
}

const generate = async (limit: 3 | 5, recompute = false) => {
  const sessionId = props.chat.session_id
  const epoch = ++generationEpoch
  busy.value = true
  error.value = ''
  replyState.value = {
    state: recompute ? 'recomputing' : 'loading',
    detail: recompute ? '正在丢弃旧上下文并按最新消息重新计算。' : undefined,
  }
  try {
    await turnWriteQueue
    await refreshRuntime()
    if (epoch !== generationEpoch || sessionId !== props.chat.session_id) return
    const envelope = await yanceReplyService.generateCandidates(sessionId, {
      limit,
      expected_revision: runtime.value?.context_revision,
      current_goal: currentGoal.value.trim() || undefined,
      current_turn_persona: currentTurnPersona.value.trim() || undefined,
      allow_sensitive_context: allowSensitiveContext.value,
      current_turn_correction: currentTurnCorrection.value.trim() || undefined,
      strategy: strategy.value,
      deep_reply: deepReply.value,
    })
    if (epoch !== generationEpoch || sessionId !== props.chat.session_id) return
    expanded.value = limit === 5
    applyEnvelope(envelope)
  } catch (cause: any) {
    if (epoch !== generationEpoch || sessionId !== props.chat.session_id) return
    const detail = cause?.response?.data?.detail
    if (cause?.response?.status === 409 || detail?.code === 'reply_context_stale') {
      markStale()
    } else {
      candidates.value = []
      error.value = typeof detail === 'string' ? detail : 'reply_generation_unavailable'
      replyState.value = {
        state: 'error',
        detail: '现有 Agent runtime 当前无法生成建议；手动回复仍可用。',
        canRecompute: true,
      }
    }
  } finally {
    if (epoch === generationEpoch && sessionId === props.chat.session_id) busy.value = false
  }
}

const abortGeneration = () => {
  generationEpoch++
  busy.value = false
  candidates.value = []
  expanded.value = false
  sourceMessageId.value = null
  replyState.value = { state: 'stale', detail: '本次结果已丢弃；没有发送或学习。', canRecompute: true }
}

const saveLongTermGoal = async () => {
  const clean = longTermGoal.value.trim()
  if (!window.confirm(clean ? '确认保存长期目标到现有关系记忆？' : '确认撤销长期目标？')) return
  error.value = ''
  try {
    const result = await yanceReplyService.setLongTermGoal(props.chat.session_id, clean || null)
    storedLongTermGoal.value = result.long_term ?? ''
    longTermGoal.value = storedLongTermGoal.value
    longTermGoalDirty.value = false
    await generate(3, true)
  } catch (cause: any) {
    error.value = typeof cause?.response?.data?.detail === 'string'
      ? cause.response.data.detail : 'long_term_goal_unavailable'
  }
}

const ensureFresh = () => {
  if (sourceMessageId.value === null) return true
  if (latestInboundId() !== sourceMessageId.value) {
    markStale()
    return false
  }
  return true
}

const recordEvidence = async (
  candidate: YanceReplyBrainCandidate,
  decision: 'adopt' | 'reject',
) => {
  const sessionId = props.chat.session_id
  const epoch = generationEpoch
  const sourceId = sourceMessageId.value
  if (replyState.value.state !== 'ready' || !sourceId || !ensureFresh()
      || !candidates.value.some(item => item.id === candidate.id)) return false
  try {
    // This is the generation snapshot, NEVER the result of a fresh runtime poll.
    if (!candidate.contextRevision || candidate.contextRevision !== contextRevision.value) {
      markStale()
      return false
    }
    const result = await yanceReplyService.recordEvidence(sessionId, {
      source_message_id: sourceId,
      context_revision: candidate.contextRevision,
      candidate_id: candidate.id,
      decision,
      draft: candidate.draft,
      do_not_learn: doNotLearn.value,
    })
    // The request may finish after contact switch, permission revocation or close.
    if (sessionId !== props.chat.session_id || epoch !== generationEpoch || !props.open) return false
    if (!result?.recorded || result.stale) {
      markStale()
      return false
    }
    return true
  } catch (cause: any) {
    if (sessionId !== props.chat.session_id || epoch !== generationEpoch || !props.open) return false
    if (cause?.response?.status === 409) markStale()
    else error.value = 'learning_evidence_unavailable'
    return false
  }
}

const adopt = async (candidate: YanceReplyBrainCandidate) => {
  if (adoptingCandidateId.value || candidate.humanLikeness !== 'pass'
      || (candidate.runtimeState && candidate.runtimeState !== 'ready'
          && candidate.type === 'text')) return
  const epoch = generationEpoch
  adoptingCandidateId.value = candidate.id
  try {
    if (!await recordEvidence(candidate, 'adopt')) return
    if (candidate.type === 'text') {
      props.adoptDraft(candidate.draft)
      return
    }
    if (!['voice', 'photo', 'image', 'video', 'file'].includes(candidate.type)) return
    if (Number.isInteger(candidate.attachmentId) && Number(candidate.attachmentId) > 0) {
      props.adoptAttachment(Number(candidate.attachmentId))
      return
    }
    const runtimeState = candidate.runtimeState ?? 'runtime-pending'
    if (runtimeState === 'unavailable') return
    props.adoptMediaIntent({
      type: candidate.type as 'voice' | 'photo' | 'image' | 'video' | 'file',
      label: candidate.label,
      prompt: candidate.draft,
      runtimeState,
    })
  } finally {
    if (epoch === generationEpoch) adoptingCandidateId.value = null
  }
}

const reject = async (candidate: YanceReplyBrainCandidate) => {
  if (!await recordEvidence(candidate, 'reject')) return
  candidates.value = candidates.value.filter(item => item.id !== candidate.id)
  if (!candidates.value.length) {
    replyState.value = {
      state: 'empty',
      detail: '已记录不采用证据；你可以重新生成或直接手动回复。',
      canRecompute: true,
    }
  }
}

const replaceChat = (updated: ChatDetail) => {
  Object.assign(props.chat, updated)
}

const selectMode = async (next: 'HUMAN' | 'AI_ASSIST' | 'AI_AUTO') => {
  error.value = ''
  try {
    if (next === 'HUMAN') {
      assist.value = false
      if (!props.chat.user_id) replaceChat(await sessionToAgentService.takeoverChat(props.chat.session_id))
      candidates.value = []
      expanded.value = false
      sourceMessageId.value = null
      replyState.value = { state: 'idle', detail: 'HUMAN 模式：只由你手动回复。' }
      return
    }
    if (next === 'AI_ASSIST') {
      if (!props.chat.user_id) replaceChat(await sessionToAgentService.takeoverChat(props.chat.session_id))
      assist.value = true
      await generate(3, true)
      return
    }
    await turnWriteQueue
    await refreshRuntime()
    if (runtime.value?.ai_auto_available === false) {
      error.value = runtime.value.ai_auto_unavailable_reason || 'ai_auto_unavailable'
      return
    }
    if (!window.confirm('AI_AUTO 会把当前会话释放给现有 Agent 自动回复。继续？')) return
    assist.value = false
    replaceChat(await sessionToAgentService.releaseToAI(props.chat.session_id))
    candidates.value = []
    expanded.value = false
    sourceMessageId.value = null
    replyState.value = { state: 'idle', detail: 'AI_AUTO 模式：新消息由现有 Agent 自动回复。' }
    await refreshRuntime()
  } catch (cause: any) {
    const detail = cause?.response?.data?.detail
    error.value = detail === 'agent_ai_replies_disabled'
      ? '此 Agent 尚未启用 AI 自动回复；请先在现有 Agent 设置中授权。'
      : (typeof detail === 'string' ? detail : 'reply_mode_change_unavailable')
  }
}

const saveRule = async () => {
  if (!durableRule.value.trim()) return
  error.value = ''
  try {
    await yanceReplyService.promoteRule(props.chat.agent.id, {
      scope: durableScope.value,
      rule: durableRule.value.trim(),
      customer_id: durableScope.value === 'contact' ? props.chat.customer.id : undefined,
    })
    durableRule.value = ''
    await loadHistory()
  } catch (cause: any) {
    error.value = cause?.response?.status === 403
      ? '没有修改 Agent 长期规则的权限。'
      : 'durable_rule_unavailable'
  }
}

const loadHistory = async () => {
  try {
    const response = await yanceReplyService.learningHistory(props.chat.agent.id)
    history.value = response.versions
    historyOpen.value = true
  } catch {
    error.value = 'learning_history_unavailable'
  }
}

const rollback = async (transactionId: number) => {
  if (!window.confirm('回滚会恢复该版本的人格/长期规则。继续？')) return
  try {
    await yanceReplyService.rollbackLearning(props.chat.agent.id, transactionId)
    await loadHistory()
  } catch {
    error.value = 'learning_rollback_unavailable'
  }
}

watch(
  () => props.turnIntent,
  intent => {
    if (!intent) return
    const identity = activeTurn()
    const valid = intent.sessionId === identity.sessionId
      && intent.customerId === identity.customerId && intent.agentId === identity.agentId
      && intent.sourceMessageId === identity.sourceMessageId && identity.sourceMessageId !== null
    if (!valid) {
      emit('turn-intent-receipt', { nonce: intent.nonce, accepted: false, detail: '联系人或最新消息已变化；未应用本轮意图。' })
      return
    }
    if (intent.action === 'undo') {
      if (!turnIntentSnapshot || turnIntentSnapshot.sessionId !== identity.sessionId
          || turnIntentSnapshot.sourceMessageId !== identity.sourceMessageId) {
        emit('turn-intent-receipt', { nonce: intent.nonce, accepted: false, detail: '当前回合没有可撤销的意图。' })
        return
      }
      currentTurnPersona.value = turnIntentSnapshot.persona
      currentGoal.value = turnIntentSnapshot.goal
      doNotLearn.value = turnIntentSnapshot.doNotLearn
      turnIntentSnapshot = null
      abortGeneration()
      emit('turn-intent-receipt', { nonce: intent.nonce, accepted: true, undone: true, detail: '已撤销本轮覆盖；旧候选已作废，未发送消息。' })
      return
    }
    if (!intent.currentTurnPersona || intent.currentTurnPersona.length > 1600
        || /[\u0000-\u001f\u007f]/.test(intent.currentTurnPersona)) {
      emit('turn-intent-receipt', { nonce: intent.nonce, accepted: false, detail: '本轮人格内容无效或超出原生 1600 字限制。' })
      return
    }
    if (!turnIntentSnapshot) {
      turnIntentSnapshot = {
        sessionId: identity.sessionId, sourceMessageId: identity.sourceMessageId!,
        persona: currentTurnPersona.value, goal: currentGoal.value, doNotLearn: doNotLearn.value,
      }
    }
    currentTurnPersona.value = intent.currentTurnPersona
    if (intent.currentGoal !== undefined) currentGoal.value = intent.currentGoal
    if (intent.doNotLearn !== undefined) doNotLearn.value = intent.doNotLearn
    abortGeneration()
    emit('turn-intent-receipt', { nonce: intent.nonce, accepted: true, detail: '已进入当前 Reply Brain 的本轮设置。请重新生成建议；没有发送或学习。' })
  },
  { flush: 'sync' },
)

watch(
  () => [props.chat.session_id, props.chat.customer.id, props.chat.agent.id, latestInboundId()],
  (_, previous) => {
    if (previous) {
      turnIntentSnapshot = null
      currentTurnPersona.value = ''
      currentTurnCorrection.value = ''
      currentGoal.value = ''
      doNotLearn.value = Boolean(props.initialDoNotLearn)
    }
    notifyActiveTurn()
  },
  { flush: 'sync' },
)

watch(
  () => props.chat.session_id,
  () => {
    // Invalidate BOTH an in-flight generation and a pending evidence adoption.
    // Neither is allowed to stage into the next contact's single Composer.
    generationEpoch++
    busy.value = false
    resettingSession = true
    adoptingCandidateId.value = null
    runtime.value = null
    lastHydratedTurnId = null
    // Do not orphan in-flight writes from the old session: their captured
    // sessionId check fails closed if the contact changes.
    turnWriteQueue = Promise.resolve()
    candidates.value = []
    sourceMessageId.value = null
    contextRevision.value = ''
    expanded.value = false
    assist.value = false
    allowSensitiveContext.value = false
    currentGoal.value = ''
    currentTurnPersona.value = ''
    currentTurnCorrection.value = ''
    longTermGoal.value = ''
    storedLongTermGoal.value = ''
    longTermGoalDirty.value = false
    error.value = ''
    history.value = []
    historyOpen.value = false
    replyState.value = { state: 'idle', detail: '打开后按当前会话生成建议。' }
    // The panel stays mounted while the native contact changes.
    if (props.open) {
      if (props.chat.user_id) assist.value = true
      void generate(3)
    }
    void nextTick(() => { resettingSession = false })
  },
)

watch(
  [currentGoal, allowSensitiveContext],
  () => {
    if (!hydratingRuntime && !resettingSession) void queueTurnControlsWrite()
  },
)

watch(
  [currentGoal, currentTurnPersona, currentTurnCorrection, longTermGoal,
    strategy, deepReply, allowSensitiveContext, doNotLearn],
  () => {
    if (!hydratingRuntime && !resettingSession && (candidates.value.length || busy.value)) {
      generationEpoch++
      busy.value = false
      markStale()
    }
  },
)

watch(
  () => [props.chat.session_id, props.chat.user_id, props.chat.agent.ai_replies_enabled,
    props.chat.messages.length, latestInboundId()],
  (_, previous) => {
    // Contact changes are owned by the session watcher, which safely starts
    // the new inference. Do not immediately cancel that new request here.
    if (previous?.[0] !== props.chat.session_id) return
    if (candidates.value.length || busy.value) {
      generationEpoch++
      busy.value = false
      markStale()
    }
  },
)

watch(
  () => props.initialCurrentGoal,
  value => { currentGoal.value = value ?? '' },
)

watch(
  () => props.initialCurrentTurnPersona,
  value => { currentTurnPersona.value = value ?? '' },
)

watch(
  () => props.initialLongTermGoal,
  value => {
    if (!value) return
    longTermGoal.value = value
    longTermGoalDirty.value = value !== storedLongTermGoal.value
  },
)

watch(
  () => props.initialDoNotLearn,
  value => { doNotLearn.value = Boolean(value) },
)

watch(
  () => props.recomputeToken,
  (value, previous) => {
    if (!props.open || !value || value === previous) return
    void generate(3, true)
  },
)

watch(
  () => props.abortToken,
  (value, previous) => {
    if (!value || value === previous) return
    abortGeneration()
  },
)

watch(
  () => props.open,
  (open) => {
    if (!open) {
      // The panel is an operator-owned draft surface, never background inference.
      if (busy.value) {
        generationEpoch++
        busy.value = false
        candidates.value = []
        replyState.value = { state: 'idle', detail: '打开后按当前会话生成建议。' }
      }
      return
    }
    if (replyState.value.state !== 'idle') return
    if (props.chat.user_id) assist.value = true
    void generate(3)
  },
)
</script>

<template>
  <section
    class="yance-reply-runtime"
    data-yance-reply-runtime
    :data-yance-reply-mode="mode"
    :data-yance-reply-state="open ? replyState.state : 'collapsed'"
  >
    <button
      type="button"
      class="yance-reply-runtime__toggle"
      data-yance-reply-toggle
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      言策建议
    </button>

    <div v-if="open" class="yance-reply-runtime__panel" data-yance-reply-panel>
      <div class="yance-reply-runtime__modes" data-yance-reply-modes>
        <strong>回复模式</strong>
        <button type="button" :aria-pressed="mode === 'HUMAN'" @click="selectMode('HUMAN')">HUMAN</button>
        <button type="button" :aria-pressed="mode === 'AI_ASSIST'" @click="selectMode('AI_ASSIST')">AI_ASSIST</button>
        <button type="button" :aria-pressed="mode === 'AI_AUTO'" :disabled="runtime?.ai_auto_available === false" @click="selectMode('AI_AUTO')">AI_AUTO</button>
        <small>HUMAN / ASSIST 作用于当前会话；AI_AUTO 权限由现有 Agent.ai_replies_enabled 决定。</small>
      </div>

      <details class="yance-reply-runtime__settings">
        <summary>本轮设置与长期目标</summary>
      <div class="yance-reply-runtime__controls" data-yance-reply-controls>
        <label>当前目标 <input v-model="currentGoal" data-yance-current-goal maxlength="600" placeholder="仅本轮，自动保存到会话历史" /></label>
        <label>本轮 Persona <input v-model="currentTurnPersona" data-yance-current-turn-persona maxlength="1600" placeholder="仅本轮，不持久化" /></label>
        <label>长期目标
          <input
            v-model="longTermGoal"
            data-yance-long-term-goal-input
            maxlength="1000"
            placeholder="显式确认后写入现有关系记忆"
            @input="longTermGoalDirty = true"
          />
        </label>
        <button
          type="button"
          data-yance-save-long-term-goal
          :disabled="busy || (!longTermGoalDirty && longTermGoal === storedLongTermGoal)"
          @click="saveLongTermGoal"
        >
          保存长期目标
        </button>
        <label><input v-model="allowSensitiveContext" type="checkbox" data-yance-sensitive-context-permission /> 允许本轮敏感上下文（可随时撤销，变更写入现有会话权限）</label>
        <label>本轮纠正 <input v-model="currentTurnCorrection" data-yance-current-turn-correction maxlength="800" placeholder="仅本轮，不学习" /></label>
        <label>策略
          <select v-model="strategy" data-yance-balance-strategy>
            <option value="balanced">Balance</option>
            <option value="warm">Warm</option>
            <option value="direct">Direct</option>
            <option value="playful">Playful</option>
          </select>
        </label>
        <label><input v-model="deepReply" type="checkbox" data-yance-deep-reply /> deep_reply</label>
        <label><input v-model="doNotLearn" type="checkbox" data-yance-do-not-learn /> do_not_learn</label>
        <button
          type="button"
          data-yance-recompute
          :disabled="busy"
          @click="generate(3, true)"
        >
          重新生成
        </button>
      </div>

      </details>

      <div class="yance-reply-runtime__owner-state">
        <span data-yance-peer-typing-owner data-owner-state="unavailable">peer typing：无 admitted owner</span>
        <span data-yance-long-term-goal data-owner-state="ready">长期目标：现有 Customer 关系记忆</span>
      </div>

      <section
        v-if="replyState.state !== 'ready'"
        class="yance-reply-state-card"
        data-yance-reply-secondary-state
        :data-state="replyState.state"
      >
        <strong>{{ stateLabel }}</strong>
        <p v-if="replyState.detail">{{ replyState.detail }}</p>
        <details v-if="replyState.why">
          <summary>为什么这样建议？</summary>
          <p>{{ replyState.why }}</p>
        </details>
      </section>

      <YanceReplyBrainCandidateCard
        v-for="candidate in visibleCandidates"
        :key="candidate.id"
        :candidate="candidate"
        :processing="adoptingCandidateId === candidate.id"
        @adopt="adopt"
        @reject="reject"
      />

      <button
        v-if="canExpand"
        type="button"
        data-yance-more-candidates
        :disabled="busy"
        @click="generate(5, true)"
      >
        更多建议（最多 5 条）
      </button>

      <details class="yance-reply-runtime__learning" data-yance-learning>
        <summary>学习与长期规则</summary>
        <div>
          <select v-model="durableScope" data-yance-rule-scope>
            <option value="contact">仅此联系人</option>
            <option value="global">全局</option>
          </select>
          <input v-model="durableRule" data-yance-durable-rule maxlength="1200" placeholder="批准后写入现有 Persona instructions" />
          <button type="button" data-yance-save-rule @click="saveRule">保存长期规则</button>
          <button type="button" data-yance-learning-history @click="loadHistory">历史 / 回滚</button>
        </div>
        <ul v-if="historyOpen" data-yance-learning-history-list>
          <li v-for="version in history" :key="version.transaction_id">
            <span>#{{ version.transaction_id }}</span>
            <button type="button" @click="rollback(version.transaction_id)">回滚</button>
          </li>
        </ul>
      </details>

      <p v-if="error" class="yance-reply-runtime__error" data-yance-reply-error>{{ error }}</p>
    </div>
  </section>
</template>

<style scoped>
.yance-reply-runtime {
  flex: 0 0 auto;
  min-width: 0;
  padding: 7px 12px;
  border-top: 1px solid var(--o08);
  background: var(--bg);
}
.yance-reply-runtime__toggle,
.yance-reply-runtime button,
.yance-reply-runtime input,
.yance-reply-runtime select {
  border: 1px solid var(--o10);
  border-radius: var(--radius-btn, 8px);
  background: var(--o05);
  color: var(--text);
  padding: 6px 9px;
}
.yance-reply-runtime__panel {
  display: grid;
  min-width: 0;
  gap: 8px;
  max-height: min(190px, 31dvh);
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  margin-top: 6px;
}
.yance-reply-runtime__panel > * {
  min-width: 0;
  max-width: 100%;
}
.yance-reply-runtime__settings {
  min-width: 0;
  border: 1px solid var(--o10);
  border-radius: 8px;
  padding: 7px 9px;
}
.yance-reply-runtime__settings summary {
  cursor: pointer;
  color: var(--text);
  font-size: 12px;
}
.yance-reply-runtime__settings[open] .yance-reply-runtime__controls {
  margin-top: 8px;
}
.yance-reply-runtime__modes,
.yance-reply-runtime__controls,
.yance-reply-runtime__owner-state {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 11px;
}
.yance-reply-runtime__controls label {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  max-width: 100%;
  flex-wrap: wrap;
}
.yance-reply-runtime__controls input:not([type='checkbox']),
.yance-reply-runtime__learning input {
  min-width: 0;
  max-width: 100%;
}
.yance-reply-runtime__owner-state,
.yance-reply-runtime__error {
  color: var(--muted);
}
.yance-reply-runtime__learning > div {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}
</style>
