import api from './api'
import type { YanceReplyBrainCandidate } from '@/yance/semanticTypes'

export type YanceReplyMode = 'HUMAN' | 'AI_ASSIST' | 'AI_AUTO'

export type ReplyRuntimeProjection = {
  mode: 'HUMAN' | 'AI_AUTO'
  session_scope_available: boolean
  ai_auto_scope: 'session'
  ai_auto_available?: boolean
  ai_auto_unavailable_reason?: string | null
  ai_auto_permission_owner: 'Agent.ai_replies_enabled'
  sensitive_confirmation_required: boolean
  ai_auto_enabled: boolean
  human_owner_user_id?: string | null
  session_status: string
  source_message_id?: number | null
  context_revision: string
  peer_typing_owner: 'unavailable' | 'ready'
  long_term_goal_owner: 'unavailable' | 'ready'
  long_term_goal?: string | null
  goal_owner?: 'Customer.meta_data.relationship_memory'
  current_turn_controls?: {
    source_message_id: number
    version: number
    current_goal: string | null
    allow_sensitive_context: boolean
  } | null
  current_turn_owner?: 'ChatHistory.attributes.yance_current_turn_controls'
}

export type ReplyCandidateEnvelope = {
  state: 'ready' | 'no_reply' | 'defer' | 'stale'
  candidates: YanceReplyBrainCandidate[]
  why?: string | null
  balance_strategy?: string | null
  deep_reply?: string | null
  can_recompute?: boolean
  source_message_id?: number | null
  context_revision: string
}

export const yanceReplyService = {
  async getRuntime(sessionId: string) {
    const { data } = await api.get<ReplyRuntimeProjection>(`/yance/sessions/${sessionId}/reply-runtime`)
    return data
  },

  async setTurnControls(sessionId: string, payload: {
    source_message_id: number
    expected_version: number
    current_goal: string | null
    allow_sensitive_context: boolean
  }) {
    const { data } = await api.put<NonNullable<ReplyRuntimeProjection['current_turn_controls']>>(
      `/yance/sessions/${sessionId}/reply-turn-controls`, payload,
    )
    return data
  },

  async setLongTermGoal(sessionId: string, goal: string | null) {
    const { data } = await api.put<{ long_term: string | null }>(
      '/yance/sessions/' + sessionId + '/long-term-goal', { goal },
    )
    return data
  },

  async generateCandidates(sessionId: string, payload: {
    limit: 3 | 5
    expected_revision?: string
    current_goal?: string
    current_turn_persona?: string
    allow_sensitive_context?: boolean
    current_turn_correction?: string
    strategy?: string
    deep_reply?: boolean
  }) {
    const { data } = await api.post<ReplyCandidateEnvelope>(
      `/yance/sessions/${sessionId}/reply-candidates`,
      payload,
    )
    return data
  },

  async recordEvidence(sessionId: string, payload: {
    source_message_id: number
    context_revision: string
    candidate_id: string
    decision: 'adopt' | 'reject'
    draft: string
    do_not_learn: boolean
  }) {
    const { data } = await api.post(`/yance/sessions/${sessionId}/reply-evidence`, payload)
    return data
  },

  async promoteRule(agentId: string, payload: {
    scope: 'global' | 'contact'
    rule: string
    customer_id?: string
  }) {
    const { data } = await api.post(`/yance/agents/${agentId}/learning/rules`, payload)
    return data
  },

  async learningHistory(agentId: string) {
    const { data } = await api.get<{ versions: Array<{ transaction_id: number; instructions: string }> }>(
      `/yance/agents/${agentId}/learning/history`,
    )
    return data
  },

  async rollbackLearning(agentId: string, transactionId: number) {
    const { data } = await api.post(
      `/yance/agents/${agentId}/learning/history/${transactionId}/rollback`,
    )
    return data
  },

  async goalOwner() {
    const { data } = await api.get<{
      current_turn_goal: 'available'
      long_term_goal: 'unavailable' | 'available'
      long_term_goal_hold?: string
    }>('/yance/goal-owner')
    return data
  },
}
