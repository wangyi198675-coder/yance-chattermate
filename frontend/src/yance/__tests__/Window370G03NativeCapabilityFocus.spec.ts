import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import YanceNativeCapabilityHub from '../components/YanceNativeCapabilityHub.vue'

const { push, subscriptions, afterRoute } = vi.hoisted(() => {
  const subscriptions = new Set<() => void>()
  return {
    push: vi.fn(async (path: string) => {
      for (const callback of subscriptions) callback()
      return undefined
    }),
    subscriptions,
    afterRoute: vi.fn((callback: () => void) => {
      subscriptions.add(callback)
      return () => subscriptions.delete(callback)
    }),
  }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push, afterEach: afterRoute, currentRoute: { value: { fullPath: '/yance/home' } } }) }))

const mounted = () => mount(YanceNativeCapabilityHub, { attachTo: document.body })
const dialog = () => document.querySelector<HTMLElement>('[data-yance-native-capability-hub]')

let rects: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  push.mockClear()
  afterRoute.mockClear()
  subscriptions.clear()
  // jsdom has no layout boxes; actual rendered Chrome geometry is tested separately.
  rects = vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(
    () => ({ length: 1 }) as DOMRectList,
  )
})
afterEach(() => {
  rects.mockRestore()
  document.body.replaceChildren()
  subscriptions.clear()
})

describe('W362 G03 capability dialog keyboard and native route lifecycle', () => {
  it('focuses its close control, loops Tab both ways, and returns focus after Escape', async () => {
    const wrapper = mounted()
    const launcher = wrapper.get<HTMLButtonElement>('[data-yance-capability-launcher]')
    launcher.element.focus()
    await launcher.trigger('click')
    await flushPromises()

    const element = dialog()!
    expect(element.getAttribute('role')).toBe('dialog')
    expect(element.getAttribute('aria-modal')).toBe('true')
    expect(element.getAttribute('aria-labelledby')).toBe('yance-native-capability-title')
    const controls = [...element.querySelectorAll<HTMLButtonElement>('button')]
    expect(controls).toHaveLength(8)
    expect(document.activeElement).toBe(controls[0])

    controls.at(-1)!.focus()
    const next = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    document.dispatchEvent(next)
    expect(next.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(controls[0])

    const previous = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })
    document.dispatchEvent(previous)
    expect(previous.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(controls.at(-1))

    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(escape)
    await flushPromises()
    expect(escape.defaultPrevented).toBe(true)
    expect(dialog()).toBeNull()
    expect(document.activeElement).toBe(launcher.element)
    wrapper.unmount()
    expect(subscriptions.size).toBe(0)
  })

  it('restores launcher after mouse Close and backdrop; reopens without orphan focus guards', async () => {
    const wrapper = mounted()
    const opener = wrapper.get<HTMLButtonElement>('[data-yance-capability-launcher]')
    for (let i = 0; i < 3; i++) {
      opener.element.focus()
      await opener.trigger('click')
      await flushPromises()
      expect(document.activeElement).toBe(dialog()!.querySelector('[data-yance-capability-close]'))
      if (i % 2 === 0) {
        await wrapper.get('[data-yance-capability-close]').trigger('click')
      } else {
        await wrapper.get('[data-yance-capability-scrim]').trigger('mousedown')
      }
      await flushPromises()
      expect(dialog()).toBeNull()
      expect(document.activeElement).toBe(opener.element)
    }
    wrapper.unmount()
  })

  it('keeps GF topmost and dismisses only hub after top GF closes', async () => {
    const wrapper = mounted()
    const opener = wrapper.get<HTMLButtonElement>('[data-yance-capability-launcher]')
    await opener.trigger('click')
    await flushPromises()
    const gf = document.createElement('div')
    gf.setAttribute('data-yance-global-girlfriend', '')
    document.body.appendChild(gf)
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(escape)
    await flushPromises()
    expect(dialog()).not.toBeNull()
    expect(escape.defaultPrevented).toBe(false)
    gf.remove()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    await flushPromises()
    expect(dialog()).toBeNull()
    wrapper.unmount()
  })

  it('closes on native navigation without restoring a stale launcher across route changes', async () => {
    const wrapper = mounted()
    const opener = wrapper.get<HTMLButtonElement>('[data-yance-capability-launcher]')
    opener.element.focus()
    await opener.trigger('click')
    await flushPromises()
    const native = wrapper.get<HTMLButtonElement>('[data-capability="agents"] [data-native-route]')
    native.element.focus()
    await native.trigger('click')
    await flushPromises()
    expect(push).toHaveBeenCalledWith({ path: '/ai-agents', state: { yanceNativeLaunch: true, yanceNativeReturnTo: '/yance/home' } })
    expect(dialog()).toBeNull()
    expect(document.activeElement).not.toBe(opener.element)
    wrapper.unmount()
    expect(subscriptions.size).toBe(0)
  })
})
