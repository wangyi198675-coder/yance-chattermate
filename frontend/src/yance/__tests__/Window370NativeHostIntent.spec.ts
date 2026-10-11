import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import YanceNativeHostView from '../YanceNativeHostView.vue'

const services = vi.hoisted(() => ({
  getRuntime: vi.fn(), generateCandidates: vi.fn(), recordEvidence: vi.fn(),
  setTurnControls: vi.fn(), takeoverChat: vi.fn(), releaseToAI: vi.fn(),
}))
vi.mock('@/services/yanceReply', () => ({
  yanceReplyService: {
    ...services, setLongTermGoal: vi.fn(), promoteRule: vi.fn(),
    learningHistory: vi.fn(), rollbackLearning: vi.fn(),
  },
}))
vi.mock('@/services/sessionToAgent', () => ({
  sessionToAgentService: {
    takeoverChat: services.takeoverChat, releaseToAI: services.releaseToAI,
  },
}))
const chat = (sessionId: string, customerId: string, inboundId: number) => ({
  session_id: sessionId, user_id: 'qa-operator',
  agent: { id: 'qa-agent', ai_replies_enabled: true },
  customer: { id: customerId },
  messages: [{ id: inboundId, message_type: 'user', message: 'QA only' }],
})
vi.mock('@/views/ConversationsView.vue', () => ({
  default: {
    name: 'ConversationsView', props: ['frozenYance', 'layoutHideHeader'],
    data: () => ({ chat: chat('session-A', 'customer-A', 101), composerDraft: '', sendCount: 0 }),
    methods: {
      adoptDraft(this: { composerDraft: string }, value: string) { this.composerDraft = value },
      adoptAttachment() {},
      adoptMediaIntent() {},
    },
    template: `<div data-qa-conversations>
      <slot name="conversation-header-actions" :chat="chat" />
      <slot name="conversation-extension" :chat="chat"
        :adoptDraft="adoptDraft" :adoptAttachment="adoptAttachment"
        :adoptMediaIntent="adoptMediaIntent" />
      <textarea data-qa-unique-composer v-model="composerDraft" />
    </div>`,
  },
}))
vi.mock('../components/YancePersonaStudio.vue', () => ({
  default: {
    name: 'YancePersonaStudio', props: ['chat', 'turnIntentFeedback'],
    emits: ['turn-override', 'close'],
    template: `<div data-qa-persona-studio>
      <button data-qa-persona-select @click="$emit('turn-override', {
        sessionId: chat.session_id, customerId: chat.customer.id, agentId: chat.agent.id,
        seedId: 'approved-QA', instructions: ['Personaseed only in this turn']
      })">仅本轮</button>
      <span data-qa-persona-receipt>{{ turnIntentFeedback }}</span>
    </div>`,
  },
}))
describe('W370 native-host actual mounted child event chain (service-isolated fixture)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    services.getRuntime.mockImplementation(async (id: string) => ({
      context_revision: id + ':rev1', source_message_id: id === 'session-A' ? 101 : 202,
      ai_auto_available: false, current_turn_controls: null,
    }))
    services.generateCandidates.mockImplementation(async (id: string) => ({
      state: 'ready', context_revision: id + ':rev1',
      source_message_id: id === 'session-A' ? 101 : 202,
      can_recompute: true, candidates: [],
    }))
  })
  const host = () => mount(YanceNativeHostView)
  it('consumes Girlfriend draft into exactly the active Reply Brain and not Composer/send', async () => {
    const wrapper = host()
    await wrapper.get('[data-yance-girlfriend-toggle]').trigger('click')
    await wrapper.get('[data-yance-girlfriend-intent]').setValue('先接住对方的信息')
    await wrapper.get('[data-yance-stage-intent]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-yance-girlfriend-receipt]').attributes('data-receipt-state')).toBe('ready')
    expect((wrapper.get('[data-yance-current-turn-persona]').element as HTMLInputElement).value).toContain('先接住对方的信息')
    expect(wrapper.findAll('[data-qa-unique-composer]')).toHaveLength(1)
    expect((wrapper.get('[data-qa-unique-composer]').element as HTMLTextAreaElement).value).toBe('')
    expect(services.generateCandidates).not.toHaveBeenCalled()
    await wrapper.get('[data-yance-recompute]').trigger('click')
    await flushPromises()
    expect(services.generateCandidates).toHaveBeenCalledWith('session-A', expect.objectContaining({
      current_turn_persona: '先接住对方的信息',
    }))
  })
  it('refuses contact/global intent instead of showing an unearned success receipt', async () => {
    const wrapper = host()
    await wrapper.get('[data-yance-girlfriend-toggle]').trigger('click')
    await wrapper.get('[data-yance-girlfriend-intent]').setValue('不要过分正式')
    await wrapper.get('input[value="global"]').setValue(true)
    await wrapper.get('[data-yance-stage-intent]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-yance-girlfriend-receipt]').attributes('data-receipt-state')).toBe('error')
    expect(services.generateCandidates).not.toHaveBeenCalled()
  })
  it('undoes scoped draft and invalidates any previous candidates', async () => {
    const wrapper = host()
    await wrapper.get('[data-yance-girlfriend-toggle]').trigger('click')
    await wrapper.get('[data-yance-girlfriend-intent]').setValue('本轮要温柔')
    await wrapper.get('[data-yance-stage-intent]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-yance-girlfriend-local-undo]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-yance-girlfriend-receipt]').text()).toContain('已撤销')
    expect((wrapper.get('[data-yance-current-turn-persona]').element as HTMLInputElement).value).toBe('')
    expect(services.generateCandidates).not.toHaveBeenCalled()
  })
  it('routes a Persona turn-only selection through the same native Reply Brain', async () => {
    const wrapper = host()
    await wrapper.get('[data-yance-persona-control]').trigger('click')
    await wrapper.get('[data-qa-persona-select]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-qa-persona-receipt]').text()).toContain('已进入当前 Reply Brain')
    expect((wrapper.get('[data-yance-current-turn-persona]').element as HTMLInputElement).value).toContain('Personaseed only in this turn')
    expect(services.generateCandidates).not.toHaveBeenCalled()
  })
  it('opens the existing current-chat Girlfriend Brain with Ctrl+Shift+G without creating another Composer', async () => {
    const wrapper = host()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'G', ctrlKey: true, shiftKey: true, bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-yance-girlfriend-native]').exists()).toBe(true)
    expect(wrapper.findAll('[data-qa-unique-composer]')).toHaveLength(1)
    expect(services.generateCandidates).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('defers current-turn shortcut to an already-visible top global Girlfriend dialog', async () => {
    const overlay = document.createElement('div')
    overlay.setAttribute('data-yance-global-girlfriend', '')
    document.body.appendChild(overlay)
    const wrapper = host()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'G', ctrlKey: true, shiftKey: true, bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-yance-girlfriend-native]').exists()).toBe(false)
    expect(wrapper.findAll('[data-qa-unique-composer]')).toHaveLength(1)
    wrapper.unmount()
    overlay.remove()
  })
  it('closes scoped modal when the active contact changes', async () => {
    const wrapper = host()
    await wrapper.get('[data-yance-girlfriend-toggle]').trigger('click')
    await wrapper.get('[data-yance-girlfriend-intent]').setValue('A only')
    await wrapper.get('[data-yance-stage-intent]').trigger('click')
    await flushPromises()
    const conversations = wrapper.getComponent({ name: 'ConversationsView' })
    ;(conversations.vm as any).chat = chat('session-B', 'customer-B', 202)
    await flushPromises()
    expect(wrapper.find('[data-yance-girlfriend-native]').exists()).toBe(false)
    expect((wrapper.get('[data-yance-current-turn-persona]').element as HTMLInputElement).value).toBe('')
  })
})
