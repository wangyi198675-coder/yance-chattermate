import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  listAccounts: vi.fn(), getAgents: vi.fn(), getConfig: vi.fn(),
  listPages: vi.fn(), connectPage: vi.fn(), businessLogin: vi.fn(),
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
  runBusinessLogin: mocks.businessLogin, runInstagramLogin: vi.fn(),
  loadMetaSdk: vi.fn(), parseSignupMessage: vi.fn(),
  signupLoginOptions: vi.fn(), META_OAUTH_CALLBACK_PATH: '/auth/meta',
}))
vi.mock('vue-router', async importOriginal => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('vue-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))
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
import IntegrationsSettings from '@/views/settings/IntegrationsSettings.vue'
const page = (id: string, active: boolean) => ({
  id, channel_type: 'messenger' as const, external_account_id: id,
  display_name: 'Page ' + id, is_active: active, agent_id: undefined,
})
const settingsStubs = {
  DashboardLayout: { template: '<div><slot /></div>' },
  TelegramConnectModal: true, ChannelConnectModal: true,
  WhatsAppTemplateManager: true, 'font-awesome-icon': true,
}
const rows = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('.integration-card')
    .find(c => c.find('.integration-name').text() === 'Messenger')!
    .findAll('.messenger-account-row')
const states = (wrapper: ReturnType<typeof mount>) =>
  rows(wrapper).map(r => r.find('.account-state').text())

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getAgents.mockResolvedValue([{ id: 'agent-1', name: 'Agent' }])
  mocks.getConfig.mockResolvedValue({
    enabled: true, app_id: 'app', config_id: 'config', graph_version: 'v22.0',
  })
  mocks.businessLogin.mockResolvedValue('code')
  mocks.listPages.mockResolvedValue({
    signup_token: 'token', pages: [{ id: 'A', name: 'Page A' }],
  })
})

describe('W281 W277 stale failure refresh after exact-Page recovery regression', () => {
  it('a delayed old failure refresh must not demote a later successful exact-Page reconnect', async () => {
    let releaseOldRefresh!: (value: ReturnType<typeof page>[]) => void
    const oldRefresh = new Promise<ReturnType<typeof page>[]>(r => { releaseOldRefresh = r })
    mocks.listAccounts
      .mockResolvedValueOnce([page('A', true), page('B', true)])
      .mockImplementationOnce(() => oldRefresh)
      .mockResolvedValue([page('A', true), page('B', true)])
    mocks.connectPage
      .mockRejectedValueOnce(new Error('subscribe_app failed'))
      .mockResolvedValueOnce(page('A', true))

    const wrapper = mount(IntegrationsSettings, { global: { stubs: settingsStubs } })
    try {
      await flushPromises()
      expect(states(wrapper)).toEqual(['Connected', 'Connected'])
      await rows(wrapper)[0].find('.account-action').trigger('click')
      await flushPromises()
      await wrapper.find('.meta-modal .meta-actions button').trigger('click')
      await flushPromises()
      await wrapper.find('.meta-signup-btn').trigger('click')
      await flushPromises()
      expect(states(wrapper)).toEqual(['Needs attention', 'Connected'])
      expect(mocks.listAccounts).toHaveBeenCalledTimes(2)

      await wrapper.find('.meta-signup-btn').trigger('click')
      await flushPromises()
      expect(mocks.connectPage).toHaveBeenCalledTimes(2)
      expect(states(wrapper)).toEqual(['Connected', 'Connected'])

      releaseOldRefresh([page('A', true), page('B', true)])
      await flushPromises()
      expect(states(wrapper)).toEqual(['Connected', 'Connected'])
    } finally {
      wrapper.unmount()
    }
  })
})
