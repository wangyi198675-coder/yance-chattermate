import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { listPeople, getStats } = vi.hoisted(() => ({
  listPeople: vi.fn(),
  getStats: vi.fn(),
}))

vi.mock('@/services/people', () => ({
  peopleService: {
    listPeople,
    getStats,
  },
}))

vi.mock('@/composables/useEnterpriseFeatures', () => ({
  useEnterpriseFeatures: () => ({ hasEnterpriseModule: false }),
}))

vi.mock('@/utils/storage', () => ({
  subscriptionStorage: {
    hasFeature: () => true,
    isSubscriptionActive: () => true,
  },
}))

vi.mock('@/layouts/DashboardLayout.vue', () => ({
  default: { template: '<div class="dashboard-stub"><slot /></div>' },
}))

vi.mock('@/components/people/PersonDetailDrawer.vue', () => ({
  default: { template: '<div class="drawer-stub" />' },
}))

vi.mock('vue-sonner', () => ({
  toast: { error: vi.fn() },
}))

import PeopleView from '@/views/PeopleView.vue'

function person(avatar = 'https://example.test/hans.jpg') {
  return {
    id: 'customer-1',
    name: 'Hans Müller',
    email: 'hans@example.test',
    phone: null,
    is_anonymous: false,
    lead_stage: 'lead',
    qualified: true,
    source: { channel: 'messenger' },
    captured_at: null,
    last_activity: '2026-10-06T06:00:00Z',
    synced: false,
    profile: {
      city: 'Berlin',
      age: 43,
      age_precision: 'exact',
      occupation: 'Designer',
      avatar: avatar ? { url: avatar } : null,
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  getStats.mockResolvedValue({
    total_people: 1,
    anonymous: 0,
    new_leads_7d: 1,
    customers: 0,
    synced_to_crm: 0,
  })
})

describe('People native profile composition', () => {
  it('renders the bounded city age occupation line in the native People row', async () => {
    listPeople.mockResolvedValue({ items: [person()], total: 1, page: 1, page_size: 20 })
    const wrapper = mount(PeopleView)
    await flushPromises()
    expect(wrapper.get('.pv-profile-line').text()).toBe('柏林 · 43岁 · Designer')
  })

  it('uses the accepted avatar projection in the existing native avatar slot', async () => {
    listPeople.mockResolvedValue({ items: [person()], total: 1, page: 1, page_size: 20 })
    const wrapper = mount(PeopleView)
    await flushPromises()
    expect(wrapper.get('.pv-avatar img').attributes('src')).toBe('https://example.test/hans.jpg')
  })

  it('falls back to initials when the projected avatar image fails', async () => {
    listPeople.mockResolvedValue({ items: [person()], total: 1, page: 1, page_size: 20 })
    const wrapper = mount(PeopleView)
    await flushPromises()
    await wrapper.get('.pv-avatar img').trigger('error')
    await flushPromises()
    expect(wrapper.find('.pv-avatar img').exists()).toBe(false)
    expect(wrapper.get('.pv-avatar').text().trim()).not.toBe('')
  })

  it('falls back to initials when no avatar projection exists', async () => {
    listPeople.mockResolvedValue({ items: [person('')], total: 1, page: 1, page_size: 20 })
    const wrapper = mount(PeopleView)
    await flushPromises()
    expect(wrapper.find('.pv-avatar img').exists()).toBe(false)
    expect(wrapper.get('.pv-avatar').text().trim()).not.toBe('')
  })
})
