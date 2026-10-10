import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { shallowMount } from '@vue/test-utils'
import ConversationChat from '@/components/conversations/ConversationChat.vue'

const { sendSpy, adoptAttachmentSpy } = vi.hoisted(() => ({
  sendSpy: vi.fn(),
  adoptAttachmentSpy: vi.fn(),
}))

vi.mock('@/composables/useConversationChat', async () => {
  const { ref } = await import('vue')
  return {
    useConversationChat: () => ({
      newMessage: ref('hello'),
      messagesContainer: ref(null),
      formattedMessages: ref([]),
      isLoading: ref(false),
      showTakeoverButton: ref(false),
      showTakenOverStatus: ref(false),
      isChatClosed: ref(false),
      canSendMessage: ref(true),
      scrollToBottom: vi.fn(),
      sendMessage: vi.fn(),
      handleTakeover: vi.fn(),
      handleRouteToHuman: vi.fn(),
      isWaitingForHuman: ref(false),
      handlerCaption: ref(''),
      updateChat: vi.fn(),
      replaceChatFromProps: vi.fn(),
      handledByAI: ref(false),
      endChat: vi.fn(),
      templateCanReopen: ref(false),
      clearTemplateSuggestion: vi.fn(),
    }),
  }
})

vi.mock('@/composables/useConversationFiles', async () => {
  const { ref } = await import('vue')
  return {
    useConversationFiles: () => {
      const existingAttachmentIds = ref<number[]>([])
      return {
        fileUploadRef: ref(null),
        uploadedFiles: ref([]),
        existingAttachmentIds,
        adoptExistingAttachment: (id: number) => {
          adoptAttachmentSpy(id)
          if (!existingAttachmentIds.value.includes(id)) existingAttachmentIds.value.push(id)
        },
        handleFilesUploaded: vi.fn(),
        handleFileUploadError: vi.fn(),
        handleChatPaste: vi.fn(),
        handleSendMessageWithAttachments: sendSpy,
        formatFileSize: (n: number) => String(n),
        isImageAttachment: () => false,
        isAudioAttachment: () => false,
        isVideoAttachment: () => false,
        getDownloadUrl: (url: string) => url,
        getImageUrl: (url: string) => url,
      }
    },
  }
})

vi.mock('@/composables/useVisualViewport', () => ({ useVisualViewport: () => {} }))
vi.mock('@/composables/useJiraTicket', async () => {
  const { ref } = await import('vue')
  return { useJiraTicket: () => ({ jiraConnected: ref(false), checkJiraStatus: vi.fn().mockResolvedValue(undefined) }) }
})
vi.mock('@/services/tickets', () => ({
  ticketService: { getTicketBySession: vi.fn().mockResolvedValue(null) },
}))
vi.mock('@/utils/permissions', () => ({
  permissionChecks: { canManageTickets: () => false },
}))
vi.mock('@/services/user', () => ({
  userService: {
    getCurrentUser: () => null,
    getUserId: () => 'user-1',
  },
}))
vi.mock('@/services/voice', () => ({
  voiceService: { generateSpeech: vi.fn() },
}))

const chat: any = {
  customer: { id: 'customer-1', email: 'anna@example.test', full_name: 'Anna', profile: null },
  agent: { id: 'agent-1', name: 'Agent', display_name: null },
  session_id: 'session-1',
  messages: [],
  created_at: '2026-10-07T00:00:00Z',
  updated_at: '2026-10-07T00:00:00Z',
  user_id: 'user-1',
  user_name: 'Me',
  group_id: null,
  status: 'open',
  channel: 'messenger',
}

describe('ConversationChat Frozen final send authority', () => {
  it('uses one 发送并学习 carrier for click and Enter on the same native handler', async () => {
    sendSpy.mockClear()
    const wrapper = shallowMount(ConversationChat, {
      props: { chat, frozenYance: true },
      global: { stubs: { 'font-awesome-icon': true } },
    })
    const controls = wrapper.findAll('[data-yance-final-send]')
    expect(controls).toHaveLength(1)
    const control = controls[0]
    expect(control.text()).toContain('发送并学习')
    expect(control.attributes('data-physical-send-owner')).toBe('native')
    expect(control.attributes('data-learning-owner-state')).toBe('unavailable')
    expect(wrapper.find('span[data-yance-send-policy]').exists()).toBe(false)

    await control.trigger('click')
    expect(sendSpy).toHaveBeenCalledTimes(1)

    const composer = wrapper.get('textarea.message-input')
    const shiftEnter = new KeyboardEvent('keydown', {
      key: 'Enter',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    })
    composer.element.dispatchEvent(shiftEnter)
    expect(shiftEnter.defaultPrevented).toBe(false)
    expect(sendSpy).toHaveBeenCalledTimes(1)

    await composer.trigger('compositionstart')
    await composer.trigger('keydown', { key: 'Enter' })
    await composer.trigger('compositionend')
    await composer.trigger('keyup', { key: 'Enter' })
    expect(sendSpy).toHaveBeenCalledTimes(1)

    await composer.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(sendSpy).toHaveBeenCalledTimes(1)

    await composer.trigger('keydown', { key: 'Enter' })
    expect(sendSpy).toHaveBeenCalledTimes(2)
  })

  it('adopts a real FileAttachment or a generation intent into Composer without direct send', async () => {
    sendSpy.mockClear()
    adoptAttachmentSpy.mockClear()
    const wrapper = shallowMount(ConversationChat, {
      props: { chat, frozenYance: true },
      global: { stubs: { 'font-awesome-icon': true } },
      slots: {
        'conversation-extension': (slotProps: any) => [
          h('button', { 'data-test-adopt-asset': '', onClick: () => slotProps.adoptAttachment(123) }, 'asset'),
          h('button', {
            'data-test-adopt-intent': '',
            onClick: () => slotProps.adoptMediaIntent({
              type: 'video',
              label: '视频回复',
              prompt: '生成视频',
              runtimeState: 'runtime-pending',
            }),
          }, 'intent'),
        ],
      },
    })

    await wrapper.get('textarea.message-input').setValue('')
    await wrapper.get('[data-test-adopt-intent]').trigger('click')
    expect(wrapper.get('[data-yance-adopted-media-intent]').attributes('data-runtime-state')).toBe('runtime-pending')
    expect(wrapper.get('[data-yance-final-send]').attributes('disabled')).toBeDefined()
    expect(sendSpy).not.toHaveBeenCalled()

    await wrapper.get('[data-test-adopt-asset]').trigger('click')
    expect(adoptAttachmentSpy).toHaveBeenCalledWith(123)
    expect(wrapper.find('[data-yance-adopted-media-intent]').exists()).toBe(false)
    expect(wrapper.get('[data-yance-final-send]').attributes('disabled')).toBeUndefined()
    expect(sendSpy).not.toHaveBeenCalled()
  })
})
