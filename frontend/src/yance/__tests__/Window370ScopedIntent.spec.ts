import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import YanceReplyBrainRuntimeComposition from '../components/YanceReplyBrainRuntimeComposition.vue'
import type { YanceScopedTurnIntent } from '../semanticTypes'

const native = vi.hoisted(() => ({
  getRuntime: vi.fn(), generateCandidates: vi.fn(), recordEvidence: vi.fn(),
  setTurnControls: vi.fn(), takeoverChat: vi.fn(), releaseToAI: vi.fn(),
}))
vi.mock('@/services/yanceReply', () => ({
  yanceReplyService: { ...native, setLongTermGoal: vi.fn(),
    promoteRule: vi.fn(), learningHistory: vi.fn(), rollbackLearning: vi.fn() },
}))
vi.mock('@/services/sessionToAgent', () => ({
  sessionToAgentService: {
    takeoverChat: native.takeoverChat, releaseToAI: native.releaseToAI,
  },
}))

const chat = (session: string, customer: string, messageId: number) => ({
  session_id: session, user_id: 'user-qa',
  customer: { id: customer },
  agent: { id: 'agent-qa', ai_replies_enabled: true },
  messages: [{ id: messageId, message_type: 'user', message: 'isolated QA inbound' }],
}) as any
const scoped = (session: string, customer: string, messageId: number, nonce = 1): YanceScopedTurnIntent => ({
  nonce, action: 'apply', sessionId: session, customerId: customer,
  agentId: 'agent-qa', sourceMessageId: messageId,
  currentTurnPersona: '本轮成熟、自然回复', doNotLearn: true,
})
const create = () => {
  const adoptDraft = vi.fn()
  const wrapper = mount(YanceReplyBrainRuntimeComposition, {
    props: {
      chat: chat('qa-A', 'customer-A', 101), open: false,
      adoptDraft, adoptAttachment: vi.fn(), adoptMediaIntent: vi.fn(),
    },
  })
  return { wrapper, adoptDraft }
}
describe('W370 source-only isolated native Reply Brain current-turn intent boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    native.getRuntime.mockImplementation(async (sessionId: string) => ({
      mode: 'HUMAN', context_revision: sessionId + ':rev1',
      source_message_id: sessionId === 'qa-A' ? 101 : 202,
      current_turn_controls: null, ai_auto_available: false,
    }))
    native.generateCandidates.mockImplementation(async (sessionId: string) => ({
      state: 'ready', source_message_id: sessionId === 'qa-A' ? 101 : 202,
      context_revision: sessionId + ':rev1', can_recompute: true, candidates: [],
    }))
    native.setTurnControls.mockResolvedValue({})
  })

  it('reports native session identity and does not infer or send before Reply Brain opens', async () => {
    const { wrapper, adoptDraft } = create()
    expect(wrapper.emitted('active-turn')?.[0]?.[0]).toEqual({
      sessionId: 'qa-A', customerId: 'customer-A',
      agentId: 'agent-qa', sourceMessageId: 101,
    })
    await wrapper.setProps({ turnIntent: scoped('qa-A', 'customer-A', 101) })
    expect(wrapper.emitted('turn-intent-receipt')?.at(-1)?.[0]).toMatchObject({
      nonce: 1, accepted: true,
    })
    expect(native.generateCandidates).not.toHaveBeenCalled()
    expect(adoptDraft).not.toHaveBeenCalled()
    await wrapper.setProps({ open: true })
    expect((wrapper.get('[data-yance-do-not-learn]').element as HTMLInputElement).checked).toBe(true)
    await wrapper.get('[data-yance-recompute]').trigger('click')
    await flushPromises()
    expect(native.generateCandidates).toHaveBeenCalledWith('qa-A', expect.objectContaining({
      current_turn_persona: '本轮成熟、自然回复',
      limit: 3,
    }))
    expect(adoptDraft).not.toHaveBeenCalled()
  })

  it('rejects cross-contact and wrong-source payloads without carrying instructions into B', async () => {
    const { wrapper } = create()
    await wrapper.setProps({ chat: chat('qa-B', 'customer-B', 202) })
    await wrapper.setProps({ turnIntent: scoped('qa-A', 'customer-A', 101) })
    expect(wrapper.emitted('turn-intent-receipt')?.at(-1)?.[0]).toMatchObject({ accepted: false })
    await wrapper.setProps({ open: true })
    await wrapper.get('[data-yance-recompute]').trigger('click')
    await flushPromises()
    expect(native.generateCandidates).toHaveBeenCalledWith('qa-B', expect.objectContaining({
      current_turn_persona: undefined,
    }))
  })

  it('invalidates the current-turn persona after another inbound message in the same session', async () => {
    const { wrapper } = create()
    await wrapper.setProps({ turnIntent: scoped('qa-A', 'customer-A', 101) })
    await wrapper.setProps({ chat: chat('qa-A', 'customer-A', 102) })
    await wrapper.setProps({ open: true })
    expect((wrapper.get('[data-yance-do-not-learn]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('[data-yance-recompute]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('active-turn')?.at(-1)?.[0]).toMatchObject({ sourceMessageId: 102 })
    expect(native.generateCandidates).toHaveBeenCalledWith('qa-A', expect.objectContaining({
      current_turn_persona: undefined,
    }))
  })

  it('undo restores earlier transient values and never alters the unique Composer', async () => {
    const { wrapper, adoptDraft } = create()
    await wrapper.setProps({ turnIntent: scoped('qa-A', 'customer-A', 101) })
    await wrapper.setProps({ turnIntent: {
      ...scoped('qa-A', 'customer-A', 101, 2), action: 'undo',
    } })
    expect(wrapper.emitted('turn-intent-receipt')?.at(-1)?.[0]).toMatchObject({
      nonce: 2, accepted: true, undone: true,
    })
    await wrapper.setProps({ open: true })
    await wrapper.get('[data-yance-recompute]').trigger('click')
    await flushPromises()
    expect(native.generateCandidates).toHaveBeenCalledWith('qa-A', expect.objectContaining({
      current_turn_persona: undefined,
    }))
    expect(adoptDraft).not.toHaveBeenCalled()
  })

  it('rejects an oversized turn override and does not call the backend with it', async () => {
    const { wrapper } = create()
    await wrapper.setProps({
      turnIntent: { ...scoped('qa-A', 'customer-A', 101), currentTurnPersona: 'x'.repeat(1601) },
    })
    expect(wrapper.emitted('turn-intent-receipt')?.at(-1)?.[0]).toMatchObject({ accepted: false })
    expect(native.generateCandidates).not.toHaveBeenCalled()
  })

  it('fails closed when native generation fails, then permits explicit retry', async () => {
    native.generateCandidates.mockRejectedValueOnce({ response: { status: 503 } })
    const { wrapper, adoptDraft } = create()
    await wrapper.setProps({ turnIntent: scoped('qa-A', 'customer-A', 101) })
    await wrapper.setProps({ open: true })
    await wrapper.get('[data-yance-recompute]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-yance-reply-secondary-state]').attributes('data-state')).toBe('error')
    expect(adoptDraft).not.toHaveBeenCalled()
    await wrapper.get('[data-yance-recompute]').trigger('click')
    await flushPromises()
    expect(native.generateCandidates).toHaveBeenCalledTimes(2)
    expect(adoptDraft).not.toHaveBeenCalled()
  })
})
