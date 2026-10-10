import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const { adoptDraftSpy, adoptAttachmentSpy, adoptMediaIntentSpy } = vi.hoisted(() => ({
  adoptDraftSpy: vi.fn(),
  adoptAttachmentSpy: vi.fn(),
  adoptMediaIntentSpy: vi.fn(),
}))

vi.mock('@/views/ConversationsView.vue', () => ({
  default: {
    name: 'ConversationsView',
    props: ['layoutHideHeader'],
    methods: {
      adoptDraft: adoptDraftSpy,
      adoptAttachment: adoptAttachmentSpy,
      adoptMediaIntent: adoptMediaIntentSpy,
    },
    template: `<div class="native-conversations-view" :data-hide-header="String(layoutHideHeader)">
      <slot name="conversation-header-actions" />
      <slot name="conversation-secondary" :conversation="{ last_message_id: 84, last_message: 'Hello' }" />
      <slot name="message-secondary" :message="{ id: 42, message: 'Hello' }" />
      <slot
        name="conversation-extension"
        :adoptDraft="adoptDraft"
        :adoptAttachment="adoptAttachment"
        :adoptMediaIntent="adoptMediaIntent"
      />
    </div>`,
  },
}))

import YanceNativeHostView from '../YanceNativeHostView.vue'
import type { YanceReplyBrainCandidate } from '../semanticTypes'

const candidates: YanceReplyBrainCandidate[] = Array.from({ length: 6 }, (_, index) => ({
  id: `c${index + 1}`,
  type: 'text',
  label: `候选${index + 1}`,
  draft: `回复 ${index + 1}`,
  humanLikeness: 'pass',
  runtimeState: 'ready',
}))

describe('YanceNativeHostView', () => {
  it('preserves the native Conversation/Dashboard host with header enabled', () => {
    const wrapper = mount(YanceNativeHostView)
    expect(wrapper.getComponent({ name: 'ConversationsView' }).props('layoutHideHeader')).toBe(false)
    expect(wrapper.find('[data-yance-native-host]').exists()).toBe(true)
  })

  it('starts Reply Brain collapsed and expands only the bounded real maximum', async () => {
    const wrapper = mount(YanceNativeHostView, { props: { replyCandidates: candidates } })
    expect(wrapper.get('[data-yance-reply-toggle]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(0)
    await wrapper.get('[data-yance-reply-toggle]').trigger('click')
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(3)
    await wrapper.get('[data-yance-more-candidates]').trigger('click')
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(5)
  })

  it.each([0, 1, 2, 3])('renders exactly %i real candidates without padding', async (count) => {
    const wrapper = mount(YanceNativeHostView, { props: { replyCandidates: candidates.slice(0, count) } })
    await wrapper.get('[data-yance-reply-toggle]').trigger('click')
    expect(wrapper.findAll('[data-yance-reply-candidate]')).toHaveLength(count)
  })

  it('adopts text only into the native draft seam', async () => {
    adoptDraftSpy.mockClear(); adoptAttachmentSpy.mockClear(); adoptMediaIntentSpy.mockClear()
    const wrapper = mount(YanceNativeHostView, { props: { replyCandidates: [candidates[0]] } })
    await wrapper.get('[data-yance-reply-toggle]').trigger('click')
    await wrapper.get('[data-yance-adopt]').trigger('click')
    expect(adoptDraftSpy).toHaveBeenCalledWith(candidates[0].draft)
    expect(adoptAttachmentSpy).not.toHaveBeenCalled()
    expect(adoptMediaIntentSpy).not.toHaveBeenCalled()
  })

  it('adopts a materialized media candidate into the native attachment seam and never sends', async () => {
    adoptDraftSpy.mockClear(); adoptAttachmentSpy.mockClear(); adoptMediaIntentSpy.mockClear()
    const media: YanceReplyBrainCandidate = {
      ...candidates[0],
      id: 'image-asset',
      type: 'image',
      attachmentId: 77,
      runtimeState: 'ready',
    }
    const wrapper = mount(YanceNativeHostView, { props: { replyCandidates: [media] } })
    await wrapper.get('[data-yance-reply-toggle]').trigger('click')
    await wrapper.get('[data-yance-adopt]').trigger('click')
    expect(adoptAttachmentSpy).toHaveBeenCalledWith(77)
    expect(adoptDraftSpy).not.toHaveBeenCalled()
    expect(adoptMediaIntentSpy).not.toHaveBeenCalled()
    expect(wrapper.emitted('send')).toBeUndefined()
  })

  it('adopts provider-pending multimodal intent into Composer staging without fabricating an attachment', async () => {
    adoptDraftSpy.mockClear(); adoptAttachmentSpy.mockClear(); adoptMediaIntentSpy.mockClear()
    const media: YanceReplyBrainCandidate = {
      ...candidates[0],
      id: 'video-intent',
      type: 'video',
      runtimeState: 'runtime-pending',
      draft: '做一个简短视频回复',
    }
    const wrapper = mount(YanceNativeHostView, { props: { replyCandidates: [media] } })
    await wrapper.get('[data-yance-reply-toggle]').trigger('click')
    await wrapper.get('[data-yance-adopt]').trigger('click')
    expect(adoptMediaIntentSpy).toHaveBeenCalledWith({
      type: 'video',
      label: media.label,
      prompt: media.draft,
      runtimeState: 'runtime-pending',
    })
    expect(adoptAttachmentSpy).not.toHaveBeenCalled()
    expect(adoptDraftSpy).not.toHaveBeenCalled()
  })

  it('projects the same exact-identity translation map into timeline and rail weak layers', () => {
    const wrapper = mount(YanceNativeHostView, {
      props: {
        translationsByMessageId: {
          '42': { messageId: 42, status: 'success', text: '时间线中文' },
          '84': { messageId: 84, status: 'success', text: '列表中文' },
        },
      },
    })
    expect(wrapper.text()).toContain('时间线中文')
    expect(wrapper.get('[data-yance-rail-translation-secondary]').text()).toContain('列表中文')
  })

  it('starts Girlfriend Brain off and keeps its existing modal composition', async () => {
    const wrapper = mount(YanceNativeHostView)
    expect(wrapper.get('[data-yance-girlfriend-toggle]').attributes('aria-pressed')).toBe('false')
    await wrapper.get('[data-yance-girlfriend-toggle]').trigger('click')
    expect(wrapper.get('[data-yance-girlfriend-toggle]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-yance-girlfriend-native]').exists()).toBe(true)
  })
})
