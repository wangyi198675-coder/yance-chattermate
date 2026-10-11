import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const { translationHealth } = vi.hoisted(() => ({
  translationHealth: vi.fn(),
}))
vi.mock('@/services/translation', () => ({
  translationService: { health: translationHealth },
}))
vi.mock('@/services/channels', () => ({
  default: { listAccounts: vi.fn(async () => []) },
}))
vi.mock('@/composables/useTheme', () => ({
  useTheme: () => ({ mode: ref('dark'), setTheme: vi.fn() }),
}))
vi.mock('@/composables/useAISetup', () => ({
  useAISetup: () => ({
    isLoading: ref(false),
    error: ref(''),
    hasExistingConfig: ref(false),
    setupConfig: ref({ provider: '', model: '', fallbackModel: '', reasoningStrength: '' }),
    providers: ref([]),
  }),
}))
vi.mock('@/composables/useNotificationSettings', () => ({
  useNotificationSettings: () => ({
    settings: ref({ sound_enabled: true }),
    isLoading: ref(false),
    error: ref(''),
  }),
}))
vi.mock('@/layouts/DashboardLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))
vi.mock('../components/YanceWebShell.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))
vi.mock('vue-router', () => ({
  RouterLink: {
    props: ['to'],
    template: '<a :data-to="to"><slot /></a>',
  },
}))
import YanceSettingsNativeComposition from '../YanceSettingsNativeComposition.vue'

let oldFetch: typeof fetch
beforeEach(() => {
  oldFetch = globalThis.fetch
  globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ status: 'healthy', version: 'test' }) })) as unknown as typeof fetch
  translationHealth.mockReset()
})
afterEach(() => {
  globalThis.fetch = oldFetch
  document.body.replaceChildren()
})

const state = (wrapper: ReturnType<typeof mount>) =>
  wrapper.get('[data-settings-product-state]').attributes('data-settings-product-state')

describe('W401 truthful provider vs local-capability status', () => {
  it.each([
    [{ state: 'not_configured' }, 'Not configured', '尚未配置 DeepL'],
    [{ state: 'connected' }, 'Connected', '翻译健康接口报告已连接'],
    [{ state: 'needs_attention', errorCode: 'UPSTREAM_ERROR' }, 'Needs attention', '翻译健康检查失败'],
  ])('projects %j from real translation health as %s', async (health, productState, detail) => {
    translationHealth.mockResolvedValue(health)
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()
    await wrapper.get('[data-settings-section="translation"]').trigger('click')
    expect(state(wrapper)).toBe(productState)
    expect(wrapper.text()).toContain(detail)
    expect(wrapper.get('[data-settings-runtime-state]').attributes('data-settings-runtime-state')).toBe(health.state)
    // Local language/integrity checks are capabilities, never a verified DeepL connection.
    expect(wrapper.get('.feature-list').text()).toContain('已有功能')
    wrapper.unmount()
  })

  it('fails closed on translation health network error rather than turning green', async () => {
    translationHealth.mockRejectedValue(new Error('network offline'))
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()
    await wrapper.get('[data-settings-section="translation"]').trigger('click')
    expect(state(wrapper)).toBe('Needs attention')
    expect(wrapper.text()).toContain('翻译健康检查失败')
    wrapper.unmount()
  })

  it('distinguishes local functionality and independent runtime verification', async () => {
    translationHealth.mockResolvedValue({ state: 'not_configured' })
    const wrapper = mount(YanceSettingsNativeComposition)
    await flushPromises()
    for (const [section, expected] of [
      ['persona', 'Verification pending'],
      ['memory', 'Available'],
      ['voice-media', 'Verification pending'],
      ['automation', 'Available'],
      ['appearance', 'Available'],
      ['ai', 'Not configured'],
    ]) {
      await wrapper.get(`[data-settings-section="${section}"]`).trigger('click')
      expect(state(wrapper)).toBe(expected)
    }
    wrapper.unmount()
  })
})
