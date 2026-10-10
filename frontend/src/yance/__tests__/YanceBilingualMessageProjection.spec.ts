import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import YanceBilingualMessageProjection from '../components/YanceBilingualMessageProjection.vue'

describe('YanceBilingualMessageProjection', () => {
  it('shows only a valid exact-identity Chinese secondary projection', () => {
    const wrapper = mount(YanceBilingualMessageProjection, {
      props: {
        canonicalMessageId: 42,
        sourceText: 'Hello',
        translation: { messageId: 42, status: 'success', text: '你好' },
      },
    })
    expect(wrapper.attributes('data-state')).toBe('success')
    expect(wrapper.get('[data-yance-translated-text]').text()).toBe('你好')
  })

  it.each([
    { messageId: 42, status: 'failed' as const, text: '错误结果' },
    { messageId: 42, status: 'stale' as const, text: '旧结果' },
    { messageId: 41, status: 'success' as const, text: '错绑身份' },
    { messageId: 42, status: 'success' as const, text: '' },
  ])('fails closed for failed/stale/mismatched/empty translation %#', (translation) => {
    const wrapper = mount(YanceBilingualMessageProjection, {
      props: { canonicalMessageId: 42, sourceText: 'Hello', translation },
    })
    expect(wrapper.attributes('data-state')).toBe('fail-closed')
    expect(wrapper.find('[data-yance-translated-text]').exists()).toBe(false)
  })

  it('fails closed when the source is already Chinese instead of duplicating it', () => {
    const wrapper = mount(YanceBilingualMessageProjection, {
      props: {
        canonicalMessageId: 42,
        sourceText: '你好 Berlin',
        translation: { messageId: 42, status: 'success', text: '你好，柏林' },
      },
    })
    expect(wrapper.attributes('data-state')).toBe('fail-closed')
    expect(wrapper.find('[data-yance-translated-text]').exists()).toBe(false)
  })

  it('keeps rail fail-closed states visually silent', () => {
    const wrapper = mount(YanceBilingualMessageProjection, {
      props: {
        canonicalMessageId: 42,
        sourceText: 'Hello',
        silentFailClosed: true,
        translation: { messageId: 42, status: 'failed' },
      },
    })
    expect(wrapper.attributes('data-state')).toBe('fail-closed')
    expect(wrapper.text()).toBe('')
  })
})
