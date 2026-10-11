import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import YanceWebShell from '../components/YanceWebShell.vue'
import YanceGlobalGirlfriend from '../components/YanceGlobalGirlfriend.vue'

const api = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  push: vi.fn(),
  route: { path: '/yance/home' },
}))
vi.mock('@/services/channels', () => ({
  default: { listAccounts: api.listAccounts },
}))
vi.mock('vue-router', () => ({
  useRoute: () => api.route,
  useRouter: () => ({ push: api.push, currentRoute: { value: api.route } }),
  RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
}))
describe('W371 approved REV3.4-P1R1 native Vue web shell + global GF', () => {
  beforeEach(() => { vi.clearAllMocks(); api.route.path = '/yance/home' })
  afterEach(() => { document.querySelectorAll('.yance-gf-scrim').forEach(e => e.remove()) })
  it('renders the six native destinations without any parallel Composer or demo dataset', async () => {
    const wrapper = mount(YanceWebShell, { slots: { default: '<div data-native-owner>真实 native slot</div>' } })
    await flushPromises()
    expect(wrapper.get('[data-yance-rev34-shell]').attributes('data-design-version')).toBe('REV3.4-P1R1')
    expect(wrapper.findAll('.yance-web-route')).toHaveLength(6)
    expect(wrapper.text()).toContain('平台状态请在账号页核对')
    expect(wrapper.find('[data-native-owner]').exists()).toBe(true)
    expect(wrapper.findAll('textarea')).toHaveLength(0)
    wrapper.unmount()
  })
  it('does not duplicate the native ChannelAccount fetch in the shared shell', async () => {
    const wrapper = mount(YanceWebShell)
    await flushPromises()
    expect(api.listAccounts).not.toHaveBeenCalled()
    expect(wrapper.get('[data-yance-live-channel-status]').text()).toContain('平台状态请在账号页核对')
    wrapper.unmount()
  })
  it('does not compete for the conversation-only Ctrl+Shift+G shortcut, but keeps the sidebar launcher', async () => {
    api.route.path = '/yance'
    const wrapper = mount(YanceGlobalGirlfriend, { attachTo: document.body, props: {
      open: false, 'onUpdate:open': async (value: boolean) => { await wrapper.setProps({ open: value }) },
    } })
    const opener = document.createElement('button')
    opener.setAttribute('data-yance-global-girlfriend-launcher', '')
    document.body.appendChild(opener)
    opener.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'G', ctrlKey: true, shiftKey: true, bubbles: true }))
    await flushPromises()
    expect(document.querySelector('.yance-gf-dialog')).toBeNull()
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(document.querySelectorAll('.yance-gf-dialog')).toHaveLength(1)
    const provider = document.createElement('section')
    provider.setAttribute('role', 'dialog')
    provider.setAttribute('aria-modal', 'true')
    document.body.appendChild(provider)
    document.querySelector<HTMLElement>('.yance-gf-close')?.focus()
    document.querySelector<HTMLElement>('.yance-gf-close')?.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    )
    await flushPromises()
    expect(document.querySelector('.yance-gf-dialog')).toBeNull()
    expect(document.querySelector('[role="dialog"][aria-modal="true"]')).toBe(provider)
    provider.remove()
    expect(document.activeElement).toBe(opener)
    opener.remove()
    wrapper.unmount()
  })
  it('opens global GF on Ctrl+Shift+G, scopes unsupported task safely and restores opener focus', async () => {
    const wrapper = mount(YanceGlobalGirlfriend, { attachTo: document.body, props: { open: false, 'onUpdate:open': async(value: boolean) => {
      await wrapper.setProps({ open: value })
    } } })
    const launcher = document.createElement('button')
    launcher.setAttribute('data-yance-global-girlfriend-launcher', 'true')
    document.body.appendChild(launcher)
    launcher.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'G', ctrlKey: true, shiftKey: true, bubbles: true }))
    await flushPromises()
    const modal = document.querySelector('.yance-gf-dialog')
    expect(modal?.getAttribute('aria-modal')).toBe('true')
    const input = document.querySelector<HTMLTextAreaElement>('[data-yance-global-gf-input]')!
    expect(document.activeElement?.getAttribute('id')).toBe('yance-gf-task-input')
    input.value = '只讨论这一轮，不发送'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    document.querySelector<HTMLButtonElement>('[data-yance-global-gf-submit]')!.click()
    await flushPromises()
    expect(document.querySelector('[data-yance-global-gf-feedback]')?.textContent).toContain('没有选中的对话')
    document.querySelector<HTMLButtonElement>('.yance-gf-close')!.click()
    await flushPromises()
    expect(document.querySelector('.yance-gf-dialog')).toBeNull()
    expect(document.activeElement).toBe(launcher)
    wrapper.unmount()
    launcher.remove()
  })
})
