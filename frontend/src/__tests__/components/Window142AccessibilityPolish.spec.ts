import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'

const mocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  getNotifications: vi.fn(),
  markAsRead: vi.fn(),
  deleteNotification: vi.fn(),
  markAllAsRead: vi.fn(),
  clearAll: vi.fn(),
  getPerson: vi.fn(),
  getCrmStatus: vi.fn(),
  listActiveWhatsAppAccounts: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.routerPush }),
}))

vi.mock('@/services/notification', () => ({
  notificationService: {
    getNotifications: mocks.getNotifications,
    markAsRead: mocks.markAsRead,
    deleteNotification: mocks.deleteNotification,
    markAllAsRead: mocks.markAllAsRead,
    clearAll: mocks.clearAll,
  },
}))

vi.mock('@/services/people', () => ({
  peopleService: {
    getPerson: mocks.getPerson,
    getCrmStatus: mocks.getCrmStatus,
    updatePerson: vi.fn(),
    markAsCustomer: vi.fn(),
    syncToCrm: vi.fn(),
  },
}))

vi.mock('@/services/channels', () => ({
  default: { listActiveWhatsAppAccounts: mocks.listActiveWhatsAppAccounts },
}))

vi.mock('@/utils/permissions', () => ({
  permissionChecks: { canManagePeople: () => false },
}))

vi.mock('vue-sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('@/components/conversations/NewWhatsAppConversation.vue', () => ({
  default: { template: '<div class="whatsapp-stub" />' },
}))

vi.mock('@/composables/useEnterpriseFeatures', () => ({
  useEnterpriseFeatures: () => ({
    hasEnterpriseModule: true,
    moduleImports: { subscriptionStore: 'subscription-store' },
    loadModule: vi.fn().mockResolvedValue(null),
  }),
}))

vi.mock('@/utils/storage', () => ({
  useSubscriptionStorage: () => ({
    getCurrentSubscription: () => null,
    isSubscriptionActive: () => false,
    hasFeature: () => false,
    getAvailablePlans: () => [],
  }),
}))

vi.mock('@/composables/useAISetup', async () => {
  const { ref } = await import('vue')
  return {
    useAISetup: () => ({
      isLoading: ref(false),
      error: ref(''),
      providers: ref([]),
      setupConfig: ref({
        provider: '',
        model: '',
        apiKey: '',
        baseUrl: '',
      }),
      saveAISetup: vi.fn().mockResolvedValue(true),
      updateAISetup: vi.fn().mockResolvedValue(true),
      hasExistingConfig: ref(false),
    }),
  }
})

import NotificationList from '@/components/notifications/NotificationList.vue'
import PersonDetailDrawer from '@/components/people/PersonDetailDrawer.vue'
import AISetup from '@/components/ai/AISetup.vue'

const notifications = [
  {
    id: 1,
    type: 'chat_assigned',
    title: 'Conversation assigned',
    message: 'Open the conversation',
    notification_metadata: { session_id: 'session-1' },
    is_read: false,
    created_at: '2026-10-07T06:00:00Z',
  },
  {
    id: 2,
    type: 'system',
    title: 'System notice',
    message: 'No destination',
    is_read: true,
    created_at: '2026-10-07T06:00:00Z',
  },
]

const person = {
  id: 'customer-1',
  name: 'Anna',
  email: 'anna@example.test',
  phone: null,
  identified: true,
  is_anonymous: false,
  lead_stage: 'lead',
  qualified: false,
  source: null,
  created_at: '2026-01-01T00:00:00Z',
  lead_qualified_at: null,
  meta_data: {},
  profile: null,
  summary: null,
  captured_attributes: {},
  timeline: [],
  conversations: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getNotifications.mockResolvedValue(notifications.map((item) => ({ ...item })))
  mocks.markAsRead.mockResolvedValue(undefined)
  mocks.deleteNotification.mockResolvedValue(undefined)
  mocks.markAllAsRead.mockResolvedValue(undefined)
  mocks.clearAll.mockResolvedValue(undefined)
  mocks.getPerson.mockResolvedValue(person)
  mocks.getCrmStatus.mockResolvedValue({ connected_providers: [], synced: [] })
  mocks.listActiveWhatsAppAccounts.mockResolvedValue([])
})

describe('Window142 low-risk accessibility polish', () => {
  it('gives linkable notifications keyboard parity without overstating non-linkable rows', async () => {
    const wrapper = mount(NotificationList, { props: { isOpen: true } })
    await flushPromises()

    const rows = wrapper.findAll('.notification-item')
    expect(rows).toHaveLength(2)

    const linkable = rows[0]
    expect(linkable.attributes('role')).toBe('link')
    expect(linkable.attributes('tabindex')).toBe('0')
    expect(rows[1].attributes('role')).toBeUndefined()
    expect(rows[1].attributes('tabindex')).toBeUndefined()

    await linkable.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(mocks.markAsRead).toHaveBeenCalledWith(1)
    expect(mocks.routerPush).toHaveBeenCalledTimes(1)

    mocks.routerPush.mockClear()
    await linkable.trigger('keydown', { key: ' ' })
    await flushPromises()
    expect(mocks.routerPush).toHaveBeenCalledTimes(1)

    mocks.routerPush.mockClear()
    await linkable.get('.delete-notification').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(mocks.routerPush).not.toHaveBeenCalled()
  })

  it('names the notification region and exposes filter selected state', async () => {
    const wrapper = mount(NotificationList, { props: { isOpen: true } })
    await flushPromises()

    const drawer = wrapper.get('.notification-drawer')
    expect(drawer.attributes('role')).toBe('region')
    expect(drawer.attributes('aria-labelledby')).toBe('notification-drawer-title')
    expect(wrapper.get('#notification-drawer-title').text()).toBe('通知')
    expect(wrapper.get('.close-button').attributes('aria-label')).toBe('关闭通知')

    expect(wrapper.get('.refresh-button').attributes('title')).toBe('刷新通知')
    expect(wrapper.findAll('.mark-all').map(button => button.text())).toEqual(['全部标记为已读', '清空通知'])
    const filters = wrapper.findAll('.filter-tab')
    expect(filters[0].attributes('aria-pressed')).toBe('true')
    expect(filters[1].attributes('aria-pressed')).toBe('false')
    expect(filters.map(button => button.text())).toEqual(['全部', '未读'])
    await filters[1].trigger('click')
    expect(filters[0].attributes('aria-pressed')).toBe('false')
    expect(filters[1].attributes('aria-pressed')).toBe('true')
  })

  it('keeps native notification bulk actions operational under Chinese labels', async () => {
    const wrapper = mount(NotificationList, { props: { isOpen: true } })
    await flushPromises()
    await wrapper.findAll('.mark-all')[0]!.trigger('click')
    await flushPromises()
    expect(mocks.markAllAsRead).toHaveBeenCalledOnce()
    await wrapper.findAll('.mark-all')[1]!.trigger('click')
    await flushPromises()
    expect(mocks.clearAll).toHaveBeenCalledOnce()
    expect(wrapper.findAll('.notification-item')).toHaveLength(0)
  })

  it('names the existing person drawer without claiming modal semantics', async () => {
    const wrapper = mount(PersonDetailDrawer, {
      props: { customerId: 'customer-1' },
      global: { stubs: { 'font-awesome-icon': true } },
    })
    await flushPromises()

    const drawer = wrapper.get('aside.pdd')
    expect(drawer.attributes('aria-label')).toBe('Person details')
    expect(drawer.attributes('role')).toBeUndefined()
    expect(drawer.attributes('aria-modal')).toBeUndefined()
    expect(wrapper.get('.pdd-close').attributes('aria-label')).toBe('Close person details')
  })

  it('uses native AI setup buttons and preserves the locked custom activation path', async () => {
    const wrapper = mount(AISetup)
    await flushPromises()

    const tabs = wrapper.findAll('button.tab')
    expect(tabs).toHaveLength(2)
    expect(tabs[0].attributes('type')).toBe('button')
    expect(tabs[1].attributes('type')).toBe('button')
    expect(tabs[0].attributes('aria-pressed')).toBe('true')
    expect(tabs[1].attributes('aria-pressed')).toBe('false')
    expect(tabs[1].classes()).toContain('locked')
    expect(tabs[1].attributes('disabled')).toBeUndefined()

    await tabs[1].trigger('click')
    expect(tabs[0].attributes('aria-pressed')).toBe('false')
    expect(tabs[1].attributes('aria-pressed')).toBe('true')
  })

  it('has one global reduced-motion normalization contract', () => {
    const baseCss = readFileSync('src/assets/base.css', 'utf8')
    const matches = baseCss.match(/@media\s*\(prefers-reduced-motion:\s*reduce\)/g) ?? []
    expect(matches).toHaveLength(1)
    expect(baseCss).toContain('animation: none !important;')
    expect(baseCss).toContain('transition: none !important;')
    expect(baseCss).toContain('scroll-behavior: auto !important;')
  })
})
