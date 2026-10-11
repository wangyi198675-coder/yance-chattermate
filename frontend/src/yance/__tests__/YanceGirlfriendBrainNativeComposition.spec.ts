import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import YanceGirlfriendBrainNativeComposition from '../components/YanceGirlfriendBrainNativeComposition.vue'
import { FROZEN_VOICE_MEDIA_UI_READINESS } from '../capabilityWiring'

const props = {
  voiceReadiness: FROZEN_VOICE_MEDIA_UI_READINESS.voice,
  imageReadiness: FROZEN_VOICE_MEDIA_UI_READINESS.image,
  videoReadiness: FROZEN_VOICE_MEDIA_UI_READINESS.video,
}

describe('YanceGirlfriendBrainNativeComposition', () => {
  it('uses the native BaseModal composition with turn-scoped semantic state', () => {
    const wrapper = mount(YanceGirlfriendBrainNativeComposition, { props })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(wrapper.get('[data-yance-girlfriend-turn-only]').element).toBeInstanceOf(HTMLInputElement)
    expect((wrapper.get('[data-yance-girlfriend-turn-only]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('[data-yance-girlfriend-scope]').text()).toContain('当前关系')
    expect(wrapper.find('[data-yance-girlfriend-persona]').exists()).toBe(true)
    expect(wrapper.find('[data-yance-girlfriend-goal]').exists()).toBe(true)
  })

  it('stages a semantic intent draft without sending a conversation message', async () => {
    const wrapper = mount(YanceGirlfriendBrainNativeComposition, { props })
    await wrapper.get('[data-yance-girlfriend-intent]').setValue('先接住对方刚才的信息，再自然延续。')
    await wrapper.get('input[value="contact"]').setValue(true)
    await wrapper.get('[data-yance-girlfriend-persona]').setValue('成熟自然')
    await wrapper.get('[data-yance-girlfriend-goal]').setValue('继续聊天')
    await wrapper.get('[data-yance-stage-intent]').trigger('click')

    expect(wrapper.emitted('intent-draft')?.[0]).toEqual([{
      instruction: '先接住对方刚才的信息，再自然延续。',
      scope: 'contact',
      personaNote: '成熟自然',
      goalNote: '继续聊天',
      turnOnly: true,
    }])
    expect(wrapper.find('[data-yance-girlfriend-receipt]').exists()).toBe(false)
    await wrapper.setProps({ intentFeedback: { state: 'ready', detail: 'Reply Brain 已接收本轮意图；仍须手动生成并确认。', undoAvailable: true } })
    expect(wrapper.get('[data-yance-girlfriend-receipt]').attributes('data-receipt-state')).toBe('ready')
    await wrapper.get('[data-yance-girlfriend-local-undo]').trigger('click')
    expect(wrapper.emitted('undo-request')).toHaveLength(1)
  })

  it('projects voice and generative media as truthful non-GREEN states', () => {
    const wrapper = mount(YanceGirlfriendBrainNativeComposition, { props })
    for (const selector of [
      '[data-yance-voice-readiness]',
      '[data-yance-image-readiness]',
      '[data-yance-video-readiness]',
    ]) {
      const button = wrapper.get(selector)
      expect(button.attributes('data-runtime-state')).toBe('runtime-pending')
      expect(button.attributes('disabled')).toBeDefined()
    }
  })
})
