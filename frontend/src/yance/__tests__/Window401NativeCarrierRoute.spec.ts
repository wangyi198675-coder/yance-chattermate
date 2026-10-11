import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const { push } = vi.hoisted(() => ({ push: vi.fn(async () => undefined) }))
vi.mock('vue-router', () => ({
  useRouter: () => ({
    currentRoute: { value: { fullPath: '/yance/settings' } },
    push,
    afterEach: () => () => {},
  }),
}))
import YanceNativeCapabilityHub from '../components/YanceNativeCapabilityHub.vue'

afterEach(() => {
  document.body.replaceChildren()
  push.mockClear()
})

describe('W401 native capability history-entry launch contract', () => {
  it('marks an explicit Yance launch and preserves the return route for all navigable entries', async () => {
    for (const [key, path] of [
      ['knowledge', '/knowledge'],
      ['agents', '/ai-agents'],
      ['tickets', '/tickets'],
      ['analytics', '/analytics'],
      ['help', '/faq'],
      ['ai', '/yance/manage/ai'],
      ['widget', '/settings/widget-apps'],
    ]) {
      const wrapper = mount(YanceNativeCapabilityHub, { attachTo: document.body })
      await wrapper.get('[data-yance-capability-launcher]').trigger('click')
      await wrapper.get(`[data-capability="${key}"] button`).trigger('click')
      await flushPromises()
      expect(push).toHaveBeenCalledWith({
        path,
        state: { yanceNativeLaunch: true, yanceNativeReturnTo: '/yance/settings' },
      })
      wrapper.unmount()
      push.mockClear()
    }
  })

  it('does not route the unavailable workflow or forge a native permission bypass', async () => {
    const wrapper = mount(YanceNativeCapabilityHub)
    await wrapper.get('[data-yance-capability-launcher]').trigger('click')
    expect(wrapper.get('[data-capability="workflow"]').text()).toContain('不可用')
    expect(wrapper.find('[data-capability="workflow"] button').exists()).toBe(false)
    expect(push).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('uses browser-history entry markers rather than leaking session-wide origin to direct upstream URLs', () => {
    const layout = readFileSync(resolve(process.cwd(), 'src/layouts/DashboardLayout.vue'), 'utf8')
    expect(layout).toContain('window.history.state?.yanceNativeLaunch === true')
    expect(layout).toContain('window.history.replaceState')
    expect(layout).toContain('removeNativeRouteHook()')
    expect(layout).not.toContain('sessionStorage.setItem(nativeOriginKey')
    expect(layout).not.toContain('fromYanceHistory()')
    expect(layout).toContain('!isYanceNativeShell')
    expect(layout).toContain('data-yance-native-carrier')
  })
})
