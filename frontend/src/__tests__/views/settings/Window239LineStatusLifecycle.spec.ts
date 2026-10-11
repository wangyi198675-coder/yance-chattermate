import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { lineAccountState } from '@/utils/lineAccountState'

// Native provider/network operations and unrelated third-party integrations are
// isolated; the actual Yance and ChatterMate Vue components, LINE credential
// form, lifecycle handlers, readiness projection and DOM all execute here.
const channelFixture = vi.hoisted(() => ({ accounts: [] as any[] }))
vi.mock('@/services/channels', () => ({
  default: {
    listAccounts: vi.fn(() => Promise.resolve([...channelFixture.accounts])),
    disconnectLine: vi.fn(),
    connectLine: vi.fn(),
    setAccountAgent: vi.fn(),
  },
}))
vi.mock('@/services/agent', () => ({
  agentService: {
    getOrganizationAgents: vi.fn().mockResolvedValue([
      { id: 'agent-one', display_name: 'Assigned Agent' },
    ]),
  },
}))
vi.mock('vue-sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('@/services/jira', () => ({
  checkJiraConnection: vi.fn().mockResolvedValue({ connected: false }),
  getJiraAuthUrl: vi.fn().mockReturnValue('/jira/auth'),
  disconnectJira: vi.fn(),
}))
vi.mock('@/services/shopify', () => ({
  checkShopifyConnection: vi.fn().mockResolvedValue({ connected: false }),
  getShopifyShops: vi.fn().mockResolvedValue([]),
}))
vi.mock('@/services/crm', () => ({
  default: {
    listConnections: vi.fn().mockResolvedValue([]),
  },
}))
vi.mock('@/composables/useTheme', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return { useTheme: () => ({ mode: ref('system'), setTheme: vi.fn() }) }
})
vi.mock('@/composables/useAISetup', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return {
    useAISetup: () => ({
      isLoading: ref(false),
      error: ref(''),
      setupConfig: ref({ provider: '', model: '' }),
      providers: ref([]),
      hasExistingConfig: ref(false),
    }),
  }
})
vi.mock('@/composables/useNotificationSettings', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return {
    useNotificationSettings: () => ({
      settings: ref(null),
      isLoading: ref(false),
      error: ref(null),
    }),
  }
})
vi.mock('@/services/translation', () => ({
  translationService: {
    health: vi.fn().mockResolvedValue({ state: 'not_configured' }),
  },
}))
vi.mock('@/config/api', () => ({ getApiUrl: () => 'http://api.test/api/v1' }))
vi.mock('@/layouts/DashboardLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-router')>(),
  RouterLink: {
    props: ['to'],
    template: '<a :data-to="to"><slot /></a>',
  },
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

import channelsService from '@/services/channels'
import { toast } from 'vue-sonner'
import IntegrationsSettings from '@/views/settings/IntegrationsSettings.vue'
import YanceSettingsNativeComposition from '@/yance/YanceSettingsNativeComposition.vue'

const line = (
  id: string,
  is_active: boolean,
  provider_health?: Record<string, unknown>,
) => ({
  id,
  channel_type: 'line',
  is_active,
  external_account_id: id,
  display_name: `LINE ${id}`,
  ...(provider_health ? { provider_health } : {}),
})

const ready = {
  readiness: 'READY',
  reconnect_needed: false,
  last_provider_error: null,
}

async function renderLineCard(accounts: any[]) {
  channelFixture.accounts = accounts
  const wrapper = mount(YanceSettingsNativeComposition)
  await flushPromises()
  const card = wrapper.get('[data-platform="line"]')
  const snapshot = {
    label: card.get('.state-badge').text(),
    className: card.get('.state-badge').classes(),
    detail: card.text(),
    managementLink: wrapper.get('.section-actions .primary-action').attributes('data-to'),
  }
  wrapper.unmount()
  return snapshot
}

beforeEach(() => {
  vi.mocked(channelsService.disconnectLine).mockReset()
  vi.mocked(channelsService.disconnectLine).mockResolvedValue(undefined)
  vi.mocked(channelsService.connectLine).mockReset()
  vi.mocked(channelsService.setAccountAgent).mockReset()
  vi.mocked(toast.success).mockClear()
  vi.mocked(toast.error).mockClear()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ status: 'healthy', version: 'test' }),
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Window239 LINE native ChannelAccount status and per-account UI', () => {
  it('never reports inactive-only accounts as connected', () => {
    expect(lineAccountState([{ is_active: false }])).toEqual({
      connected: false,
      needsAttention: true,
      inactiveCount: 1,
    })
    expect(lineAccountState([])).toEqual({
      connected: false,
      needsAttention: false,
      inactiveCount: 0,
    })
  })

  it('never upgrades active-but-unverified LINE accounts to Connected, including mixed siblings', () => {
    expect(lineAccountState([{ is_active: true }, { is_active: false }])).toEqual({
      connected: false,
      needsAttention: true,
      inactiveCount: 2,
    })
    expect(lineAccountState([{ is_active: true }, { is_active: true }])).toEqual({
      connected: false,
      needsAttention: true,
      inactiveCount: 2,
    })
    expect(lineAccountState([{ is_active: true }])).toEqual({
      connected: false,
      needsAttention: true,
      inactiveCount: 1,
    })
  })

  it('recognizes only verified READY LINE accounts and flags unverified siblings independently', () => {
    expect(lineAccountState([{ is_active: true, provider_health: ready }])).toEqual({
      connected: true,
      needsAttention: false,
      inactiveCount: 0,
    })
    expect(lineAccountState([
      { is_active: true, provider_health: ready },
      { is_active: true },
    ])).toEqual({
      connected: true,
      needsAttention: true,
      inactiveCount: 1,
    })
    expect(lineAccountState([
      { is_active: true, provider_health: ready },
      { is_active: false, provider_health: ready },
    ])).toEqual({
      connected: true,
      needsAttention: true,
      inactiveCount: 1,
    })
    expect(lineAccountState([
      { is_active: true, provider_health: ready },
      { is_active: true, provider_health: ready },
    ])).toEqual({
      connected: true,
      needsAttention: false,
      inactiveCount: 0,
    })
  })

  it('projects native LINE accounts into actual Settings DOM without claiming unverified connectivity', async () => {
    const empty = await renderLineCard([])
    expect(empty.label).toBe('尚未配置')
    expect(empty.className).not.toContain('connected')
    expect(empty.managementLink).toBe('/yance/platform-accounts')

    const inactive = await renderLineCard([line('inactive', false)])
    expect(inactive.label).toBe('需要检查')
    expect(inactive.detail).toContain('1 个 LINE 账号需要处理')
    expect(inactive.className).not.toContain('connected')

    // Activation without current provider health is NOT proof of a working connection.
    const unverified = await renderLineCard([line('unverified', true)])
    expect(unverified.label).toBe('需要检查')
    expect(unverified.detail).toContain('LINE unverified')

    const degraded = await renderLineCard([line('degraded', true, {
      ...ready,
      readiness: 'DEGRADED',
    })])
    expect(degraded.label).toBe('需要检查')

    const reconnect = await renderLineCard([line('reconnect', true, {
      ...ready,
      reconnect_needed: true,
    })])
    expect(reconnect.label).toBe('需要检查')

    const failed = await renderLineCard([line('failed', true, {
      ...ready,
      last_provider_error: 'invalid token',
    })])
    expect(failed.label).toBe('需要检查')

    const connected = await renderLineCard([line('verified', true, ready)])
    expect(connected.label).toBe('已连接')
    expect(connected.className).toContain('connected')

    const mixed = await renderLineCard([
      line('verified', true, ready),
      line('inactive', false),
    ])
    expect(mixed.label).toBe('已连接')
    expect(mixed.detail).toContain('1 个 LINE 账号需要处理')
    expect(mixed.managementLink).toBe('/yance/platform-accounts')
  })
})

/**
 * Native ChatterMate integrations manager is a separate routed Vue surface:
 * the Yance Settings status tests above do not cover its interactions.
 * Stub only the external API/service boundaries and the modal content.
 * Leave IntegrationsSettings.vue and lineAccountState.ts unmodified.
 */
const lineModalStub = {
  props: ['channel', 'existingAccount'],
  emits: ['connected', 'close'],
  template: `<section data-native-line-modal :data-channel="channel"
    :data-account-id="existingAccount?.id || ''">
    <button data-native-line-save @click="$emit('connected')">Credential saved</button>
    <button data-native-line-close @click="$emit('close')">Close</button>
  </section>`,
}

async function mountNativeLineManager(accounts: any[], realCredentialModal = false) {
  channelFixture.accounts = accounts
  const wrapper = mount(IntegrationsSettings, {
    global: {
      stubs: {
        ChannelConnectModal: realCredentialModal ? false : lineModalStub,
        TelegramConnectModal: true,
        MetaChannelConnect: true,
        WhatsAppTemplateManager: true,
      },
    },
  })
  await flushPromises()
  const lineCard = () => wrapper.findAll('.integration-card')
    .find(card => card.find('.integration-name').text() === 'LINE')
  return { wrapper, lineCard }
}

describe('Window239 routed native ChatterMate IntegrationsSettings LINE lifecycle', () => {
  it('shows no account as not connected, and the real Connect control opens an empty LINE credential modal', async () => {
    const { wrapper, lineCard } = await mountNativeLineManager([])
    try {
      const card = lineCard()
      expect(card).toBeDefined()
      expect(card!.get('.status-badge').text()).toBe('Not connected')
      expect(card!.find('[data-line-account-list]').exists()).toBe(false)
      await card!.get('.int-btn-connect').trigger('click')
      expect(wrapper.get('[data-native-line-modal]').attributes('data-channel')).toBe('line')
      expect(wrapper.get('[data-native-line-modal]').attributes('data-account-id')).toBe('')
      expect(channelsService.disconnectLine).not.toHaveBeenCalled()
      await wrapper.get('[data-native-line-close]').trigger('click')
      expect(wrapper.find('[data-native-line-modal]').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('shows inactive LINE account as Needs attention with exact-account Manage and Add controls', async () => {
    const { wrapper, lineCard } = await mountNativeLineManager([line('inactive', false)])
    try {
      const card = lineCard()!
      expect(card.get('.status-badge').text()).toBe('Needs attention')
      const row = card.get('[data-line-account-id="inactive"]')
      expect(row.text()).toContain('Needs attention')
      await row.get('.int-btn-manage').trigger('click')
      expect(wrapper.get('[data-native-line-modal]').attributes('data-account-id')).toBe('inactive')
      await wrapper.get('[data-native-line-close]').trigger('click')
      await card.get('.line-account-list > .int-btn-connect').trigger('click')
      expect(wrapper.get('[data-native-line-modal]').attributes('data-account-id')).toBe('')
      expect(wrapper.get('[data-native-line-modal]').attributes('data-channel')).toBe('line')
    } finally {
      wrapper.unmount()
    }
  })

  it('fails closed on active-but-provider-unverified LINE in the real native integration CARD', async () => {
    const { wrapper, lineCard } = await mountNativeLineManager([line('unverified', true)])
    try {
      expect(lineCard()!.get('.status-badge').text()).toBe('Needs attention')
      expect(lineCard()!.find('.status-badge.connected').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('fails closed on active-but-provider-unverified LINE in the real native account ROW', async () => {
    const { wrapper, lineCard } = await mountNativeLineManager([line('unverified', true)])
    try {
      const row = lineCard()!.get('[data-line-account-id="unverified"]')
      expect(row.get('.line-account-identity small:last-child').text()).toBe('Needs attention')
    } finally {
      wrapper.unmount()
    }
  })

  it.each([
    ['provider-verified READY', ready, 'Connected'],
    ['provider-DEGRADED', { ...ready, readiness: 'DEGRADED' }, 'Needs attention'],
    ['reconnect-needed', { ...ready, reconnect_needed: true }, 'Needs attention'],
    ['provider-error', { ...ready, last_provider_error: 'expired' }, 'Needs attention'],
  ] as const)('projects native LINE %s truthfully at card and account row', async (_scenario, health, expected) => {
    const { wrapper, lineCard } = await mountNativeLineManager([line('state', true, health)])
    try {
      expect(lineCard()!.get('.status-badge').text()).toBe(expected)
      expect(lineCard()!.get('[data-line-account-id="state"] .line-account-identity small:last-child').text()).toBe(expected)
    } finally {
      wrapper.unmount()
    }
  })

  it('manages exact LINE identities, adds another channel and refreshes from native list after save', async () => {
    const first = line('first', true, ready)
    const sibling = line('sibling', false)
    const { wrapper, lineCard } = await mountNativeLineManager([first, sibling])
    try {
      expect(lineCard()!.findAll('.line-account-row')).toHaveLength(2)
      expect(lineCard()!.text()).toContain('1 LINE channel(s) need attention.')
      await lineCard()!.get('[data-line-account-id="sibling"] .int-btn-manage').trigger('click')
      expect(wrapper.get('[data-native-line-modal]').attributes('data-account-id')).toBe('sibling')
      await wrapper.get('[data-native-line-close]').trigger('click')

      await lineCard()!.get('.line-account-list > .int-btn-connect').trigger('click')
      expect(wrapper.get('[data-native-line-modal]').attributes('data-account-id')).toBe('')
      channelFixture.accounts = [first, sibling, line('added', true, ready)]
      const readsBefore = vi.mocked(channelsService.listAccounts).mock.calls.length
      await wrapper.get('[data-native-line-save]').trigger('click')
      await flushPromises()
      expect(channelsService.listAccounts).toHaveBeenCalledTimes(readsBefore + 1)
      expect(lineCard()!.findAll('.line-account-row')).toHaveLength(3)
      expect(lineCard()!.get('[data-line-account-id="added"]').text()).toContain('LINE added')
      expect(wrapper.find('[data-native-line-modal]').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('cancels without a native disconnect and then disconnects only selected LINE account after confirmation', async () => {
    const first = line('first', true, ready)
    const sibling = line('sibling', true, ready)
    const { wrapper, lineCard } = await mountNativeLineManager([first, sibling])
    try {
      await lineCard()!.get('[data-line-account-id="sibling"] .int-btn-disconnect').trigger('click')
      expect(wrapper.get('.disconnect-modal-body').text()).toContain('LINE sibling')
      expect(wrapper.get('.disconnect-modal-body').text()).toContain('Other LINE channels remain connected')
      expect(channelsService.disconnectLine).not.toHaveBeenCalled()
      await wrapper.get('.disconnect-modal .btn-cancel').trigger('click')
      expect(channelsService.disconnectLine).not.toHaveBeenCalled()

      vi.mocked(channelsService.disconnectLine).mockImplementationOnce(async (id: string) => {
        channelFixture.accounts = channelFixture.accounts.filter(account => account.id !== id)
      })
      await lineCard()!.get('[data-line-account-id="sibling"] .int-btn-disconnect').trigger('click')
      const readsBefore = vi.mocked(channelsService.listAccounts).mock.calls.length
      await wrapper.get('.disconnect-modal .btn-disconnect').trigger('click')
      await flushPromises()
      expect(channelsService.disconnectLine).toHaveBeenCalledExactlyOnceWith('sibling')
      expect(channelsService.listAccounts).toHaveBeenCalledTimes(readsBefore + 1)
      expect(lineCard()!.find('[data-line-account-id="sibling"]').exists()).toBe(false)
      expect(lineCard()!.find('[data-line-account-id="first"]').exists()).toBe(true)
      expect(toast.success).toHaveBeenCalledWith('Disconnected LINE channel LINE sibling')
      expect(wrapper.find('.disconnect-modal').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('surfaces failed native LINE disconnect with exact error and retains both accounts', async () => {
    const first = line('first', true, ready)
    const sibling = line('sibling', false)
    vi.mocked(channelsService.disconnectLine).mockRejectedValueOnce({
      response: { data: { detail: 'LINE provider denied disconnect' } },
    })
    const { wrapper, lineCard } = await mountNativeLineManager([first, sibling])
    try {
      await lineCard()!.get('[data-line-account-id="sibling"] .int-btn-disconnect').trigger('click')
      await wrapper.get('.disconnect-modal .btn-disconnect').trigger('click')
      await flushPromises()
      expect(channelsService.disconnectLine).toHaveBeenCalledExactlyOnceWith('sibling')
      expect(toast.error).toHaveBeenCalledWith('LINE provider denied disconnect')
      expect(toast.success).not.toHaveBeenCalled()
      expect(lineCard()!.findAll('.line-account-row')).toHaveLength(2)
      expect(lineCard()!.get('[data-line-account-id="sibling"]').exists()).toBe(true)
      expect(wrapper.find('.disconnect-modal').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })
})

describe('Window239 native LINE credential modal through routed IntegrationsSettings', () => {
  it('submits actual LINE credentials through connectLine, then manages exact saved account by setAccountAgent', async () => {
    const created = line('new-account', true, ready)
    vi.mocked(channelsService.connectLine).mockImplementationOnce(async (_credentials: any) => {
      channelFixture.accounts = [created]
      return created as any
    })
    vi.mocked(channelsService.setAccountAgent).mockImplementationOnce(async (id: string, agentId: string) => ({
      ...created,
      agent_id: agentId,
    } as any))
    const { wrapper, lineCard } = await mountNativeLineManager([], true)
    try {
      await lineCard()!.get('.int-btn-connect').trigger('click')
      expect(wrapper.get('.cc-modal-header h3').text()).toContain('连接 LINE')
      await wrapper.get('#cc-channel_secret').setValue('  actual-secret  ')
      await wrapper.get('#cc-channel_access_token').setValue('  actual-token  ')
      await wrapper.get('.cc-modal .cc-btn-primary').trigger('click')
      await flushPromises()

      expect(channelsService.connectLine).toHaveBeenCalledExactlyOnceWith({
        channel_secret: 'actual-secret',
        channel_access_token: 'actual-token',
      })
      expect(wrapper.get('.cc-modal .cc-intro').text()).toContain('消息收发仍需验证')
      await wrapper.get('.cc-modal .cc-btn-secondary').trigger('click')
      await flushPromises()
      expect(lineCard()!.get('[data-line-account-id="new-account"]').text()).toContain('LINE new-account')
      expect(wrapper.find('.cc-modal').exists()).toBe(false)

      await lineCard()!.get('[data-line-account-id="new-account"] .int-btn-manage').trigger('click')
      await flushPromises()
      expect(wrapper.get('.cc-modal-header h3').text()).toContain('管理 LINE')
      expect(wrapper.get('[data-no-duplicate-account]').text()).toContain('请勿重复创建账号')
      expect(wrapper.get('#cc-agent').element.tagName).toBe('SELECT')
      await wrapper.get('.cc-modal .cc-btn-primary').trigger('click')
      await flushPromises()
      expect(channelsService.setAccountAgent).toHaveBeenCalledExactlyOnceWith('new-account', 'agent-one')
      expect(channelsService.connectLine).toHaveBeenCalledTimes(1)
      expect(wrapper.find('.cc-modal').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('shows real credential submission error without falsely saving or creating an account', async () => {
    vi.mocked(channelsService.connectLine).mockRejectedValueOnce({
      response: { data: { detail: 'LINE credential was rejected' } },
    })
    const { wrapper, lineCard } = await mountNativeLineManager([], true)
    try {
      await lineCard()!.get('.int-btn-connect').trigger('click')
      await wrapper.get('#cc-channel_secret').setValue('secret')
      await wrapper.get('#cc-channel_access_token').setValue('invalid')
      await wrapper.get('.cc-modal .cc-btn-primary').trigger('click')
      await flushPromises()
      expect(channelsService.connectLine).toHaveBeenCalledExactlyOnceWith({
        channel_secret: 'secret',
        channel_access_token: 'invalid',
      })
      expect(toast.error).toHaveBeenCalledWith('连接失败：LINE credential was rejected')
      expect(toast.success).not.toHaveBeenCalled()
      expect(wrapper.find('.cc-modal').exists()).toBe(true)
      expect(lineCard()!.findAll('.line-account-row')).toHaveLength(0)
      expect(channelsService.setAccountAgent).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
    }
  })
})
