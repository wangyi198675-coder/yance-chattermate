import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const api = vi.hoisted(() => ({ listAccounts: vi.fn() }))
vi.mock('@/services/channels', () => ({ default: api }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/layouts/DashboardLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))
vi.mock('../components/YanceWebShell.vue', () => ({
  default: { template: '<section><slot /></section>' },
}))
vi.mock('@/components/integrations/MetaChannelConnect.vue', () => ({
  default: { template: '<div class="meta-modal-content"><div class="meta-modal-header"><h3>Meta 连接</h3><button aria-label="关闭弹窗" @click="$emit(\'close\')">关闭</button></div><input aria-label="账号" /><button>确认</button></div>' },
}))
vi.mock('@/components/integrations/TelegramConnectModal.vue', () => ({
  default: { template: '<div class="tg-modal-content"><div class="tg-modal-header"><h3>Telegram 连接</h3><button aria-label="关闭弹窗" @click="$emit(\'close\')">关闭</button></div><input aria-label="令牌" /><button>确认</button></div>' },
}))
vi.mock('@/components/integrations/ChannelConnectModal.vue', () => ({
  default: { template: '<div class="cc-modal-content"><div class="cc-modal-header"><h3>凭据连接</h3><button aria-label="关闭弹窗" @click="$emit(\'close\')">关闭</button></div><input aria-label="凭据" /><button>确认</button></div>' },
}))
vi.mock('@/components/integrations/WhatsAppTemplateManager.vue', () => ({
  default: { template: '<div data-native-template />' },
}))
import YancePlatformAccounts from '../YancePlatformAccounts.vue'

let rects: ReturnType<typeof vi.spyOn> | undefined
beforeEach(() => {
  api.listAccounts.mockReset()
  api.listAccounts.mockResolvedValue([])
  rects = vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(
    () => ({ length: 1 }) as DOMRectList,
  )
})
afterEach(() => {
  rects?.mockRestore()
  document.body.replaceChildren()
})

describe('W364 R2 all seven native channel dialogs: host-owned focus lifecycle', () => {
  it.each(['messenger', 'whatsapp', 'instagram', 'telegram', 'line', 'email', 'sms'] as const)(
    '%s: native modal has real accessible semantics, wraps keyboard, and returns to exact launcher after refresh',
    async (channel) => {
      const wrapper = mount(YancePlatformAccounts, { attachTo: document.body })
      await flushPromises()
      const trigger = wrapper.get<HTMLButtonElement>('[data-yance-channel-launcher="' + channel + '"]')
      trigger.element.focus()
      expect(document.activeElement).toBe(trigger.element)
      await trigger.trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-yance-connection-guide]').text()).toContain('未资格化')
      await wrapper.get('[data-guide-native="' + channel + '"]').trigger('click')
      await flushPromises()
      const dialog = document.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]')
      expect(dialog).toBeTruthy()
      expect(dialog?.getAttribute('aria-labelledby')).toContain(channel)
      expect(dialog?.contains(document.activeElement)).toBe(true)
      const buttons = Array.from(dialog!.querySelectorAll<HTMLButtonElement>('button'))
      buttons[0]!.focus()
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
      expect(document.activeElement).toBe(buttons.at(-1))
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
      expect(document.activeElement).toBe(buttons[0])
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await flushPromises()
      expect(document.querySelector('[role="dialog"][aria-modal="true"]')).toBeNull()
      expect(document.activeElement).toBe(trigger.element)
      expect(api.listAccounts).toHaveBeenCalledTimes(2)
      wrapper.unmount()
    },
  )
})
