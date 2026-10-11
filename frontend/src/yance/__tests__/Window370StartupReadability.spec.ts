import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const { replace, query } = vi.hoisted(() => ({
  replace: vi.fn(),
  query: { state: 'NETWORK_ERROR' as 'NETWORK_ERROR' | 'BACKEND_UNAVAILABLE' },
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query }),
  useRouter: () => ({ replace }),
}))
import YanceStartupStateView from '../YanceStartupStateView.vue'

describe('W370 genuine startup failure UI', () => {
  it('shows readable Chinese backend failure and offers the existing recheck route', async () => {
    query.state = 'NETWORK_ERROR'
    const wrapper = mount(YanceStartupStateView)
    expect(wrapper.get('[data-yance-startup-state]').text()).toContain('无法连接本地服务')
    expect(wrapper.text()).toContain('本机 ChatterMate 后端')
    await wrapper.get('button').trigger('click')
    expect(replace).toHaveBeenCalledWith('/yance')
    wrapper.unmount()
  })
  it('distinguishes unavailable backend without suggesting account reset', () => {
    query.state = 'BACKEND_UNAVAILABLE'
    const wrapper = mount(YanceStartupStateView)
    expect(wrapper.text()).toContain('本地服务尚未就绪')
    expect(wrapper.text()).toContain('不会因此被重置')
    wrapper.unmount()
  })
  it('has explicit dark background and readable foreground instead of inheriting theme white-on-white', () => {
    const text = readFileSync(resolve(process.cwd(), 'src/yance/YanceStartupStateView.vue'), 'utf8')
    expect(text).toContain('background: #231e2c')
    expect(text).toContain('color: #f4eaf3')
    expect(text).toContain('aria-live="polite"')
  })
})
