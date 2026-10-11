export type YanceTranslationStatus = 'loading' | 'success' | 'failed' | 'stale'

export type YanceTranslationProjection = {
  messageId: string | number
  status: YanceTranslationStatus
  text?: string
  sourceLanguage?: string
  targetLanguage?: string
  sourceSha256?: string
  provider?: string
  providerModel?: string
  integrity?: 'passed' | 'failed'
  integrityFailures?: string[]
  errorCode?: string
  stylePolicy?: string
  updatedAt?: string
}

export type YanceHumanLikenessState = 'pass' | 'review' | 'blocked' | 'unknown'
export type YanceCandidateRuntimeState = 'ready' | 'runtime-pending' | 'unavailable'

export type YanceReplyBrainCandidate = {
  id: string
  contextRevision?: string
  type: 'text' | 'voice' | 'photo' | 'image' | 'video' | 'file' | 'other'
  label: string
  draft: string
  why?: string
  evidence?: string[]
  previewLabel?: string
  humanLikeness?: YanceHumanLikenessState
  runtimeState?: YanceCandidateRuntimeState
  /** Existing canonical FileAttachment only; never synthesize this ID in the UI. */
  attachmentId?: number
}

export type YanceReplyBrainState =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'empty'
  | 'no-reply'
  | 'defer'
  | 'platform-switch'
  | 'stale'
  | 'recomputing'
  | 'error'

export type YanceReplyBrainStateProjection = {
  state: YanceReplyBrainState
  title?: string
  detail?: string
  why?: string
  evidence?: string[]
  platform?: string
  canRecompute?: boolean
}

export type YanceGirlfriendScope = 'turn' | 'contact' | 'language' | 'relationship' | 'global'

export type YanceGirlfriendIntentDraft = {
  instruction: string
  scope: YanceGirlfriendScope
  personaNote?: string
  goalNote?: string
  turnOnly: boolean
}

export type YanceScopedTurnIntent = {
  nonce: number
  action: 'apply' | 'undo'
  sessionId: string
  customerId: string
  agentId: string
  sourceMessageId: number
  currentTurnPersona?: string
  currentGoal?: string
  doNotLearn?: boolean
}

export type YanceGirlfriendOrchestrationState =
  | 'idle'
  | 'interpreting'
  | 'clarification'
  | 'scoped-proposal'
  | 'delegated-owner-wait'
  | 'receipt'
  | 'permission-required'
  | 'stale'
  | 'recomputing'

export type YanceGirlfriendOrchestrationProjection = {
  state: YanceGirlfriendOrchestrationState
  title?: string
  detail?: string
  why?: string
  receipt?: string
  capability?: string
  model?: string
  undoAvailable?: boolean
  permissionPrompt?: string
}

export type YanceCapabilityReadinessProjection = {
  runtimeState: 'ready' | 'runtime-pending' | 'unavailable'
  label: string
}
