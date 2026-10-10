import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('@/composables/useTheme', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return {
    useTheme: () => ({
      mode: ref('system'),
      setTheme: vi.fn(),
    }),
  }
})

vi.mock('@/composables/useAISetup', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return {
    useAISetup: () => ({
      isLoading: ref(false),
      error: ref(''),
      setupConfig: ref({ provider: 'openai', model: 'gpt-test', apiKey: '', baseUrl: '' }),
      providers: ref([{ value: 'openai', models: [{ value: 'gpt-test', reasoning_strengths: [] }] }]),
      hasExistingConfig: ref(true),
    }),
  }
})

vi.mock('@/composables/useNotificationSettings', async () => {
  const { ref } = await vi.importActual<typeof import('vue')>('vue')
  return {
    useNotificationSettings: () => ({
      settings: ref({
        notify_new_chat: true,
        notify_chat_transfer: false,
        notify_chat_assigned: true,
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
    listAccounts: vi.fn().mockResolvedValue([
      {
        id: 'wa-1',
        channel_type: 'whatsapp',
        external_account_id: '15550001',
        display_name: 'Primary WhatsApp',
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
  default: { template: '<div><slot /></div>' },
}))

vi.mock('vue-router', () => ({
  RouterLink: {
    props: ['to'],
    template: '<a :data-to="to"><slot /></a>',
  },
}))

import YanceSettingsNativeComposition from '../YanceSettingsNativeComposition.vue'

const sectionIds = [
  'accounts',
  'ai',
  'persona',
  'memory',
  'translation',
  'voice-media',
  'automation',
  'appearance',
  'privacy',
  'diagnostics',
] as const

describe('Window 46 Settings product parity and copy closure', () => {
  it('renders all required Settings product families', async () => {
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()

    for (const id of sectionIds) {
      expect(wrapper.find(`[data-settings-section="${id}"]`).exists()).toBe(true)
    }

    expect(wrapper.text()).toContain('账户与平台')
    expect(wrapper.text()).toContain('AI 与模型')
    expect(wrapper.text()).toContain('外观与通知')
    expect(wrapper.text()).toContain('诊断')
  })

  it('keeps product-facing copy free of internal engineering language across every section', async () => {
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()

    const rendered: string[] = []
    for (const id of sectionIds) {
      await wrapper.get(`[data-settings-section="${id}"]`).trigger('click')
      rendered.push(wrapper.get('[data-active-settings-section]').text())
    }

    const productCopy = rendered.join('\n')
    expect(productCopy).not.toMatch(
      /Window\s*\d+|production owner|admission|registry|Graphiti|Process Compose|\bHOLD\b|production parity|AI_AUTO|AI_ASSIST|\bHUMAN\b/i,
    )
    expect(productCopy).toContain('Connected')
    expect(productCopy).toContain('Needs attention')
    expect(productCopy).toContain('Not configured')
    expect(productCopy).toContain('Unavailable')
  })

  it('does not expose executable controls for unavailable runtime families', async () => {
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()

    for (const id of ['memory', 'voice-media'] as const) {
      await wrapper.get(`[data-settings-section="${id}"]`).trigger('click')
      const pane = wrapper.get('[data-active-settings-section]')
      expect(pane.text()).toContain('Unavailable')
      expect(pane.find('input').exists()).toBe(false)
      expect(pane.find('select').exists()).toBe(false)
    }

    await wrapper.get('[data-settings-section="translation"]').trigger('click')
    const translationPane = wrapper.get('[data-active-settings-section="translation"]')
    expect(translationPane.text()).toContain('Not configured')
    expect(translationPane.text()).toContain('DeepL')
    expect(translationPane.find('input').exists()).toBe(false)
    expect(translationPane.find('select').exists()).toBe(false)
  })
})
