import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MetaChannelConnect from '@/components/integrations/MetaChannelConnect.vue'

const native = vi.hoisted(() => ({
  getEmbeddedSignupConfig: vi.fn(),
  connectWhatsApp: vi.fn(),
  connectMessengerSignup: vi.fn(),
  listMessengerSignupPages: vi.fn(),
  runBusinessLogin: vi.fn(),
  getOrganizationAgents: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/services/channels', () => ({
  default: {
    getEmbeddedSignupConfig: native.getEmbeddedSignupConfig,
    connectWhatsApp: native.connectWhatsApp,
    connectMessengerSignup: native.connectMessengerSignup,
    listMessengerSignupPages: native.listMessengerSignupPages,
    setAccountAgent: vi.fn(),
  },
}))
vi.mock('@/services/agent', () => ({
  agentService: { getOrganizationAgents: native.getOrganizationAgents },
}))
vi.mock('@/utils/metaSdk', () => ({
  runBusinessLogin: native.runBusinessLogin,
  runInstagramLogin: vi.fn(),
  loadMetaSdk: vi.fn(),
  parseSignupMessage: vi.fn(),
  signupLoginOptions: vi.fn(),
  META_OAUTH_CALLBACK_PATH: '/auth/meta',
}))
vi.mock('vue-sonner', () => ({
  toast: { error: native.toastError, success: vi.fn() },
}))

const stubs = { 'font-awesome-icon': true }

beforeEach(() => {
  vi.clearAllMocks()
  native.getOrganizationAgents.mockResolvedValue([{ id: 'agent-1', name: '测试助手' }])
  native.getEmbeddedSignupConfig.mockResolvedValue({ enabled: false, app_id: '' })
  native.connectWhatsApp.mockResolvedValue({
    id: 'synthetic-wa', channel_type: 'whatsapp', display_name: '合成测试号码',
    is_active: true, external_account_id: 'synthetic-wa',
  })
})

describe('W361 W359 Chinese residual correction: native Meta owner unchanged', () => {
  it('WABA placeholder is Chinese, optional true; missing required values send zero POST', async () => {
    const wrapper = mount(MetaChannelConnect, {
      props: { channel: 'whatsapp' },
      global: { stubs },
    })
    await flushPromises()

    const waba = wrapper.get('#meta-waba_id')
    expect(waba.attributes('placeholder')).toBe('用于自动订阅 Webhook（选填）')
    expect(wrapper.text()).toContain('WhatsApp 商业账号 ID（选填）')
    await wrapper.get('.meta-actions .meta-btn-primary').trigger('click')
    await flushPromises()
    expect(native.connectWhatsApp).not.toHaveBeenCalled()

    await wrapper.get('#meta-phone_number_id').setValue('synthetic-phone')
    await wrapper.get('#meta-access_token').setValue('synthetic-token')
    await wrapper.get('.meta-actions .meta-btn-primary').trigger('click')
    await flushPromises()

    expect(native.connectWhatsApp).toHaveBeenCalledOnce()
    expect(native.connectWhatsApp).toHaveBeenCalledWith({
      phone_number_id: 'synthetic-phone', access_token: 'synthetic-token',
    })
    expect(native.connectWhatsApp.mock.calls[0][0]).not.toHaveProperty('waba_id')
    wrapper.unmount()
  })

  it('configured Messenger shows Chinese native Facebook Login for Business CTA and exact Page selection', async () => {
    native.getEmbeddedSignupConfig.mockResolvedValue({
      enabled: true, app_id: 'meta-test-app', config_id: 'business-config',
      graph_version: 'v22.0',
    })
    native.runBusinessLogin.mockResolvedValue('synthetic-code')
    native.listMessengerSignupPages.mockResolvedValue({
      signup_token: 'synthetic-signup-token',
      pages: [{ id: 'owned-page', name: '实际授权专页' }],
    })
    native.connectMessengerSignup.mockResolvedValue({
      id: 'native-row', channel_type: 'messenger',
      display_name: '实际授权专页', external_account_id: 'owned-page', is_active: true,
    })

    const wrapper = mount(MetaChannelConnect, {
      props: { channel: 'messenger' },
      global: { stubs },
    })
    await flushPromises()

    const login = wrapper.get('.meta-signup-btn')
    expect(login.text()).toContain('通过 Facebook 继续')
    expect(login.text()).not.toContain('Continue with Facebook')
    await login.trigger('click')
    await flushPromises()
    expect(native.runBusinessLogin).toHaveBeenCalledWith(
      expect.objectContaining({ appId: 'meta-test-app', configId: 'business-config' }),
    )
    expect(native.listMessengerSignupPages).toHaveBeenCalledWith(
      'synthetic-code', expect.stringContaining('/auth/meta'),
    )
    expect(native.connectMessengerSignup).toHaveBeenCalledWith({
      signup_token: 'synthetic-signup-token', page_id: 'owned-page',
    })
    expect(wrapper.emitted('account-updated')?.[0]?.[0]).toMatchObject({
      id: 'native-row', external_account_id: 'owned-page', is_active: true,
    })
    wrapper.unmount()
  })
})
