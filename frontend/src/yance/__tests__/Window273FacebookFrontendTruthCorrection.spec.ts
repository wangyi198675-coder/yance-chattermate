import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  getAgents: vi.fn(),
  getConfig: vi.fn(),
  listPages: vi.fn(),
  connectPage: vi.fn(),
  businessLogin: vi.fn(),
}))

vi.mock('@/services/channels', () => ({
  default: {
    listAccounts: mocks.listAccounts,
    getEmbeddedSignupConfig: mocks.getConfig,
    listMessengerSignupPages: mocks.listPages,
    connectMessengerSignup: mocks.connectPage,
    setAccountAgent: vi.fn(),
  },
}))
vi.mock('@/services/agent', () => ({
  agentService: { getOrganizationAgents: mocks.getAgents },
}))
vi.mock('@/utils/metaSdk', () => ({
  runBusinessLogin: mocks.businessLogin,
  runInstagramLogin: vi.fn(),
  loadMetaSdk: vi.fn(),
  parseSignupMessage: vi.fn(),
  signupLoginOptions: vi.fn(),
  META_OAUTH_CALLBACK_PATH: '/auth/meta',
}))
vi.mock('vue-router', async importOriginal => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('vue-sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('@/services/jira', () => ({
  checkJiraConnection: vi.fn().mockResolvedValue({ connected: false }),
  getJiraAuthUrl: vi.fn(), disconnectJira: vi.fn(),
}))
vi.mock('@/services/shopify', () => ({
  checkShopifyConnection: vi.fn().mockResolvedValue({ connected: false }),
  getShopifyShops: vi.fn().mockResolvedValue([]),
}))
vi.mock('@/services/crm', () => ({
  default: { listConnections: vi.fn().mockResolvedValue([]) },
}))

import MetaChannelConnect from '@/components/integrations/MetaChannelConnect.vue'
import IntegrationsSettings from '@/views/settings/IntegrationsSettings.vue'

const page = (id: string, active: boolean) => ({
  id, channel_type: 'messenger' as const, external_account_id: id,
  display_name: 'Page ' + id, is_active: active, agent_id: undefined,
})
const modalStubs = { 'font-awesome-icon': true, MessengerPagePicker: true }
const settingsStubs = {
  DashboardLayout: { template: '<div><slot /></div>' },
  TelegramConnectModal: true,
  ChannelConnectModal: true,
  WhatsAppTemplateManager: true,
  'font-awesome-icon': true,
}
const messengerCard = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('.integration-card').find(c => c.find('.integration-name').text() === 'Messenger')!
const rows = (wrapper: ReturnType<typeof mount>) =>
  messengerCard(wrapper).findAll('.messenger-account-row')

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getAgents.mockResolvedValue([{ id: 'agent-1', name: 'Agent' }])
  mocks.getConfig.mockResolvedValue({
    enabled: true, app_id: 'meta-app', config_id: 'login-config', graph_version: 'v22.0',
  })
  mocks.businessLogin.mockResolvedValue('login-code')
  mocks.listPages.mockResolvedValue({
    signup_token: 'server-sealed-token',
    pages: [{ id: 'A', name: 'Page A' }],
  })
  mocks.listAccounts.mockResolvedValue([])
})

describe('W273 W272 Facebook subscription UI truth, source-executing', () => {
  it('DEFECT A: inactive Manage says Needs attention, offers exact-page reconnect, never agent Skip', async () => {
    mocks.connectPage.mockResolvedValue(page('A', true))
    const wrapper = shallowMount(MetaChannelConnect, {
      props: { channel: 'messenger', existingAccount: page('A', false) },
      global: { stubs: modalStubs },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Needs attention')
    expect(wrapper.text()).toContain('Reconnect Facebook Page')
    expect(wrapper.text()).not.toContain('Page A is connected.')
    expect(wrapper.text()).not.toContain('Skip for now')
    await wrapper.find('.meta-signup-btn').trigger('click')
    await flushPromises()
    expect(mocks.businessLogin).toHaveBeenCalledOnce()
    expect(mocks.connectPage).toHaveBeenCalledWith({
      signup_token: 'server-sealed-token', page_id: 'A',
    })
    expect(wrapper.emitted('account-updated')?.[0]?.[0]).toMatchObject({ id: 'A', is_active: true })
    expect(wrapper.text()).toContain('Page A is connected.')
    wrapper.unmount()
  })

  it('DEFECT B: actual failed re-subscribe deactivates only A; mounted Settings refreshes native rows', async () => {
    let serverRows = [page('A', true), page('B', true)]
    mocks.listAccounts.mockImplementation(async () => serverRows.map(p => ({ ...p })))
    mocks.connectPage.mockImplementation(async () => {
      serverRows = [page('A', false), page('B', true)]
      throw new Error('subscribe_app failed')
    })
    const wrapper = mount(IntegrationsSettings, { global: { stubs: settingsStubs } })
    await flushPromises()
    expect(rows(wrapper).map(r => r.find('.account-state').text())).toEqual(['Connected', 'Connected'])
    await rows(wrapper)[0].find('.account-action').trigger('click')
    await flushPromises()
    expect(wrapper.find('.meta-modal').text()).toContain('Page A is connected.')
    await wrapper.find('.meta-modal .meta-actions button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.meta-signup-btn').text()).toContain('Reconnect Facebook Page')
    await wrapper.find('.meta-signup-btn').trigger('click')
    await flushPromises()
    expect(mocks.connectPage).toHaveBeenCalledWith({
      signup_token: 'server-sealed-token', page_id: 'A',
    })
    expect(mocks.listAccounts.mock.calls.length).toBeGreaterThan(1)
    expect(rows(wrapper).map(r => r.find('.account-state').text())).toEqual(['Needs attention', 'Connected'])
    expect(wrapper.find('.meta-modal').text()).not.toContain('Page A is connected.')
    wrapper.unmount()
  })

  it('failure refresh outage: fail-closes exact A without degrading healthy B', async () => {
    let afterFailure = false
    mocks.listAccounts.mockImplementation(async () => {
      if (afterFailure) throw new Error('network unavailable')
      return [page('A', true), page('B', true)]
    })
    mocks.connectPage.mockImplementation(async () => {
      afterFailure = true
      throw new Error('subscribe_app failed')
    })
    const wrapper = mount(IntegrationsSettings, { global: { stubs: settingsStubs } })
    await flushPromises()
    await rows(wrapper)[0].find('.account-action').trigger('click')
    await flushPromises()
    await wrapper.find('.meta-modal .meta-actions button').trigger('click')
    await flushPromises()
    await wrapper.find('.meta-signup-btn').trigger('click')
    await flushPromises()
    expect(rows(wrapper).map(r => r.find('.account-state').text())).toEqual(['Needs attention', 'Connected'])
    wrapper.unmount()
  })

  it('reconnect must not silently connect a sibling Page when authorization excludes selected Page', async () => {
    mocks.listPages.mockResolvedValue({
      signup_token: 'server-sealed-token', pages: [{ id: 'B', name: 'Page B' }],
    })
    const wrapper = shallowMount(MetaChannelConnect, {
      props: { channel: 'messenger', existingAccount: page('A', false) },
      global: { stubs: modalStubs },
    })
    await flushPromises()
    await wrapper.find('.meta-signup-btn').trigger('click')
    await flushPromises()
    expect(mocks.connectPage).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Needs attention')
    wrapper.unmount()
  })

  it('initial zero/inactive/active/mixed native projections remain truthful', async () => {
    for (const [list, label, states] of [
      [[], 'Not configured', []],
      [[page('A', false)], 'Needs attention', ['Needs attention']],
      [[page('A', true)], 'Connected', ['Connected']],
      [[page('A', false), page('B', true)], 'Connected', ['Needs attention', 'Connected']],
    ] as const) {
      mocks.listAccounts.mockResolvedValueOnce(list)
      const wrapper = mount(IntegrationsSettings, { global: { stubs: { ...settingsStubs, MetaChannelConnect: true } } })
      await flushPromises()
      expect(messengerCard(wrapper).find('.status-badge').text()).toBe(label)
      expect(rows(wrapper).map(r => r.find('.account-state').text())).toEqual(states)
      wrapper.unmount()
    }
  })

  it('failed first-time Page subscription discovers staged inactive Page through native read', async () => {
    let serverRows: ReturnType<typeof page>[] = []
    mocks.listAccounts.mockImplementation(async () => serverRows.map(p => ({ ...p })))
    mocks.connectPage.mockImplementation(async () => {
      serverRows = [page('A', false)]
      throw new Error('subscribe_app failed')
    })
    const wrapper = mount(IntegrationsSettings, { global: { stubs: settingsStubs } })
    await flushPromises()
    await messengerCard(wrapper).find('[data-add-facebook-page]').trigger('click')
    await flushPromises()
    await wrapper.find('.meta-signup-btn').trigger('click')
    await flushPromises()
    expect(rows(wrapper).map(r => r.find('.account-state').text())).toEqual(['Needs attention'])
    wrapper.unmount()
  })
})


describe('W273 exact-account reconciliation and recovery lifecycle', () => {
  it('does not revive failed A from a stale active list response; healthy B stays Connected', async () => {
    mocks.listAccounts.mockResolvedValue([page('A', true), page('B', true)])
    mocks.connectPage.mockRejectedValue(new Error('subscribe_app failed'))
    const wrapper = mount(IntegrationsSettings, { global: { stubs: settingsStubs } })
    await flushPromises()
    await rows(wrapper)[0].find('.account-action').trigger('click')
    await flushPromises()
    await wrapper.find('.meta-modal .meta-actions button').trigger('click')
    await flushPromises()
    await wrapper.find('.meta-signup-btn').trigger('click')
    await flushPromises()
    expect(rows(wrapper).map(r => r.find('.account-state').text())).toEqual(['Needs attention', 'Connected'])
    wrapper.unmount()
  })

  it('after A subscription failure, reauthorization of the exact same Page restores A only after success', async () => {
    let serverRows = [page('A', true), page('B', true)]
    mocks.listAccounts.mockImplementation(async () => serverRows.map(p => ({ ...p })))
    mocks.connectPage.mockImplementationOnce(async () => {
      serverRows = [page('A', false), page('B', true)]
      throw new Error('subscribe_app failed')
    }).mockImplementationOnce(async () => {
      serverRows = [page('A', true), page('B', true)]
      return page('A', true)
    })
    const wrapper = mount(IntegrationsSettings, { global: { stubs: settingsStubs } })
    await flushPromises()
    await rows(wrapper)[0].find('.account-action').trigger('click')
    await flushPromises()
    await wrapper.find('.meta-modal .meta-actions button').trigger('click')
    await flushPromises()
    await wrapper.find('.meta-signup-btn').trigger('click')
    await flushPromises()
    expect(rows(wrapper).map(r => r.find('.account-state').text())).toEqual(['Needs attention', 'Connected'])
    await wrapper.find('.meta-signup-btn').trigger('click')
    await flushPromises()
    expect(mocks.connectPage).toHaveBeenCalledTimes(2)
    expect(mocks.connectPage.mock.calls[1][0].page_id).toBe('A')
    expect(rows(wrapper).map(r => r.find('.account-state').text())).toEqual(['Connected', 'Connected'])
    expect(wrapper.find('.meta-modal').text()).toContain('Page A is connected.')
    wrapper.unmount()
  })
})
