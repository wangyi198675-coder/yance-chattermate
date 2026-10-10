import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { ChannelAccount } from '@/services/channels'

const api = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  connectEmail: vi.fn(),
  connectSms: vi.fn(),
  connectLine: vi.fn(),
  disconnectEmail: vi.fn(),
  disconnectSms: vi.fn(),
  disconnectLine: vi.fn(),
}))
vi.mock('@/services/channels', () => ({
  default: api,
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/layouts/DashboardLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))
vi.mock('@/components/integrations/MetaChannelConnect.vue', () => ({
  default: { template: '<div data-native-meta-modal />' },
}))
vi.mock('@/components/integrations/TelegramConnectModal.vue', () => ({
  default: { template: '<div data-native-telegram-modal />' },
}))
vi.mock('@/components/integrations/ChannelConnectModal.vue', () => ({
  default: { template: '<div data-native-credential-modal />' },
}))
vi.mock('@/components/integrations/WhatsAppTemplateManager.vue', () => ({
  default: { template: '<div data-native-template-modal />' },
}))

import YancePlatformAccounts from '../YancePlatformAccounts.vue'

const make = (channel_type: ChannelAccount['channel_type'], id: string, health?: ChannelAccount['provider_health']): ChannelAccount => ({
  id,
  channel_type,
  external_account_id: `external-${id}`,
  display_name: `Synthetic ${id}`,
  is_active: true,
  provider_health: health,
})

beforeEach(() => { vi.clearAllMocks() })

describe('W358 W359 provider health and existing credential account safety', () => {
  it('prioritizes reconnect and provider error over stale ready or healthy status', async () => {
    api.listAccounts.mockResolvedValue([
      make('whatsapp', 'reconnect', { readiness: 'ready', reconnect_needed: true }),
      make('whatsapp', 'error', { readiness: 'healthy', last_provider_error: 'revoked' }),
      make('whatsapp', 'ok', { readiness: 'ready', reconnect_needed: false }),
    ])
    const wrapper = mount(YancePlatformAccounts)
    await flushPromises()
    const labels = wrapper.findAll('[data-platform-type="whatsapp"] li small').map(el => el.text())
    expect(labels).toEqual(['需要检查', '需要检查', '提供商就绪'])
  })

  it('displays a retryable error without any fabricated not-configured platform rows', async () => {
    api.listAccounts.mockRejectedValue(new Error('offline'))
    const wrapper = mount(YancePlatformAccounts)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('无法读取平台账号')
    expect(wrapper.find('[data-platform-empty]').exists()).toBe(false)
    expect(wrapper.findAll('.platform-section')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('尚未配置')
    api.listAccounts.mockResolvedValueOnce([])
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.findAll('.platform-section')).toHaveLength(8)
    expect(wrapper.find('[data-platform-empty]').exists()).toBe(true)
  })

  it.each(['email', 'sms', 'line'] as const)(
    '%s existing row opens safe read-only identity and cannot reconfigure via create POST',
    async (channel) => {
      api.listAccounts.mockResolvedValue([make(channel, `fixed-${channel}-id`)])
      const wrapper = mount(YancePlatformAccounts)
      await flushPromises()
      const section = wrapper.get(`[data-platform-type="${channel}"]`)
      expect(section.get('li').text()).toContain('查看账号')
      await section.get('li button').trigger('click')
      expect(wrapper.get('[data-yance-existing-credential-safe-view]').text()).toContain(`external-fixed-${channel}-id`)
      expect(wrapper.get('[data-yance-existing-credential-safe-view]').text()).toContain('凭据重配暂不可用')
      expect(wrapper.find('[data-native-credential-modal]').exists()).toBe(false)
      expect(api.connectEmail).not.toHaveBeenCalled()
      expect(api.connectSms).not.toHaveBeenCalled()
      expect(api.connectLine).not.toHaveBeenCalled()
      await wrapper.get('[data-yance-existing-credential-safe-view] button').trigger('click')
      expect(wrapper.find('[data-yance-existing-credential-safe-view]').exists()).toBe(false)
      await section.get('header button').trigger('click')
      expect(wrapper.find('[data-native-credential-modal]').exists()).toBe(true)
      expect(api.connectEmail).not.toHaveBeenCalled()
      expect(api.connectSms).not.toHaveBeenCalled()
      expect(api.connectLine).not.toHaveBeenCalled()
    },
  )
})
