import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import ConversationsList from '@/components/conversations/ConversationsList.vue'

const updateInboxState = vi.fn()
vi.mock('@/services/chat', () => ({
  chatService: { updateInboxState: (...args: any[]) => updateInboxState(...args) },
}))
vi.mock('@/composables/useConversationsList', async () => {
  const { computed, ref, reactive } = await import('vue')
  return {
    useConversationsList: (props: any) => ({
      selectedChat: ref(null),
      selectedId: ref(null),
      chatLoading: ref(false),
      formattedConversations: computed(() => props.conversations.map((conv: any) => ({
        ...conv, timeAgo: 'now', message_type: 'text',
      }))),
      loadChatDetail: vi.fn(),
      unreadMessages: reactive(
        Object.fromEntries(props.conversations.map((conv: any) => [conv.session_id, conv.unread_count])),
      ),
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
  userService: { getUserId: () => 'user-a' },
}))

const menuContainer = { template: '<div><slot /></div>' }
const menuButton = { template: '<button type="button"><slot /></button>' }
const menuItem = { template: '<div><slot :active="false" /></div>' }
const record = (id: string, overrides: Record<string, unknown> = {}) => ({
  session_id: id, user_id: 'user-a',
  customer: { id, email: id + '@example.test', full_name: id },
  agent: { id: 'agent-a', name: 'Agent', display_name: null },
  last_message: 'Hallo', updated_at: '2026-10-08T00:00:00Z',
  message_count: 2, unread_count: 0, followed: false,
  favourite: false, archived: false, status: 'open', channel: 'messenger',
  ...overrides,
})
const render = (conversations: any[]) => mount(ConversationsList, {
  props: {
    conversations, loading: false, error: '', statusFilter: 'open',
    hasMore: false, loadingMore: false, frozenYance: true,
  },
  global: {
    stubs: {
      Menu: menuContainer, MenuButton: menuButton, MenuItems: menuContainer,
      MenuItem: menuItem, ConversationChat: true, CustomerAvatar: true,
      ChannelBadge: true, HandlerBadge: true,
    },
  },
})

describe('Window228 S07 canonical UI loop', () => {
  beforeEach(() => {
    updateInboxState.mockReset()
    updateInboxState.mockImplementation(async (_id: string, patch: any) => ({
      followed: false, favourite: false, archived: false,
      last_read_message_id: null, ...patch,
    }))
  })

  it('shows archive separately, permits unarchive, then rehydrates from server props', async () => {
    const wrapper = render([record('active'), record('archived', { archived: true })])
    expect(wrapper.findAll('.conversation-item')).toHaveLength(1)
    expect(wrapper.text()).toContain('active')
    await wrapper.get('[data-yance-archive-filter]').trigger('click')
    expect(wrapper.emitted('updateInboxFilter')?.[0]).toEqual(['archived'])
    expect(wrapper.findAll('.conversation-item')).toHaveLength(1)
    expect(wrapper.text()).toContain('archived')
    expect(wrapper.get('[data-yance-archive-action]').text()).toContain('取消归档')
    await wrapper.get('[data-yance-archive-action]').trigger('click')
    await flushPromises()
    expect(updateInboxState).toHaveBeenCalledWith('archived', { archived: false })
    expect(wrapper.emitted('refresh')).toBeTruthy()

    // Simulate a server refetch and a new window: the canonical owner, not a
    // stored tab/optimistic toggle, determines whether the row is archived.
    await wrapper.setProps({ conversations: [record('active'), record('archived')] })
    await nextTick()
    expect(wrapper.findAll('.conversation-item')).toHaveLength(0)
    wrapper.unmount()
    const restarted = render([record('active'), record('archived')])
    expect(restarted.findAll('.conversation-item')).toHaveLength(2)
  })

  it('writes favourite and follow to the one bounded inbox-state endpoint', async () => {
    const wrapper = render([record('first'), record('second')])
    await wrapper.findAll('[data-yance-favourite-action]')[0].trigger('click')
    await flushPromises()
    expect(updateInboxState).toHaveBeenCalledWith('first', { favourite: true })
    await wrapper.findAll('[data-yance-follow-action]')[0].trigger('click')
    await flushPromises()
    expect(updateInboxState).toHaveBeenCalledWith('first', { followed: true })

    await wrapper.setProps({
      conversations: [record('first', { favourite: true, followed: true }), record('second')],
    })
    await wrapper.get('[data-yance-favourite-filter]').trigger('click')
    expect(wrapper.findAll('.conversation-item')).toHaveLength(1)
    expect(wrapper.text()).toContain('first')
    await wrapper.get('[data-yance-follow-filter]').trigger('click')
    expect(wrapper.findAll('.conversation-item')).toHaveLength(1)
  })

  it('rehydrates the unread badge only from canonical server data after remount', async () => {
    const first = render([record('one', { unread_count: 2 }), record('two')])
    expect(first.get('.unread-bubble').text()).toBe('2')
    await first.findAll('.frozen-rail-tabs button')[1].trigger('click')
    expect(first.findAll('.conversation-item')).toHaveLength(1)
    first.unmount()
    const restarted = render([record('one', { unread_count: 0 }), record('two')])
    await restarted.findAll('.frozen-rail-tabs button')[1].trigger('click')
    expect(restarted.findAll('.conversation-item')).toHaveLength(0)
  })

  it('does not claim a failed write succeeded', async () => {
    updateInboxState.mockRejectedValueOnce(new Error('server unavailable'))
    const wrapper = render([record('first')])
    await wrapper.get('[data-yance-archive-action]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('未保存')
    expect(wrapper.findAll('.conversation-item')).toHaveLength(1)
    expect(wrapper.emitted('refresh')).toBeTruthy()
  })
})
