import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { setTheme, listAccounts } = vi.hoisted(() => ({
  setTheme: vi.fn(),
  listAccounts: vi.fn().mockResolvedValue([
    {
      id: 'wa-1',
      channel_type: 'whatsapp',
      external_account_id: '15550001',
      display_name: 'Primary WhatsApp',
      is_active: true,
    },
    {
      id: 'msg-1',
      channel_type: 'messenger',
      external_account_id: 'page-1',
      display_name: 'Yance Test Page',
      is_active: true,
    },
    {
      id: 'tg-1',
      channel_type: 'telegram',
      external_account_id: 'bot-1',
      display_name: 'Yance Bot',
      is_active: false,
    },
  ]),
}))

vi.mock('@/composables/useTheme', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return {
    useTheme: () => ({
      mode: ref('dark'),
      setTheme,
    }),
  }
})

vi.mock('@/composables/useAISetup', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return {
    useAISetup: () => ({
      isLoading: ref(false),
      error: ref(''),
      setupConfig: ref({
        provider: 'openai',
        model: 'gpt-test',
        apiKey: '',
        baseUrl: '',
      }),
      hasExistingConfig: ref(true),
      providers: ref([]),
    }),
  }
})

vi.mock('@/composables/useNotificationSettings', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return {
    useNotificationSettings: () => ({
      settings: ref({
        notify_new_chat: true,
        notify_chat_transfer: true,
        notify_chat_assigned: false,
      }),
      isLoading: ref(false),
      isSaving: ref(false),
      error: ref(null),
      load: vi.fn(),
      save: vi.fn(),
    }),
  }
})

vi.mock('@/services/channels', () => ({
  default: {
    listAccounts,
  },
}))


vi.mock('@/services/translation', () => ({
  translationService: {
    health: vi.fn().mockResolvedValue({
      owner: 'deepl.official_translation_api',
      state: 'not_configured',
      stylePolicy: 'persona_chat_preserve_v1',
    }),
  },
}))

vi.mock('@/layouts/DashboardLayout.vue', () => ({
  default: { template: '<div class="dashboard-stub"><slot /></div>' },
}))

vi.mock('vue-router', () => ({
  RouterLink: {
    props: ['to'],
    template: '<a class="router-link-stub" :data-to="to"><slot /></a>',
  },
}))

import YanceSettingsNativeComposition from '../YanceSettingsNativeComposition.vue'

describe('YanceSettingsNativeComposition', () => {
  it('opens on Accounts & Platforms and projects native account state without cloning lifecycle controls', async () => {
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()

    expect(
      wrapper.get('[data-active-settings-section]').attributes('data-active-settings-section'),
    ).toBe('accounts')
    expect(wrapper.text()).toContain('消息平台')
    expect(wrapper.text()).toContain('Primary WhatsApp')
    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain('需要检查')
    expect(wrapper.text()).toContain('尚未配置')
    expect(wrapper.find('[data-to="/yance/platform-accounts"]').exists()).toBe(true)
    expect(listAccounts).toHaveBeenCalled()
  })

  it('shows Translation from real provider health without fake language controls', async () => {
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()
    await wrapper.get('[data-settings-section="translation"]').trigger('click')

    expect(wrapper.get('[data-settings-runtime-state="not_configured"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('DeepL')
    expect(wrapper.text()).toContain('尚未配置')
    expect(wrapper.find('[data-active-settings-section="translation"] input').exists()).toBe(false)
    expect(wrapper.find('[data-active-settings-section="translation"] select').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/HOLD|owner|admission|registry|Graphiti|Window\s*\d+/i)
  })

  it('uses the native theme state and delegates notification/profile management to User Settings', async () => {
    setTheme.mockClear()
    const wrapper = mount(YanceSettingsNativeComposition)
    await wrapper.get('[data-settings-section="appearance"]').trigger('click')

    const systemButton = wrapper.findAll('button').find((button) => button.text() === '跟随系统')
    expect(systemButton).toBeTruthy()
    await systemButton!.trigger('click')
    expect(setTheme).toHaveBeenCalledWith('system')
    expect(wrapper.text()).toContain('桌面通知')
    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.find('[data-to="/yance/manage/user"]').exists()).toBe(true)
  })

  it('keeps workspace policy and profile management on the existing native routes', () => {
    const wrapper = mount(YanceSettingsNativeComposition)
    expect(wrapper.find('[data-to="/yance/manage/organization"]').exists()).toBe(true)
    expect(wrapper.find('[data-to="/yance/manage/user"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('工作区')
    expect(wrapper.text()).toContain('时区')
    expect(wrapper.text()).toContain('营业时间')
  })
  it('keeps all five canonical status values in data attributes while rendering only Chinese labels', async () => {
    listAccounts.mockResolvedValueOnce([])
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()

    const status = () => wrapper.get('.pane-heading .truth-state')
    expect(status().attributes('data-settings-product-state')).toBe('Not configured')
    expect(status().text()).toBe('尚未配置')

    await wrapper.get('[data-settings-section="ai"]').trigger('click')
    expect(status().attributes('data-settings-product-state')).toBe('Connected')
    expect(status().text()).toBe('已连接')
    await wrapper.get('[data-settings-section="persona"]').trigger('click')
    expect(status().attributes('data-settings-product-state')).toBe('Needs attention')
    expect(status().text()).toBe('需要检查')
    await wrapper.get('[data-settings-section="memory"]').trigger('click')
    expect(status().attributes('data-settings-product-state')).toBe('Unavailable')
    expect(status().text()).toBe('暂不可用')
    await wrapper.get('[data-settings-section="translation"]').trigger('click')
    expect(wrapper.get('[data-settings-runtime-state="not_configured"]').exists()).toBe(true)
    expect(wrapper.get('.state-badge').text()).toBe('尚未配置')
    wrapper.unmount()
  })

  it('displays Loading as 加载中 and native read failure as 需要检查, never false unconfigured', async () => {
    let resolve!: (value: unknown[]) => void
    listAccounts.mockImplementationOnce(() => new Promise<unknown[]>(done => { resolve = done }))
    const loading = mount(YanceSettingsNativeComposition)
    expect(loading.get('.pane-heading .truth-state').attributes('data-settings-product-state')).toBe('Loading')
    expect(loading.get('.pane-heading .truth-state').text()).toBe('加载中')
    resolve([])
    await flushPromises()
    loading.unmount()

    listAccounts.mockRejectedValueOnce(new Error('offline'))
    const error = mount(YanceSettingsNativeComposition)
    await flushPromises()
    expect(error.get('.pane-heading .truth-state').attributes('data-settings-product-state')).toBe('Needs attention')
    expect(error.get('.pane-heading .truth-state').text()).toBe('需要检查')
    expect(error.findAll('.status-card .state-badge').every(x => x.text() === '需要检查')).toBe(true)
    expect(error.findAll('.status-card .state-badge').some(x => x.text() === '尚未配置')).toBe(false)
    error.unmount()
  })

})
