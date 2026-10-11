import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ConversationsList from '@/components/conversations/ConversationsList.vue'
import ConversationChat from '@/components/conversations/ConversationChat.vue'
import FileUpload from '@/components/common/FileUpload.vue'
import { chatService } from '@/services/chat'

const testState = vi.hoisted(() => ({
  openConversation: vi.fn(),
  send: vi.fn(),
  copy: vi.fn(),
  canSendRefs: [] as Array<any>,
  messages: [] as any[],
}))

vi.mock('@/composables/useConversationsList', async () => {
  const { computed, ref } = await import('vue')
  return {
    useConversationsList: (props: any) => ({
      selectedChat: ref(null),
      selectedId: ref(null),
      chatLoading: ref(false),
      formattedConversations: computed(() => props.conversations.map((conv: any) => ({
        ...conv,
        timeAgo: 'now',
        message_type: conv.attributes?.message_type || 'text',
      }))),
      loadChatDetail: testState.openConversation,
      unreadMessages: {},
      clearUnread: vi.fn(),
    }),
  }
})

vi.mock('@/composables/useBreakpoint', async () => {
  const { ref } = await import('vue')
  return { useBreakpoint: () => ({ isMobile: ref(false) }) }
})

vi.mock('@/utils/chatState', () => ({
  chatHandler: () => ({ kind: 'ai', label: 'AI' }),
}))

vi.mock('@/composables/useConversationChat', async () => {
  const { ref } = await import('vue')
  return {
    useConversationChat: () => {
      const canSendMessage = ref(true)
      testState.canSendRefs.push(canSendMessage)
      return {
        newMessage: ref(''),
        messagesContainer: ref(null),
        formattedMessages: ref(testState.messages),
        isLoading: ref(false),
        showTakeoverButton: ref(false),
        showTakenOverStatus: ref(false),
        isChatClosed: ref(false),
        canSendMessage,
        scrollToBottom: vi.fn().mockResolvedValue(undefined),
        sendMessage: vi.fn(),
        handleTakeover: vi.fn(),
        handleRouteToHuman: vi.fn(),
        isWaitingForHuman: ref(false),
        handlerCaption: ref('Sending is unavailable for this conversation'),
        updateChat: vi.fn(),
        replaceChatFromProps: vi.fn(),
        handledByAI: ref(false),
        endChat: vi.fn(),
        templateCanReopen: ref(false),
        clearTemplateSuggestion: vi.fn(),
      }
    },
  }
})

vi.mock('@/composables/useConversationFiles', async () => {
  const { ref } = await import('vue')
  return {
    useConversationFiles: () => ({
      fileUploadRef: ref(null),
      uploadedFiles: ref([]),
      existingAttachmentIds: ref<number[]>([]),
      adoptExistingAttachment: vi.fn(),
      handleFilesUploaded: vi.fn(),
      handleFileUploadError: vi.fn(),
      handleChatPaste: vi.fn(),
      handleSendMessageWithAttachments: testState.send,
      formatFileSize: (n: number) => String(n),
      isImageAttachment: (type: string) => type.startsWith('image/'),
      isAudioAttachment: (type: string) => type.startsWith('audio/'),
      isVideoAttachment: (type: string) => type.startsWith('video/'),
      getDownloadUrl: (url: string) => `https://files.test${url}`,
      getImageUrl: (url: string) => `https://files.test${url}`,
    }),
  }
})

vi.mock('@/composables/useVisualViewport', () => ({ useVisualViewport: () => ({}) }))
vi.mock('@/composables/useJiraTicket', async () => {
  const { ref } = await import('vue')
  return {
    useJiraTicket: () => ({
      jiraConnected: ref(false),
      checkJiraStatus: vi.fn().mockResolvedValue(undefined),
    }),
  }
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

const conversation: any = {
  customer: {
    id: 'customer-1',
    email: 'anna@example.test',
    full_name: 'Anna',
    profile: { city: 'Berlin' },
  },
  agent: { id: 'agent-1', name: 'Agent', display_name: null },
  last_message: 'Hallo',
  updated_at: '2026-10-07T00:00:00Z',
  message_count: 3,
  session_id: 'session-1',
  user_id: 'user-1',
  user_name: 'Me',
  status: 'open',
  channel: 'messenger',
}

const chat: any = {
  customer: conversation.customer,
  agent: conversation.agent,
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

const chatStubs = {
  'font-awesome-icon': true,
  ChannelBadge: true,
  CustomerAvatar: true,
  FileUpload: true,
  JiraTicketModal: true,
  TicketCreateModal: true,
  WhatsAppTemplatePicker: true,
}

beforeEach(() => {
  testState.openConversation.mockReset().mockResolvedValue(undefined)
  testState.send.mockReset().mockResolvedValue(undefined)
  testState.copy.mockReset().mockResolvedValue(undefined)
  testState.canSendRefs.length = 0
  testState.messages.length = 0
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: testState.copy },
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Window124 / Window138 Conversation core interaction', () => {
  it('keeps the row on one open owner with Enter/Space parity and nested-menu isolation', async () => {
    const wrapper = mount(ConversationsList, {
      props: {
        conversations: [conversation],
        loading: false,
        error: '',
        statusFilter: 'open',
        hasMore: false,
        loadingMore: false,
        frozenYance: true,
      },
      global: {
        stubs: {
          ConversationChat: true,
          ChannelBadge: true,
          HandlerBadge: true,
          CustomerAvatar: true,
        },
      },
    })

    const row = wrapper.get('.conversation-item')
    expect(row.attributes('role')).toBe('button')
    expect(row.attributes('tabindex')).toBe('0')

    await row.trigger('keydown', { key: 'Enter' })
    await row.trigger('keydown', { key: ' ' })
    expect(testState.openConversation).toHaveBeenCalledTimes(2)
    expect(testState.openConversation).toHaveBeenNthCalledWith(1, 'session-1')
    expect(testState.openConversation).toHaveBeenNthCalledWith(2, 'session-1')

    await wrapper.get('[data-yance-contact-menu-button]').trigger('click')
    await nextTick()
    expect(testState.openConversation).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-yance-contact-menu-items]').exists()).toBe(true)
  })

  it('converges right-click on one accessible Headless UI menu and persists native contact actions', async () => {
    const updateInboxState = vi.spyOn(chatService, 'updateInboxState').mockResolvedValue({
      followed: true,
      archived: false,
      favourite: false,
      last_read_message_id: null,
    } as any)
    const wrapper = mount(ConversationsList, {
      props: {
        conversations: [conversation],
        loading: false,
        error: '',
        statusFilter: 'open',
        hasMore: false,
        loadingMore: false,
        frozenYance: true,
      },
      global: {
        stubs: {
          ConversationChat: true,
          ChannelBadge: true,
          HandlerBadge: true,
          CustomerAvatar: true,
        },
      },
    })
    const row = wrapper.get('.conversation-item')

    await row.trigger('contextmenu')
    await nextTick()
    const menu = wrapper.get('[data-yance-contact-menu-items]')
    expect(menu.attributes('role')).toBe('menu')
    expect(wrapper.get('[data-yance-contact-action="open"]').text()).toBe('打开')
    expect(wrapper.get('[data-yance-contact-action="details"]').text()).toBe('详情')
    const follow = wrapper.get('[data-yance-follow-action]')
    const archive = wrapper.get('[data-yance-archive-action]')
    expect(follow.attributes('disabled')).toBeUndefined()
    expect(archive.attributes('disabled')).toBeUndefined()
    expect(follow.attributes('data-native-state')).toBe('SessionToAgent.is_followed')
    expect(archive.attributes('data-native-state')).toBe('SessionToAgent.is_archived')
    expect(testState.openConversation).not.toHaveBeenCalled()

    await follow.trigger('click')
    await flushPromises()
    expect(updateInboxState).toHaveBeenCalledExactlyOnceWith('session-1', { followed: true })
    expect(wrapper.emitted('refresh')).toHaveLength(1)
    expect(testState.openConversation).not.toHaveBeenCalled()

    await row.trigger('contextmenu')
    await nextTick()
    await wrapper.get('[data-yance-archive-action]').trigger('click')
    await flushPromises()
    expect(updateInboxState).toHaveBeenNthCalledWith(2, 'session-1', { archived: true })
    expect(wrapper.emitted('refresh')).toHaveLength(2)
    expect(testState.openConversation).not.toHaveBeenCalled()

    updateInboxState.mockRejectedValueOnce(new Error('native owner unavailable'))
    await row.trigger('contextmenu')
    await nextTick()
    await wrapper.get('[data-yance-follow-action]').trigger('click')
    await flushPromises()
    expect(updateInboxState).toHaveBeenNthCalledWith(3, 'session-1', { followed: true })
    expect(wrapper.emitted('refresh')).toHaveLength(3)
    expect(wrapper.text()).toContain('操作未保存，请重试')
  })

  it('uses one row-local message action model for visible overflow, right-click, text and media', async () => {
    testState.messages.push({
      id: 41,
      message: 'canonical source text',
      message_type: 'user',
      timeAgo: 'now',
      attributes: {},
      attachments: [{
        id: 7,
        filename: 'clip.mp4',
        file_url: '/clip.mp4',
        file_size: 12,
        content_type: 'video/mp4',
      }],
    })

    const wrapper = mount(ConversationChat, {
      props: { chat, frozenYance: true },
      global: { stubs: chatStubs },
    })

    expect(wrapper.findAll('[data-yance-message-menu-button]')).toHaveLength(1)
    await wrapper.get('.message').trigger('contextmenu')
    await nextTick()

    expect(wrapper.find('[data-yance-message-menu-items]').exists()).toBe(true)
    const open = wrapper.get('[data-yance-message-action="open"]')
    const download = wrapper.get('[data-yance-message-action="download"]')
    expect(open.attributes('href')).toBe('https://files.test/clip.mp4')
    expect(download.attributes('href')).toBe('https://files.test/clip.mp4')
    expect(download.attributes('download')).toBe('clip.mp4')

    await wrapper.get('[data-yance-message-action="copy"]').trigger('click')
    await flushPromises()
    expect(testState.copy).toHaveBeenCalledWith('canonical source text')
  })

  it('sends only on deliberate non-composing Enter and keeps Shift+Enter / IME at zero sends', async () => {
    const wrapper = mount(ConversationChat, {
      props: { chat, frozenYance: true },
      global: { stubs: chatStubs },
    })
    const composer = wrapper.get('textarea.message-input')

    await composer.setValue('line one')
    await composer.trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(testState.send).not.toHaveBeenCalled()

    await composer.trigger('compositionstart')
    await composer.trigger('keydown', { key: 'Enter' })
    await composer.trigger('compositionend')
    await composer.trigger('keyup', { key: 'Enter' })
    expect(testState.send).not.toHaveBeenCalled()

    await composer.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(testState.send).toHaveBeenCalledTimes(1)
  })

  it('links unavailable Composer state programmatically and prevents Enter send while disabled', async () => {
    const wrapper = mount(ConversationChat, {
      props: { chat, frozenYance: true },
      global: { stubs: chatStubs },
    })
    const canSend = testState.canSendRefs[0]
    canSend.value = false
    await nextTick()

    const composer = wrapper.get('textarea.message-input')
    const describedBy = composer.attributes('aria-describedby')
    expect(describedBy).toContain('composer-unavailable-session-1')
    expect(wrapper.get('#composer-unavailable-session-1').attributes('role')).toBe('status')

    await composer.trigger('keydown', { key: 'Enter' })
    expect(testState.send).not.toHaveBeenCalled()
    expect(composer.attributes('aria-invalid')).toBeUndefined()
  })

  it('links inline TTS failure to the same Composer without false invalid state', async () => {
    const { voiceService } = await import('@/services/voice')
    vi.mocked(voiceService.generateSpeech).mockRejectedValueOnce(new Error('provider unavailable'))

    const wrapper = mount(ConversationChat, {
      props: { chat, frozenYance: true },
      global: { stubs: chatStubs },
    })
    const composer = wrapper.get('textarea.message-input')
    await composer.setValue('hello')
    await wrapper.get('.tts-button').trigger('click')
    await flushPromises()
    await nextTick()

    const describedBy = composer.attributes('aria-describedby')
    expect(describedBy).toContain('composer-tts-error-session-1')
    const error = wrapper.get('#composer-tts-error-session-1')
    expect(error.attributes('role')).toBe('status')
    expect(error.attributes('aria-live')).toBe('polite')
    expect(error.text()).toBe('Voice generation failed')
    expect(composer.attributes('aria-invalid')).toBeUndefined()
  })

  it('receives first drag on the always-mounted FileUpload root and sends first drop through the existing owner once', async () => {
    class ImmediateFileReader {
      result: string | null = null
      onload: ((event: any) => void) | null = null
      onerror: ((event: any) => void) | null = null

      readAsDataURL() {
        this.result = 'data:text/plain;base64,QQ=='
        queueMicrotask(() => this.onload?.({ target: this }))
      }
    }
    vi.stubGlobal('FileReader', ImmediateFileReader as any)

    const wrapper = mount(FileUpload)
    const root = wrapper.get('.file-upload-container')
    const file = new File(['A'], 'note.txt', { type: 'text/plain' })

    await root.trigger('dragenter', { dataTransfer: { files: [file] } })
    expect(wrapper.find('.drop-zone-overlay').exists()).toBe(true)

    await root.trigger('drop', { dataTransfer: { files: [file] } })
    await flushPromises()

    expect(wrapper.find('.drop-zone-overlay').exists()).toBe(false)
    const uploads = wrapper.emitted('filesUploaded') || []
    expect(uploads).toHaveLength(1)
    expect((uploads[0][0] as any[])[0]).toMatchObject({
      filename: 'note.txt',
      content_type: 'text/plain',
      size: 1,
    })
  })

  it('keeps the bounded source structure free of a second composer/action-state owner', () => {
    const chatSource = readFileSync(
      resolve(process.cwd(), 'src/components/conversations/ConversationChat.vue'),
      'utf8',
    )
    const listSource = readFileSync(
      resolve(process.cwd(), 'src/components/conversations/ConversationsList.vue'),
      'utf8',
    )
    const uploadSource = readFileSync(
      resolve(process.cwd(), 'src/components/common/FileUpload.vue'),
      'utf8',
    )

    expect(chatSource.match(/<textarea\b/g) || []).toHaveLength(1)
    expect(chatSource).not.toContain('@keyup.enter')
    expect(chatSource).toContain('@keydown="handleComposerKeydown"')
    expect(chatSource).toContain('event.isComposing')
    expect(chatSource).toContain('data-yance-message-action-menu')
    expect(chatSource).not.toMatch(/messageAction.*\[idx\]|idx.*messageAction/i)
    expect(listSource).toContain("from '@headlessui/vue'")
    expect(uploadSource).toContain('@dragenter="handleDragOver"')
    expect(uploadSource).toContain('@drop="handleDrop"')
  })
})
