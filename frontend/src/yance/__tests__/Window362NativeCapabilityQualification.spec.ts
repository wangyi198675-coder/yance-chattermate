import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import YanceNativeCapabilityHub from '../components/YanceNativeCapabilityHub.vue'
import YancePlatformConnectionGuide from '../components/YancePlatformConnectionGuide.vue'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push, currentRoute: { value: { fullPath: '/yance/home' } } }) }))
const channels = ['messenger','whatsapp','instagram','telegram','line','email','sms','slack'] as const

describe('W370 W362 G03/G05 native-first qualification boundaries', () => {
  it('renders 8 distinct capability families; routes only existing native views, never nonexistent workflow', async () => {
    push.mockClear()
    const w = mount(YanceNativeCapabilityHub)
    await w.get('[data-yance-capability-launcher]').trigger('click')
    expect(w.findAll('[data-yance-native-capability-hub] article')).toHaveLength(8)
    const routes = w.findAll('[data-native-route]').map(x=>x.attributes('data-native-route'))
    expect(new Set(routes).size).toBe(7)
    expect(routes).toContain('/ai-agents')
    expect(routes).toContain('/knowledge')
    expect(routes).toContain('/tickets')
    expect(routes).toContain('/analytics')
    expect(routes).toContain('/faq')
    expect(routes).toContain('/settings/widget-apps')
    expect(routes).toContain('/yance/manage/ai')
    expect(w.get('[data-capability="workflow"]').text()).toContain('不可用')
    expect(w.get('[data-capability="workflow"]').find('button').exists()).toBe(false)
    await w.get('[data-capability="agents"] button').trigger('click')
    expect(push).toHaveBeenCalledWith({ path: '/ai-agents', state: { yanceNativeLaunch: true, yanceNativeReturnTo: '/yance/home' } })
    w.unmount()
  })
  it.each(channels)('%s requires truthful identity choice before any native connection', async channel => {
    const w = mount(YancePlatformConnectionGuide, { props: { channel } })
    expect(w.get('[data-yance-connection-guide]').attributes('data-yance-connection-guide')).toBe('')
    const entries = w.findAll('[data-identity-index]')
    expect(entries).toHaveLength(2)
    expect(entries[0]!.attributes('data-qualified')).toBe('native')
    expect(entries[1]!.attributes('data-qualified')).toBe('unavailable')
    expect(entries[1]!.find('button').exists()).toBe(false)
    expect(w.findAll('[data-guide-native]')).toHaveLength(1)
    await w.get('[data-guide-native]').trigger('click')
    expect(w.emitted('continue')?.[0]).toEqual([channel])
    w.unmount()
  })
})
