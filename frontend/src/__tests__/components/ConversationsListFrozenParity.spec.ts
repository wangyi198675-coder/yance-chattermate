import { describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import ConversationsList from '@/components/conversations/ConversationsList.vue'

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
      loadChatDetail: vi.fn(),
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
vi.mock('@/services/user', () => ({
  userService: { getUserId: () => 'user-1' },
}))

const conversation: any = {
  customer: {
    id: 'customer-1',
    email: 'anna@example.test',
    full_name: 'Anna',
    profile: { city: 'Berlin', age: 43, occupation: 'Designer' },
  },
  agent: { id: 'agent-1', name: 'Agent', display_name: null },
  last_message: 'Hallo aus Berlin',
  updated_at: '2026-10-07T00:00:00Z',
  message_count: 3,
  session_id: 'session-1',
  user_id: null,
  status: 'open',
  channel: 'messenger',
}

describe('ConversationsList Frozen parity', () => {
  it('renders the canonical zh-CN profile projection under the native contact row', () => {
    const wrapper = shallowMount(ConversationsList, {
      props: {
        conversations: [conversation],
        loading: false,
        error: '',
        statusFilter: 'open',
        hasMore: false,
        loadingMore: false,
        frozenYance: true,
      },
    })
    const line = wrapper.get('[data-yance-contact-profile-line]')
    expect(line.text()).toContain('柏林')
    expect(line.text()).toContain('43')
    expect(line.text()).toContain('Designer')
  })

  it('keeps source last-message primary and renders a secondary slot beneath it', () => {
    const wrapper = shallowMount(ConversationsList, {
      props: {
        conversations: [conversation],
        loading: false,
        error: '',
        statusFilter: 'open',
        hasMore: false,
        loadingMore: false,
        frozenYance: true,
      },
      slots: {
        'conversation-secondary': '<p data-test-rail-secondary>柏林你好</p>',
      },
    })
    expect(wrapper.get('.last-message').text()).toBe('Hallo aus Berlin')
    expect(wrapper.get('[data-test-rail-secondary]').text()).toBe('柏林你好')
  })
})
