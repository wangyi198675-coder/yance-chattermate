import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { getPerson, getCrmStatus, listActiveWhatsAppAccounts } = vi.hoisted(() => ({
  getPerson: vi.fn(),
  getCrmStatus: vi.fn(),
  listActiveWhatsAppAccounts: vi.fn(),
}))

vi.mock('@/services/people', () => ({
  peopleService: {
    getPerson,
    getCrmStatus,
    updatePerson: vi.fn(),
    markAsCustomer: vi.fn(),
    syncToCrm: vi.fn(),
  },
}))

vi.mock('@/services/channels', () => ({
  default: { listActiveWhatsAppAccounts },
}))

vi.mock('@/utils/permissions', () => ({
  permissionChecks: { canManagePeople: () => false },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('vue-sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('@/components/conversations/NewWhatsAppConversation.vue', () => ({
  default: { template: '<div class="whatsapp-stub" />' },
}))

import PersonDetailDrawer from '@/components/people/PersonDetailDrawer.vue'

const detail = {
  id: 'customer-1',
  name: 'Anna',
  email: 'anna@example.test',
  phone: '+491234',
  identified: true,
  is_anonymous: false,
  lead_stage: 'lead',
  qualified: false,
  source: null,
  created_at: '2026-01-01T00:00:00Z',
  lead_qualified_at: null,
  meta_data: {
    person_profile: { city: 'Cuxhaven' },
    unrelated: 'preserved but not rendered as profile rows',
  },
  profile: {
    country: 'Germany',
    city: 'Cuxhaven',
    age: 43,
    age_precision: 'observed',
    occupation: 'Architect',
    avatar: { url: 'https://example.test/anna.jpg' },
  },
  summary: null,
  captured_attributes: {},
  timeline: [],
  conversations: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  getPerson.mockResolvedValue(detail)
  getCrmStatus.mockResolvedValue({ connected_providers: [], synced: [] })
  listActiveWhatsAppAccounts.mockResolvedValue([])
})

describe('PersonDetailDrawer profile composition', () => {
  it('composes bounded profile rows inside the existing native drawer', async () => {
    const wrapper = mount(PersonDetailDrawer, {
      props: { customerId: 'customer-1' },
      global: { stubs: { 'font-awesome-icon': true } },
    })
    await flushPromises()
    const projection = wrapper.get('[data-person-profile-projection]')
    expect(projection.text()).toContain('库克斯港')
    expect(projection.text()).toContain('43岁（记录）')
    expect(projection.text()).toContain('Architect')
    expect(projection.text()).not.toContain('unrelated')
  })

  it('uses the same avatar slot and falls back after image failure', async () => {
    const wrapper = mount(PersonDetailDrawer, {
      props: { customerId: 'customer-1' },
      global: { stubs: { 'font-awesome-icon': true } },
    })
    await flushPromises()
    expect(wrapper.get('.pdd-avatar img').attributes('src')).toBe('https://example.test/anna.jpg')
    await wrapper.get('.pdd-avatar img').trigger('error')
    await flushPromises()
    expect(wrapper.find('.pdd-avatar img').exists()).toBe(false)
    expect(wrapper.get('.pdd-avatar').text().trim()).not.toBe('')
  })
})
