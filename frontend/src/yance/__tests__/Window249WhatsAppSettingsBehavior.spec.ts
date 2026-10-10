import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { ChannelAccount } from '@/services/channels'
import IntegrationsSettings from '@/views/settings/IntegrationsSettings.vue'

const mocks = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  reconnectWhatsApp: vi.fn(),
  rotateWhatsAppCredentials: vi.fn(),
  disconnectWhatsApp: vi.fn(),
  toastError: vi.fn(),
}))
vi.mock('@/services/channels', () => ({
  default: {
    listAccounts: mocks.listAccounts,
    reconnectWhatsApp: mocks.reconnectWhatsApp,
    rotateWhatsAppCredentials: mocks.rotateWhatsAppCredentials,
    disconnectWhatsApp: mocks.disconnectWhatsApp,
  },
}))
vi.mock('@/services/jira', () => ({
  checkJiraConnection: vi.fn().mockResolvedValue({ connected: false }),
  getJiraAuthUrl: vi.fn(),
  disconnectJira: vi.fn(),
}))
vi.mock('@/services/shopify', () => ({
  checkShopifyConnection: vi.fn().mockResolvedValue({ connected: false }),
  getShopifyShops: vi.fn().mockResolvedValue([]),
}))
vi.mock('@/services/crm', () => ({
  default: { listConnections: vi.fn().mockResolvedValue([]) },
}))
vi.mock('vue-sonner', () => ({
  toast: { error: mocks.toastError, success: vi.fn(), info: vi.fn() },
}))
vi.mock('vue-router', async importOriginal => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

const healthy = (id: string): ChannelAccount => ({
  id, channel_type: 'whatsapp', external_account_id: `PN_${id}`,
  display_name: `Number ${id}`, is_active: true,
  provider_health: { readiness: 'READY', credential_status: 'VALID', reconnect_needed: false },
})
const attention = (id: string): ChannelAccount => ({
  ...healthy(id), is_active: false,
  provider_health: { readiness: 'ACTION_REQUIRED', credential_status: 'VALID', reconnect_needed: true },
})

const render = async (accounts: ChannelAccount[]) => {
  mocks.listAccounts.mockResolvedValue(accounts)
  const wrapper = mount(IntegrationsSettings, {
    global: {
      stubs: {
        DashboardLayout: { template: '<main><slot /></main>' },
        MetaChannelConnect: true,
        TelegramConnectModal: true,
        WhatsAppTemplateManager: true,
        ChannelConnectModal: true,
      },
    },
  })
  await flushPromises()
  const card = () => wrapper.findAll('.integration-card')
    .find(item => item.find('.integration-name').text() === 'WhatsApp')!
  return { wrapper, card }
}

describe('Window249 actual reactive WhatsApp Settings lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.reconnectWhatsApp.mockImplementation(async (id: string) => healthy(id))
    mocks.rotateWhatsAppCredentials.mockImplementation(async (id: string) => healthy(id))
    mocks.disconnectWhatsApp.mockResolvedValue(undefined)
  })

  it('zero numbers displays Not configured and Add number without claiming Connected', async () => {
    const { wrapper, card } = await render([])
    expect(card().find('.status-badge').text()).toBe('Not configured')
    expect(card().find('.int-btn-connect').text()).toBe('Add number')
    expect(card().findAll('.wa-account-row')).toHaveLength(0)
    wrapper.unmount()
  })

  it('one healthy number displays Connected', async () => {
    const { wrapper, card } = await render([healthy('A')])
    expect(card().find('.status-badge').text()).toBe('Connected')
    expect(card().findAll('.wa-account-row')).toHaveLength(1)
    expect(card().find('.wa-account-health').text()).toBe('Connected')
    expect(card().text()).toContain('Add number')
    wrapper.unmount()
  })

  it('inactive-only and registration ACTION_REQUIRED never claim Connected', async () => {
    const { wrapper, card } = await render([attention('A')])
    expect(card().find('.status-badge').text()).toBe('Needs attention')
    expect(card().find('.wa-account-health').text()).toContain('Needs attention')
    expect(card().text()).toContain('Add number')
    wrapper.unmount()
  })

  it('even active rows with ACTION_REQUIRED provider health do not count as usable', async () => {
    const failing = { ...attention('A'), is_active: true }
    const { wrapper, card } = await render([failing])
    expect(card().find('.status-badge').text()).toBe('Needs attention')
    wrapper.unmount()
  })

  it('active but degraded or registration-failed provider health remains Needs attention', async () => {
    const degraded = { ...healthy('A'),
      provider_health: { readiness: 'DEGRADED', credential_status: 'VALID' } }
    const registrationFailed = { ...healthy('B'),
      provider_health: { readiness: 'READY', phone_registration: 'ACTION_REQUIRED' } }
    const { wrapper, card } = await render([degraded, registrationFailed])
    expect(card().find('.status-badge').text()).toBe('Needs attention')
    expect(card().findAll('.wa-account-health').every(item =>
      item.text().includes('Needs attention'))).toBe(true)
    wrapper.unmount()
  })

  it('Manage selects the exact number, while Add number clears prior selection', async () => {
    const { wrapper, card } = await render([healthy('A'), healthy('B')])
    const manageB = card().findAll('.wa-account-row')[1]!.findAll('button')
      .find(button => button.text() === 'Manage')!
    await manageB.trigger('click')
    const modal = wrapper.findComponent({ name: 'MetaChannelConnect' })
    expect(modal.props('existingAccount')).toMatchObject({ id: 'B' })
    await card().find('.int-actions .int-btn-manage').trigger('click')
    expect(wrapper.findComponent({ name: 'MetaChannelConnect' })
      .props('existingAccount')).toBeNull()
    wrapper.unmount()
  })

  it('mixed numbers show aggregate Connected and inactive sibling Needs attention', async () => {
    const { wrapper, card } = await render([healthy('A'), attention('B')])
    expect(card().find('.status-badge').text()).toBe('Connected')
    const rows = card().findAll('.wa-account-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.find('.wa-account-health').text()).toBe('Connected')
    expect(rows[1]!.find('.wa-account-health').text()).toContain('Needs attention')
    wrapper.unmount()
  })

  it('a failed reconnect leaves failed account and healthy sibling untouched', async () => {
    mocks.reconnectWhatsApp.mockRejectedValueOnce(new Error('registration failed'))
    const { wrapper, card } = await render([attention('A'), healthy('B')])
    await card().findAll('.wa-account-row')[0]!.findAll('button')
      .find(button => button.text() === 'Reconnect')!.trigger('click')
    await flushPromises()
    expect(mocks.reconnectWhatsApp).toHaveBeenCalledExactlyOnceWith('A')
    expect(card().find('.status-badge').text()).toBe('Connected')
    expect(card().findAll('.wa-account-row')[0]!.find('.wa-account-health').text())
      .toContain('Needs attention')
    expect(card().findAll('.wa-account-row')[1]!.find('.wa-account-health').text())
      .toBe('Connected')
    expect(mocks.toastError).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('active READY A reconnect validation failure refreshes persisted inactive ACTION_REQUIRED A', async () => {
    mocks.reconnectWhatsApp.mockRejectedValueOnce(new Error('provider validation failed'))
    const { wrapper, card } = await render([healthy('A')])
    expect(card().find('.status-badge').text()).toBe('Connected')
    mocks.listAccounts.mockResolvedValueOnce([attention('A')])
    await card().find('.wa-account-row').findAll('button')
      .find(button => button.text() === 'Reconnect')!.trigger('click')
    await flushPromises()
    expect(mocks.reconnectWhatsApp).toHaveBeenCalledExactlyOnceWith('A')
    expect(mocks.listAccounts).toHaveBeenCalledTimes(2)
    expect(card().find('.status-badge').text()).toBe('Needs attention')
    expect(card().find('.wa-account-health').text()).toContain('Needs attention')
    expect(mocks.toastError).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('mixed READY A and B: failed A reads exact persisted A and B remains Connected', async () => {
    mocks.reconnectWhatsApp.mockRejectedValueOnce(new Error('registration failed'))
    const { wrapper, card } = await render([healthy('A'), healthy('B')])
    mocks.listAccounts.mockResolvedValueOnce([attention('A'), healthy('B')])
    await card().findAll('.wa-account-row')[0]!.findAll('button')
      .find(button => button.text() === 'Reconnect')!.trigger('click')
    await flushPromises()
    expect(mocks.reconnectWhatsApp).toHaveBeenCalledExactlyOnceWith('A')
    expect(card().find('.status-badge').text()).toBe('Connected')
    const rows = card().findAll('.wa-account-row')
    expect(rows[0]!.find('.wa-account-health').text()).toContain('Needs attention')
    expect(rows[1]!.find('.wa-account-health').text()).toBe('Connected')
    expect(rows[1]!.text()).toContain('Number B')
    wrapper.unmount()
  })

  it('reconnect rejection with unavailable refresh fails closed only the target', async () => {
    mocks.reconnectWhatsApp.mockRejectedValueOnce(new Error('provider validation failed'))
    const { wrapper, card } = await render([healthy('A'), healthy('B')])
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      mocks.listAccounts.mockRejectedValueOnce(new Error('account refresh offline'))
      await card().findAll('.wa-account-row')[0]!.findAll('button')
        .find(button => button.text() === 'Reconnect')!.trigger('click')
      await flushPromises()
      expect(card().find('.status-badge').text()).toBe('Connected')
      expect(card().findAll('.wa-account-health')[0]!.text()).toContain('Needs attention')
      expect(card().findAll('.wa-account-health')[1]!.text()).toBe('Connected')
      expect(mocks.disconnectWhatsApp).not.toHaveBeenCalled()
    } finally {
      errorSpy.mockRestore()
      wrapper.unmount()
    }
  })

  it('a stale READY account-list response cannot undo fail-closed failed reconnect', async () => {
    mocks.reconnectWhatsApp.mockRejectedValueOnce(new Error('provider validation failed'))
    const { wrapper, card } = await render([healthy('A')])
    // An earlier account-list snapshot can still say READY after the POST
    // has failed; only a successful reconnect may re-promote this UI row.
    mocks.listAccounts.mockResolvedValueOnce([healthy('A')])
    await card().find('.wa-account-row').findAll('button')
      .find(button => button.text() === 'Reconnect')!.trigger('click')
    await flushPromises()
    expect(card().find('.status-badge').text()).toBe('Needs attention')
    expect(card().find('.wa-account-health').text()).toContain('Needs attention')
    wrapper.unmount()
  })

  it('a missing exact target in refresh cannot promote it from a healthy sibling', async () => {
    mocks.reconnectWhatsApp.mockRejectedValueOnce(new Error('registration failed'))
    const { wrapper, card } = await render([healthy('A'), healthy('B')])
    mocks.listAccounts.mockResolvedValueOnce([healthy('B')])
    await card().findAll('.wa-account-row')[0]!.findAll('button')
      .find(button => button.text() === 'Reconnect')!.trigger('click')
    await flushPromises()
    expect(card().findAll('.wa-account-health')[0]!.text()).toContain('Needs attention')
    expect(card().findAll('.wa-account-health')[1]!.text()).toBe('Connected')
    expect(card().findAll('.wa-account-row')).toHaveLength(2)
    wrapper.unmount()
  })

  it('successfully reconnecting one failed number updates aggregate reactively', async () => {
    const { wrapper, card } = await render([attention('A')])
    expect(card().find('.status-badge').text()).toBe('Needs attention')
    await card().find('.wa-account-row').findAll('button')
      .find(button => button.text() === 'Reconnect')!.trigger('click')
    await flushPromises()
    expect(card().find('.status-badge').text()).toBe('Connected')
    expect(card().find('.wa-account-health').text()).toBe('Connected')
    wrapper.unmount()
  })

  it('removing only number A preserves number B and its Connected state', async () => {
    const { wrapper, card } = await render([healthy('A'), healthy('B')])
    await card().findAll('.wa-account-row')[0]!.find('.int-btn-disconnect').trigger('click')
    expect(wrapper.find('.disconnect-modal .disconnect-modal-body').text())
      .toContain('Number A')
    await wrapper.find('.disconnect-modal .btn-disconnect').trigger('click')
    await flushPromises()
    expect(mocks.disconnectWhatsApp).toHaveBeenCalledExactlyOnceWith('A')
    expect(card().findAll('.wa-account-row')).toHaveLength(1)
    expect(card().text()).toContain('Number B')
    expect(card().text()).not.toContain('Number A')
    expect(card().find('.status-badge').text()).toBe('Connected')
    wrapper.unmount()
  })

  it('rotation validation failure does not relabel the target or sibling', async () => {
    mocks.rotateWhatsAppCredentials.mockRejectedValueOnce(new Error('invalid'))
    const { wrapper, card } = await render([attention('A'), healthy('B')])
    await card().findAll('.wa-account-row')[0]!.findAll('button')
      .find(button => button.text() === 'Rotate token')!.trigger('click')
    await wrapper.find('input[name="whatsapp-rotation-token"]').setValue('invalid-test-token')
    await wrapper.find('.disconnect-modal .int-btn-manage').trigger('click')
    await flushPromises()
    expect(mocks.rotateWhatsAppCredentials).toHaveBeenCalledWith('A', {
      access_token: 'invalid-test-token',
    })
    expect(card().find('.status-badge').text()).toBe('Connected')
    expect(card().findAll('.wa-account-row')[0]!.find('.wa-account-health').text())
      .toContain('Needs attention')
    expect(card().findAll('.wa-account-row')[1]!.find('.wa-account-health').text())
      .toBe('Connected')
    wrapper.unmount()
  })
})
