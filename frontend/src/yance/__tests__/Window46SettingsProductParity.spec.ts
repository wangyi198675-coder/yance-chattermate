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
  useRouter: () => ({ push: vi.fn(), currentRoute: { value: { path: '/yance/settings' } } }),
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
    const canonicalStates: string[] = []
    for (const id of sectionIds) {
      await wrapper.get(`[data-settings-section="${id}"]`).trigger('click')
      rendered.push(wrapper.get('[data-active-settings-section]').text())
      canonicalStates.push(wrapper.get('.pane-heading .truth-state').attributes('data-settings-product-state') || '')
    }

    const productCopy = rendered.join('\n')
    expect(productCopy).not.toMatch(
      /Window\s*\d+|production owner|admission|registry|Graphiti|Process Compose|\bHOLD\b|production parity|AI_AUTO|AI_ASSIST|\bHUMAN\b/i,
    )
    // Product copy is Chinese, while the canonical machine-readable states
    // must remain truthful and stable for diagnostics and accessibility.
    for (const label of ['已连接', '需要检查', '尚未配置', '暂不可用']) {
      expect(productCopy).toContain(label)
    }
    for (const state of ['Needs attention', 'Not configured', 'Available', 'Verification pending']) {
      expect(canonicalStates).toContain(state)
    }
    // This fixture has a stored channel and AI settings, but no verified provider response.
    // Do not require or synthesize a Connected badge to satisfy the test.
    expect(canonicalStates).not.toContain('Connected')
    expect(canonicalStates.every(state => ['Connected', 'Needs attention', 'Not configured', 'Unavailable', 'Loading', 'Available', 'Verification pending'].includes(state))).toBe(true)
    expect(canonicalStates[sectionIds.indexOf('ai')]).toBe('Needs attention')
    expect(canonicalStates[sectionIds.indexOf('memory')]).toBe('Available')
    expect(canonicalStates[sectionIds.indexOf('translation')]).toBe('Not configured')
    expect(productCopy).not.toMatch(/\b(?:Connected|Needs attention|Not configured|Unavailable)\b/)
  })

  it('keeps read-only memory distinct from unverified AI and voice execution', async () => {
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()

    await wrapper.get('[data-settings-section="memory"]').trigger('click')
    const memoryPane = wrapper.get('[data-active-settings-section="memory"]')
    expect(memoryPane.text()).toContain('图谱推理或自动写入没有运行验收')
    expect(wrapper.get('.pane-heading .truth-state').attributes('data-settings-product-state')).toBe('Available')
    expect(memoryPane.find('input').exists()).toBe(false)
    expect(memoryPane.find('select').exists()).toBe(false)

    await wrapper.get('[data-settings-section="voice-media"]').trigger('click')
    const mediaPane = wrapper.get('[data-active-settings-section="voice-media"]')
    expect(wrapper.get('.pane-heading .truth-state').attributes('data-settings-product-state')).toBe('Verification pending')
    expect(mediaPane.find('input').exists()).toBe(false)
    expect(mediaPane.find('select').exists()).toBe(false)

    await wrapper.get('[data-settings-section="translation"]').trigger('click')
    const translationPane = wrapper.get('[data-active-settings-section="translation"]')
    expect(translationPane.text()).toContain('尚未配置')
    expect(wrapper.get('.pane-heading .truth-state').attributes('data-settings-product-state')).toBe('Not configured')
    expect(translationPane.get('[data-settings-runtime-state="not_configured"]').attributes('data-settings-runtime-state')).toBe('not_configured')
    expect(translationPane.text()).toContain('DeepL')
    expect(translationPane.find('input').exists()).toBe(false)
    expect(translationPane.find('select').exists()).toBe(false)
  })
})
