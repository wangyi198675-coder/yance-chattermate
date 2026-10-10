import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CustomerAvatar from '@/components/people/CustomerAvatar.vue'

describe('CustomerAvatar canonical projection', () => {
  it('shows the canonical person-profile avatar URL', () => {
    const wrapper = mount(CustomerAvatar, {
      props: {
        profile: { avatar: { url: ' https://example.test/avatar.jpg ' } },
        displayName: 'Anna Keller',
      },
    })
    expect(wrapper.get('img').attributes('src')).toBe('https://example.test/avatar.jpg')
  })

  it('falls back to initials when the canonical avatar is absent', () => {
    const wrapper = mount(CustomerAvatar, {
      props: { profile: null, displayName: 'Anna Keller' },
    })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.get('.canonical-customer-avatar__fallback').text()).toBe('AK')
  })

  it('fails closed to initials after an image load error without retrying the broken URL', async () => {
    const wrapper = mount(CustomerAvatar, {
      props: {
        profile: { avatar: { url: 'https://example.test/broken.jpg' } },
        displayName: 'Anna Keller',
      },
    })
    await wrapper.get('img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.get('.canonical-customer-avatar__fallback').text()).toBe('AK')
  })

  it('uses a safe anonymous fallback when no display name exists', () => {
    const wrapper = mount(CustomerAvatar, {
      props: { profile: null, displayName: '', anonymous: true },
    })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.get('.canonical-customer-avatar__fallback').text()).toBe('·')
    expect(wrapper.get('[data-canonical-customer-avatar]').classes()).toContain('is-anonymous-fallback')
  })
})
