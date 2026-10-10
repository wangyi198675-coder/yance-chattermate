import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { getRecentChats, listAccounts, push } = vi.hoisted(() => ({
  getRecentChats: vi.fn(),
  listAccounts: vi.fn(),
  push: vi.fn(),
}))

vi.mock('@/services/chat', () => ({
  chatService: { getRecentChats },
}))

vi.mock('@/services/channels', () => ({
  default: { listAccounts },
}))

vi.mock('@/composables/useConversationsList', () => ({
  useConversationsList: () => ({ unreadMessages: { 'session-1': 2 } }),
}))

vi.mock('@/services/user', () => ({
  userService: { getUserId: () => 'user-1' },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/layouts/DashboardLayout.vue', () => ({
  default: { template: '<div class="dashboard-stub"><slot /></div>' },
}))

vi.mock('@/components/common/ChannelBadge.vue', () => ({
  default: {
    props: ['channel'],
    template: '<span class="channel-stub">{{ channel }}</span>',
  },
}))

vi.mock('@/components/conversations/HandlerBadge.vue', () => ({
  default: { template: '<span class="handler-stub">handler</span>' },
}))

import YanceHomeNativeComposition from '../YanceHomeNativeComposition.vue'

function conversation(overrides: Record<string, unknown> = {}) {
  return {
    customer: {
      id: 'customer-1',
      email: 'hans@example.test',
      full_name: 'Hans Müller',
      profile: {
        city: 'Berlin',
        age: 43,
        age_precision: 'exact',
        occupation: 'Designer',
        avatar: { url: 'https://example.test/hans.jpg' },
      },
    },
    agent: {
      id: 'agent-1',
      name: 'Agent',
      display_name: 'Agent',
      ai_replies_enabled: true,
    },
    last_message: 'Bis später',
    updated_at: '2026-10-06T06:00:00Z',
    message_count: 12,
    session_id: 'session-1',
    user_id: null,
    status: 'open',
    channel: 'messenger',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  getRecentChats.mockResolvedValue([conversation()])
  listAccounts.mockResolvedValue([
    {
      id: 'messenger-1',
      channel_type: 'messenger',
      external_account_id: 'page-1',
      display_name: 'Facebook Page',
      is_active: true,
    },
  ])
})

describe('YanceHomeNativeComposition', () => {
  it('uses one native recent-chat query for Home instead of a second message/contact store', async () => {
    const wrapper = mount(YanceHomeNativeComposition)
    await flushPromises()
    expect(getRecentChats).toHaveBeenCalledTimes(1)
    expect(getRecentChats).toHaveBeenCalledWith({ limit: 12, status: 'all' })
    expect(wrapper.findAll('[data-native-conversation-projection]')).toHaveLength(1)
  })

  it('projects canonical customer profile fields and native unread state into Home', async () => {
    const wrapper = mount(YanceHomeNativeComposition)
    await flushPromises()
    expect(wrapper.text()).toContain('Hans Müller')
    expect(wrapper.text()).toContain('柏林 · 43岁 · Designer')
    expect(wrapper.text()).toContain('2 条未读')
    expect(wrapper.get('.home-avatar img').attributes('src')).toBe('https://example.test/hans.jpg')
  })

  it('routes continue-conversation back into the admitted native-hosted /yance Conversation', async () => {
    const wrapper = mount(YanceHomeNativeComposition)
    await flushPromises()
    const button = wrapper.findAll('button').find((candidate) => candidate.text() === '继续对话')
    expect(button).toBeTruthy()
    await button!.trigger('click')
    expect(push).toHaveBeenCalledWith({ path: '/yance', query: { session: 'session-1' } })
  })

  it('falls back to initials after a Home avatar image failure', async () => {
    const wrapper = mount(YanceHomeNativeComposition)
    await flushPromises()
    await wrapper.get('.home-avatar img').trigger('error')
    await flushPromises()
    expect(wrapper.find('.home-avatar img').exists()).toBe(false)
    expect(wrapper.get('.home-avatar').text().trim()).not.toBe('')
  })

  it('routes a person into Relationship World without replacing the People owner', async () => {
    const wrapper = mount(YanceHomeNativeComposition)
    await flushPromises()
    const button = wrapper.findAll('button').find((candidate) => candidate.text() === '关系资料')
    expect(button).toBeTruthy()
    await button!.trigger('click')
    expect(push).toHaveBeenCalledWith('/yance/relationship/customer-1')
  })

  it('shows factual unread attention while relationship-derived items stay unavailable', async () => {
    const wrapper = mount(YanceHomeNativeComposition)
    await flushPromises()
    const attention = wrapper.get('[data-home-attention]')
    expect(attention.text()).toContain('未读对话')
    expect(attention.text()).toContain('1')
    expect(attention.text()).toContain('重要日期')
    expect(attention.text()).toContain('关系提醒')
    expect(attention.text()).toContain('暂不可用')
    expect(attention.text()).not.toContain('开放事项 5')
  })

  it('uses channel-account truth for the exception carrier and deep-links diagnostics', async () => {
    listAccounts.mockResolvedValue([
      {
        id: 'messenger-1',
        channel_type: 'messenger',
        external_account_id: 'page-1',
        display_name: 'Facebook Page',
        is_active: false,
      },
    ])
    const wrapper = mount(YanceHomeNativeComposition)
    await flushPromises()
    const exceptions = wrapper.get('[data-home-runtime-exceptions]')
    expect(exceptions.text()).toContain('1 个平台账号当前未启用')
    expect(exceptions.text()).toContain('Facebook Page')
    await exceptions.get('button').trigger('click')
    expect(push).toHaveBeenCalledWith('/yance/platform-accounts')
  })

  it('fails closed when channel-account status cannot be read', async () => {
    listAccounts.mockRejectedValue(new Error('unavailable'))
    const wrapper = mount(YanceHomeNativeComposition)
    await flushPromises()
    expect(wrapper.get('[data-home-runtime-exceptions]').text()).toContain('暂时无法读取平台连接状态')
    expect(wrapper.text()).not.toContain('平台运行正常')
  })
})
