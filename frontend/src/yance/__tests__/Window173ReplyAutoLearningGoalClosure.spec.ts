import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const service = vi.hoisted(() => ({
  getRuntime: vi.fn(),
  setTurnControls: vi.fn(),
  generateCandidates: vi.fn(),
  recordEvidence: vi.fn(),
  promoteRule: vi.fn(),
  learningHistory: vi.fn(),
  rollbackLearning: vi.fn(),
  goalOwner: vi.fn(),
  takeoverChat: vi.fn(),
  releaseToAI: vi.fn(),
}))

vi.mock('@/services/yanceReply', () => ({
  yanceReplyService: {
    getRuntime: service.getRuntime,
    setTurnControls: service.setTurnControls,
    generateCandidates: service.generateCandidates,
    recordEvidence: service.recordEvidence,
    promoteRule: service.promoteRule,
    learningHistory: service.learningHistory,
    rollbackLearning: service.rollbackLearning,
    goalOwner: service.goalOwner,
  },
}))

vi.mock('@/services/sessionToAgent', () => ({
  sessionToAgentService: {
    takeoverChat: service.takeoverChat,
    releaseToAI: service.releaseToAI,
  },
}))

import YanceReplyBrainRuntimeComposition from '../components/YanceReplyBrainRuntimeComposition.vue'

const candidate = (id: number) => ({
  id: `101:${id}`,
  type: 'text' as const,
  label: `候选 ${id}`,
  draft: `reply ${id}`,
  contextRevision: '101:r1',
  why: `why ${id}`,
  humanLikeness: 'pass' as const,
  runtimeState: 'ready' as const,
})

const chat = () => ({
  session_id: '00000000-0000-0000-0000-000000000123',
  user_id: '00000000-0000-0000-0000-000000000456',
  customer: {
    id: 'customer-1',
    email: 'test@example.com',
    full_name: 'Test',
  },
  agent: {
    id: 'agent-1',
    name: 'Agent',
    display_name: 'Agent',
    ai_replies_enabled: true,
  },
  messages: [
    { id: 101, message_type: 'user', message: 'hello' },
  ],
  created_at: '2026-10-07T00:00:00Z',
  updated_at: '2026-10-07T00:00:00Z',
}) as any

const runtime = {
  mode: 'HUMAN',
  session_scope_available: true,
  ai_auto_scope: 'session',
  ai_auto_permission_owner: 'Agent.ai_replies_enabled',
  sensitive_confirmation_required: true,
  ai_auto_enabled: true,
  // Backend positively qualifies this human-held Web session for release.
  ai_auto_available: true,
  human_owner_user_id: '00000000-0000-0000-0000-000000000456',
  session_status: 'OPEN',
  source_message_id: 101,
  context_revision: '101:r1',
  peer_typing_owner: 'unavailable',
  long_term_goal_owner: 'unavailable',
}

describe('Window173 Reply Brain / AI_AUTO / learning runtime composition', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    service.getRuntime.mockResolvedValue(runtime)
    service.setTurnControls.mockImplementation(async (_id, body) => ({
      source_message_id: body.source_message_id,
      version: body.expected_version + 1,
      current_goal: body.current_goal,
      allow_sensitive_context: body.allow_sensitive_context,
    }))
    service.generateCandidates
      .mockResolvedValueOnce({
        state: 'ready',
        candidates: [candidate(1), candidate(2), candidate(3)],
        why: 'current turn',
        balance_strategy: 'balanced',
        deep_reply: '',
        can_recompute: true,
        source_message_id: 101,
        context_revision: '101:r1',
      })
      .mockResolvedValueOnce({
        state: 'ready',
        candidates: [candidate(1), candidate(2), candidate(3), candidate(4), candidate(5)],
        why: 'expanded',
        balance_strategy: 'balanced',
        deep_reply: '',
        can_recompute: true,
        source_message_id: 101,
        context_revision: '101:r1',
      })
    service.recordEvidence.mockResolvedValue({ recorded: true, stale: false })
    service.learningHistory.mockResolvedValue({ versions: [] })
    service.promoteRule.mockResolvedValue({ promoted: true })
    service.rollbackLearning.mockResolvedValue({ rolled_back: true })
    service.takeoverChat.mockResolvedValue(chat())
    service.releaseToAI.mockResolvedValue({ ...chat(), user_id: null })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  const mountRuntime = () => {
    const adoptDraft = vi.fn()
    const adoptAttachment = vi.fn()
    const adoptMediaIntent = vi.fn()
    const wrapper = mount(YanceReplyBrainRuntimeComposition, {
      props: {
        chat: chat(),
        open: false,
        adoptDraft,
        adoptAttachment,
        adoptMediaIntent,
      },
    })
    return { wrapper, adoptDraft, adoptAttachment, adoptMediaIntent }
  }

  it('generates 0-3 by default and performs a real max-5 recompute on expansion', async () => {
    const { wrapper } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()

    expect(service.generateCandidates).toHaveBeenNthCalledWith(
      1,
      expect.any(String),
      expect.objectContaining({ limit: 3 }),
    )
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(3)

    await wrapper.get('[data-yance-more-candidates]').trigger('click')
    await flushPromises()

    expect(service.generateCandidates).toHaveBeenNthCalledWith(
      2,
      expect.any(String),
      expect.objectContaining({ limit: 5 }),
    )
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(5)
  })

  it('records adopt evidence before staging the same candidate into the canonical Composer seam', async () => {
    const { wrapper, adoptDraft } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()

    await wrapper.findAll('[data-yance-adopt]')[0].trigger('click')
    await flushPromises()

    expect(service.recordEvidence).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        source_message_id: 101,
        candidate_id: '101:1',
        decision: 'adopt',
        do_not_learn: false,
      }),
    )
    expect(adoptDraft).toHaveBeenCalledWith('reply 1')
  })

  it('records reject evidence without mutating the Composer', async () => {
    const { wrapper, adoptDraft } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()

    await wrapper.findAll('[data-yance-reject]')[0].trigger('click')
    await flushPromises()

    expect(service.recordEvidence).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ decision: 'reject', candidate_id: '101:1' }),
    )
    expect(adoptDraft).not.toHaveBeenCalled()
  })

  it('fails closed on stale evidence and never adopts an obsolete candidate', async () => {
    const { wrapper, adoptDraft } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()
    service.recordEvidence.mockRejectedValueOnce({ response: { status: 409 } })

    await wrapper.findAll('[data-yance-adopt]')[0].trigger('click')
    await flushPromises()

    expect(adoptDraft).not.toHaveBeenCalled()
    expect(wrapper.get('[data-yance-reply-secondary-state]').attributes('data-state')).toBe('stale')
  })

  it('treats an opened human-held Reply Brain as AI_ASSIST and HUMAN clears generated candidates', async () => {
    const { wrapper } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()

    expect(wrapper.get('[data-yance-reply-runtime]').attributes('data-yance-reply-mode')).toBe('AI_ASSIST')
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(3)

    const human = wrapper.findAll('[data-yance-reply-modes] button').find(button => button.text() === 'HUMAN')
    expect(human).toBeTruthy()
    await human!.trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-yance-reply-runtime]').attributes('data-yance-reply-mode')).toBe('HUMAN')
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(0)
  })
  it('requires explicit sensitive confirmation before releasing a human-held session to existing AI_AUTO', async () => {
    const { wrapper } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()

    const auto = wrapper.findAll('[data-yance-reply-modes] button').find(button => button.text() === 'AI_AUTO')
    expect(auto).toBeTruthy()
    await auto!.trigger('click')
    await flushPromises()

    expect(window.confirm).toHaveBeenCalled()
    expect(service.releaseToAI).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-yance-reply-runtime]').attributes('data-yance-reply-mode')).toBe('AI_AUTO')
  })

  it('keeps current-turn goal/correction transient and uses admitted Customer long-term-goal owner', async () => {
    const { wrapper } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()

    await wrapper.get('[data-yance-current-goal]').setValue('reply warmly')
    await wrapper.get('[data-yance-current-turn-correction]').setValue('no questions')
    await wrapper.get('[data-yance-recompute]').trigger('click')
    await flushPromises()

    expect(service.generateCandidates).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({
        current_goal: 'reply warmly',
        current_turn_correction: 'no questions',
      }),
    )
    expect(wrapper.get('[data-yance-long-term-goal]').attributes('data-owner-state')).toBe('ready')
    expect(wrapper.get('[data-yance-peer-typing-owner]').attributes('data-owner-state')).toBe('unavailable')
  })

  it('hydrates durable current-turn controls then persists Goal edits with exact CAS', async () => {
    service.getRuntime.mockResolvedValue({
      ...runtime,
      current_turn_controls: {
        source_message_id: 101, version: 4,
        current_goal: 'be warm', allow_sensitive_context: false,
      },
    })
    const { wrapper } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect((wrapper.get('[data-yance-current-goal]').element as HTMLInputElement).value).toBe('be warm')
    expect(service.setTurnControls).not.toHaveBeenCalled()
    await wrapper.get('[data-yance-current-goal]').setValue('be concise')
    await flushPromises()
    expect(service.setTurnControls).toHaveBeenCalledWith(
      chat().session_id,
      expect.objectContaining({
        source_message_id: 101,
        expected_version: 4,
        current_goal: 'be concise',
        allow_sensitive_context: false,
      }),
    )
  })

  it('persists sensitive permission revocation before more AI_AUTO activity', async () => {
    service.getRuntime.mockResolvedValue({
      ...runtime,
      current_turn_controls: {
        source_message_id: 101, version: 7,
        current_goal: null, allow_sensitive_context: true,
      },
    })
    const { wrapper } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect((wrapper.get('[data-yance-sensitive-context-permission]').element as HTMLInputElement).checked).toBe(true)
    await wrapper.get('[data-yance-sensitive-context-permission]').setValue(false)
    await flushPromises()
    expect(service.setTurnControls).toHaveBeenCalledWith(
      chat().session_id,
      expect.objectContaining({
        source_message_id: 101, expected_version: 7,
        allow_sensitive_context: false,
      }),
    )
  })

  it('fails closed on conflicting turn revision and refuses stale candidates', async () => {
    service.getRuntime.mockResolvedValue({
      ...runtime,
      current_turn_controls: {
        source_message_id: 101, version: 2,
        current_goal: null, allow_sensitive_context: false,
      },
    })
    const { wrapper } = mountRuntime()
    await wrapper.setProps({ open: true })
    await flushPromises()
    service.setTurnControls.mockRejectedValueOnce({ response: { status: 409 } })
    await wrapper.get('[data-yance-current-goal]').setValue('outdated')
    await flushPromises()
    expect(wrapper.get('[data-yance-reply-secondary-state]').attributes('data-state')).toBe('stale')
    expect(service.setTurnControls).toHaveBeenCalledTimes(1)
  })
})
