import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import YanceReplyBrainRuntimeComposition from '../components/YanceReplyBrainRuntimeComposition.vue'

const services = vi.hoisted(() => ({
  getRuntime: vi.fn(),
  generateCandidates: vi.fn(),
  recordEvidence: vi.fn(),
  setTurnControls: vi.fn(),
  takeoverChat: vi.fn(),
  releaseToAI: vi.fn(),
}))
vi.mock('@/services/yanceReply', () => ({
  yanceReplyService: {
    ...services,
    setLongTermGoal: vi.fn(),
    promoteRule: vi.fn(),
    learningHistory: vi.fn(),
    rollbackLearning: vi.fn(),
  },
}))
vi.mock('@/services/sessionToAgent', () => ({
  sessionToAgentService: {
    takeoverChat: services.takeoverChat,
    releaseToAI: services.releaseToAI,
  },
}))

const chat = (suffix: string, inboundId: number) => ({
  session_id: '00000000-0000-0000-0000-000000000' + suffix,
  user_id: 'user-1',
  agent: { id: 'agent-1', ai_replies_enabled: true },
  customer: { id: 'customer-1' },
  messages: [{ id: inboundId, message_type: 'user', message: 'hello' }],
}) as any

const reply = (sourceId: number, revision: string, count = 1) => ({
  state: 'ready' as const, context_revision: revision,
  source_message_id: sourceId, can_recompute: true,
  candidates: Array.from({ length: count }, (_, i) => ({
    id: sourceId + ':' + (i + 1), contextRevision: revision,
    label: '候选', type: 'text' as const, runtimeState: 'ready' as const,
    humanLikeness: 'pass' as const, draft: 'reply-' + sourceId,
  })),
})
const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const create = () => {
  const adoptDraft = vi.fn()
  const wrapper = mount(YanceReplyBrainRuntimeComposition, {
    props: { chat: chat('123', 101), open: false, adoptDraft,
      adoptAttachment: vi.fn(), adoptMediaIntent: vi.fn() },
  })
  return { wrapper, adoptDraft }
}
describe('W353 Reply Brain live owner boundary / asynchronous contact isolation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    services.getRuntime.mockImplementation(async (id: string) => ({
      mode: 'HUMAN', ai_auto_available: false,
      context_revision: id.endsWith('123') ? '101:r1' : '202:r2',
      source_message_id: id.endsWith('123') ? 101 : 202,
      current_turn_controls: null,
    }))
    services.generateCandidates.mockImplementation(async (id: string) =>
      id.endsWith('123') ? reply(101, '101:r1') : reply(202, '202:r2'))
    services.recordEvidence.mockResolvedValue({ recorded: true, stale: false })
    services.setTurnControls.mockResolvedValue({})
  })
  it('invalidates old inference and regenerates for new selected contact', async () => {
    const previous = deferred<any>()
    services.generateCandidates.mockImplementation((id: string) =>
      id.endsWith('123') ? previous.promise : Promise.resolve(reply(202, '202:r2')))
    const { wrapper } = create()
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(services.generateCandidates).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ chat: chat('456', 202) })
    await flushPromises()
    expect(services.generateCandidates).toHaveBeenCalledTimes(2)
    previous.resolve(reply(101, '101:r1'))
    await flushPromises()
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(1)
    expect(wrapper.get('[data-yance-reply-candidate] .yance-reply-candidate__draft').text()).toBe('reply-202')
  })
  it('does not stage an old candidate when evidence completes after contact switch', async () => {
    const evidence = deferred<any>()
    services.recordEvidence.mockReturnValueOnce(evidence.promise)
    const { wrapper, adoptDraft } = create()
    await wrapper.setProps({ open: true })
    await flushPromises()
    await wrapper.get('[data-yance-adopt]').trigger('click')
    await flushPromises()
    await wrapper.setProps({ chat: chat('456', 202) })
    await flushPromises()
    evidence.resolve({ recorded: true, stale: false })
    await flushPromises()
    expect(adoptDraft).not.toHaveBeenCalled()
  })
  it('refuses an acknowledged-but-unrecorded adoption, never sends', async () => {
    services.recordEvidence.mockResolvedValue({ recorded: false, stale: false })
    const { wrapper, adoptDraft } = create()
    await wrapper.setProps({ open: true })
    await flushPromises()
    await wrapper.get('[data-yance-adopt]').trigger('click')
    await flushPromises()
    expect(adoptDraft).not.toHaveBeenCalled()
    expect(wrapper.get('[data-yance-reply-secondary-state]').attributes('data-state')).toBe('stale')
  })
  it('represents zero candidates as an explicit empty state', async () => {
    services.generateCandidates.mockResolvedValue(reply(101, '101:r1', 0))
    const { wrapper } = create()
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(wrapper.get('[data-yance-reply-secondary-state]').attributes('data-state')).toBe('empty')
    expect(wrapper.findAll('[data-yance-adopt]')).toHaveLength(0)
  })
  it('discards a response if the panel closes before completion', async () => {
    const previous = deferred<any>()
    services.generateCandidates.mockReturnValue(previous.promise)
    const { wrapper, adoptDraft } = create()
    await wrapper.setProps({ open: true })
    await flushPromises()
    await wrapper.setProps({ open: false })
    previous.resolve(reply(101, '101:r1'))
    await flushPromises()
    expect(wrapper.findAll('[data-yance-adopt]')).toHaveLength(0)
    expect(adoptDraft).not.toHaveBeenCalled()
  })
})
