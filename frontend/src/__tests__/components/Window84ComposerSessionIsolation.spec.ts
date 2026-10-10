import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ConversationChat from '@/components/conversations/ConversationChat.vue'
import FileUpload from '@/components/common/FileUpload.vue'

const testState = vi.hoisted(() => ({
  sendCalls: [] as Array<{sessionId: string; text: string; files: any[]; attachmentIds: number[]}>,
  chatInstances: [] as Array<any>,
  fileInstances: [] as Array<any>,
  ttsSpy: vi.fn(),
}))

vi.mock('@/composables/useConversationChat', async () => {
  const { ref } = await import('vue')
  return {
    useConversationChat: (initialChat: any) => {
      const newMessage = ref('')
      const instance = { newMessage, initialSessionId: initialChat.session_id }
      testState.chatInstances.push(instance)
      return {
        newMessage,
        messagesContainer: ref(null),
        formattedMessages: ref([]),
        isLoading: ref(false),
        showTakeoverButton: ref(false),
        showTakenOverStatus: ref(false),
        isChatClosed: ref(false),
        canSendMessage: ref(true),
        scrollToBottom: vi.fn().mockResolvedValue(undefined),
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
      }
    },
  }
})

vi.mock('@/composables/useConversationFiles', async () => {
  const { ref } = await import('vue')
  return {
    useConversationFiles: (currentChat: any, newMessage: any) => {
      const uploadedFiles = ref<any[]>([])
      const existingAttachmentIds = ref<number[]>([])
      const instance = { currentChat, newMessage, uploadedFiles, existingAttachmentIds }
      testState.fileInstances.push(instance)
      return {
        fileUploadRef: ref(null),
        uploadedFiles,
        existingAttachmentIds,
        adoptExistingAttachment: (id: number) => {
          if (!existingAttachmentIds.value.includes(id)) existingAttachmentIds.value.push(id)
        },
        handleFilesUploaded: (files: any[]) => { uploadedFiles.value = files },
        handleFileUploadError: vi.fn(),
        handleChatPaste: vi.fn(),
        handleSendMessageWithAttachments: vi.fn(async () => {
          testState.sendCalls.push({
            sessionId: currentChat.value.session_id,
            text: newMessage.value,
            files: uploadedFiles.value.map((file: any) => ({ ...file })),
            attachmentIds: [...existingAttachmentIds.value],
          })
          newMessage.value = ''
          uploadedFiles.value = []
          existingAttachmentIds.value = []
        }),
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

vi.mock('@/composables/useVisualViewport', () => ({ useVisualViewport: () => ({}) }))
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
  voiceService: { generateSpeech: testState.ttsSpy },
}))

const chatA: any = {
  customer: { id: 'customer-a', email: 'a@example.test', full_name: 'A', profile: null },
  agent: { id: 'agent-1', name: 'Agent', display_name: null },
  session_id: 'session-a',
  messages: [],
  created_at: '2026-10-07T00:00:00Z',
  updated_at: '2026-10-07T00:00:00Z',
  user_id: 'user-1',
  user_name: 'Me',
  group_id: null,
  status: 'open',
  channel: 'messenger',
}

const chatB: any = {
  ...chatA,
  customer: { id: 'customer-b', email: 'b@example.test', full_name: 'B', profile: null },
  session_id: 'session-b',
}

function mountKeyedConversation(initialChat = chatA) {
  const activeChat = ref<any>(initialChat)
  const Harness = defineComponent({
    setup() {
      return () => h(ConversationChat, {
        key: activeChat.value.session_id,
        chat: activeChat.value,
        frozenYance: true,
      }, {
        'conversation-extension': (slotProps: any) => [
          h('button', {
            'data-test-adopt-attachment': '',
            onClick: () => slotProps.adoptAttachment(501),
          }, 'adopt attachment'),
          h('button', {
            'data-test-adopt-intent': '',
            onClick: () => slotProps.adoptMediaIntent({
              type: 'video',
              label: 'A generated video',
              prompt: 'prompt-a',
              runtimeState: 'runtime-pending',
            }),
          }, 'adopt intent'),
        ],
      })
    },
  })

  const wrapper = mount(Harness, {
    global: {
      stubs: {
        'font-awesome-icon': true,
        ChannelBadge: true,
        CustomerAvatar: true,
        FileUpload: true,
        JiraTicketModal: true,
        TicketCreateModal: true,
        WhatsAppTemplatePicker: true,
      },
    },
  })
  return { wrapper, activeChat }
}

beforeEach(() => {
  testState.sendCalls.length = 0
  testState.chatInstances.length = 0
  testState.fileInstances.length = 0
  testState.ttsSpy.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Window84 composer session isolation', () => {
  it('uses canonical session_id to key the sole production ConversationChat host', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/conversations/ConversationsList.vue'), 'utf8')
    expect(source).toContain(':key="selectedChat.session_id"')
  })

  it('clears A text on A→B and B send payload cannot contain A text', async () => {
    const { wrapper, activeChat } = mountKeyedConversation()
    await wrapper.get('textarea.message-input').setValue('draft-for-A')

    activeChat.value = chatB
    await nextTick()

    expect(wrapper.get('textarea.message-input').element).toHaveProperty('value', '')
    await wrapper.get('textarea.message-input').setValue('reply-for-B')
    await wrapper.get('[data-yance-final-send]').trigger('click')

    expect(testState.sendCalls).toEqual([{
      sessionId: 'session-b',
      text: 'reply-for-B',
      files: [],
      attachmentIds: [],
    }])
  })

  it('drops A ordinary files and adopted FileAttachment IDs before B can send', async () => {
    const { wrapper, activeChat } = mountKeyedConversation()
    const aFiles = testState.fileInstances[0]
    aFiles.uploadedFiles.value = [{
      content: 'QQ==',
      filename: 'a.txt',
      content_type: 'text/plain',
      size: 1,
    }]
    await wrapper.get('[data-test-adopt-attachment]').trigger('click')
    expect(aFiles.existingAttachmentIds.value).toEqual([501])

    activeChat.value = chatB
    await nextTick()

    const bFiles = testState.fileInstances[1]
    expect(bFiles.uploadedFiles.value).toEqual([])
    expect(bFiles.existingAttachmentIds.value).toEqual([])

    await wrapper.get('textarea.message-input').setValue('B only')
    await wrapper.get('[data-yance-final-send]').trigger('click')
    expect(testState.sendCalls[0]).toMatchObject({
      sessionId: 'session-b',
      text: 'B only',
      files: [],
      attachmentIds: [],
    })
  })

  it('does not carry A Reply Brain generation intent into B', async () => {
    const { wrapper, activeChat } = mountKeyedConversation()
    await wrapper.get('[data-test-adopt-intent]').trigger('click')
    expect(wrapper.find('[data-yance-adopted-media-intent]').exists()).toBe(true)

    activeChat.value = chatB
    await nextTick()

    expect(wrapper.find('[data-yance-adopted-media-intent]').exists()).toBe(false)
  })

  it('rejects late A TTS completion from B composer state', async () => {
    let resolveTts!: (value: any) => void
    testState.ttsSpy.mockImplementation(() => new Promise(resolve => { resolveTts = resolve }))

    const { wrapper, activeChat } = mountKeyedConversation()
    await wrapper.get('textarea.message-input').setValue('voice for A')
    await wrapper.get('.tts-button').trigger('click')

    activeChat.value = chatB
    await nextTick()
    await wrapper.get('textarea.message-input').setValue('typing in B')

    resolveTts({
      attachment: {
        id: 9001,
        file_url: '/api/v1/files/download/voice-a.mp3',
        filename: 'voice-a.mp3',
        content_type: 'audio/mpeg',
        file_size: 123,
      },
    })
    await Promise.resolve()
    await Promise.resolve()
    await nextTick()

    const bFiles = testState.fileInstances[1]
    expect(bFiles.existingAttachmentIds.value).toEqual([])
    expect(wrapper.get('textarea.message-input').element).toHaveProperty('value', 'typing in B')
    expect(wrapper.find('.tts-preview').exists()).toBe(false)
    expect(wrapper.get('.tts-button').attributes('aria-label')).toBe('Generate voice')
  })

  it('preserves normal typing/adopt/send when props refresh within the same session', async () => {
    const { wrapper, activeChat } = mountKeyedConversation()
    await wrapper.get('textarea.message-input').setValue('same-session draft')
    testState.fileInstances[0].uploadedFiles.value = [{
      content: 'Qg==',
      filename: 'same.txt',
      content_type: 'text/plain',
      size: 1,
    }]
    await wrapper.get('[data-test-adopt-attachment]').trigger('click')

    activeChat.value = { ...chatA, updated_at: '2026-10-07T00:01:00Z' }
    await nextTick()

    expect(testState.fileInstances).toHaveLength(1)
    expect(wrapper.get('textarea.message-input').element).toHaveProperty('value', 'same-session draft')
    expect(testState.fileInstances[0].existingAttachmentIds.value).toEqual([501])

    await wrapper.get('[data-yance-final-send]').trigger('click')
    expect(testState.sendCalls[0]).toMatchObject({
      sessionId: 'session-a',
      text: 'same-session draft',
      attachmentIds: [501],
    })
    expect(testState.sendCalls[0].files).toHaveLength(1)
  })
})

describe('Window84 FileUpload lifecycle isolation', () => {
  it('clearFiles revokes selected blob previews and emits an empty selection', () => {
    const revoke = vi.fn()
    const originalRevoke = (URL as any).revokeObjectURL
    ;(URL as any).revokeObjectURL = revoke

    const wrapper = mount(FileUpload)
    const vm = wrapper.vm as any
    vm.uploadedFiles.push({
      file: {} as File,
      content: 'QQ==',
      url: 'blob:preview-a',
      file_url: 'blob:preview-b',
      filename: 'a.png',
      type: 'image/png',
      size: 1,
    })

    vm.clearFiles()

    expect(vm.uploadedFiles).toEqual([])
    expect(revoke).toHaveBeenCalledWith('blob:preview-a')
    expect(revoke).toHaveBeenCalledWith('blob:preview-b')
    expect(wrapper.emitted('filesUploaded')?.at(-1)).toEqual([[]])

    wrapper.unmount()
    if (originalRevoke) (URL as any).revokeObjectURL = originalRevoke
    else delete (URL as any).revokeObjectURL
  })

  it('ignores an ordinary-file FileReader completion after clear/session disposal', async () => {
    const readers: any[] = []
    class DeferredFileReader {
      result: string | null = null
      onload: ((event: any) => void) | null = null
      onerror: ((event: any) => void) | null = null
      readAsDataURL() { readers.push(this) }
    }
    vi.stubGlobal('FileReader', DeferredFileReader as any)

    const wrapper = mount(FileUpload)
    const vm = wrapper.vm as any
    const file = {
      name: 'note.txt',
      type: 'text/plain',
      size: 1,
      slice: () => ({ arrayBuffer: async () => new Uint8Array([65]).buffer }),
    } as unknown as File
    const preventDefault = vi.fn()

    await vm.handlePaste({
      clipboardData: { items: [{ kind: 'file', getAsFile: () => file }] },
      preventDefault,
    })

    expect(preventDefault).toHaveBeenCalledTimes(1)
    expect(readers).toHaveLength(1)

    vm.clearFiles()
    readers[0].result = 'data:text/plain;base64,QQ=='
    readers[0].onload?.({ target: readers[0] })
    await nextTick()

    expect(vm.uploadedFiles).toEqual([])
    const emitted = wrapper.emitted('filesUploaded') || []
    expect(emitted).toEqual([[[]]])
  })
})
