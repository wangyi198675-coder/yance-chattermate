import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import YanceReplyBrainCandidateCard from '../components/YanceReplyBrainCandidateCard.vue'
import type { YanceReplyBrainCandidate } from '../semanticTypes'

const baseCandidate: YanceReplyBrainCandidate = {
  id: 'c1',
  type: 'text',
  label: '自然回复',
  draft: '你好',
  why: '上下文一致',
  evidence: ['latest-turn'],
  humanLikeness: 'pass',
  runtimeState: 'ready',
}

describe('YanceReplyBrainCandidateCard', () => {
  it('adopts text only after the Human-Likeness gate and never emits a send event', async () => {
    const wrapper = mount(YanceReplyBrainCandidateCard, { props: { candidate: baseCandidate } })
    const adopt = wrapper.get('[data-yance-adopt]')
    expect(adopt.attributes('data-adoption-kind')).toBe('text-draft')
    await adopt.trigger('click')
    expect(wrapper.emitted('adopt')?.[0]).toEqual([baseCandidate])
    expect(wrapper.emitted('send')).toBeUndefined()
  })

  it.each(['review', 'blocked', 'unknown'] as const)('fails closed when Human-Likeness is %s', async (humanLikeness) => {
    const wrapper = mount(YanceReplyBrainCandidateCard, {
      props: { candidate: { ...baseCandidate, humanLikeness } },
    })
    const adopt = wrapper.get('[data-yance-adopt]')
    expect(adopt.attributes('disabled')).toBeDefined()
    await adopt.trigger('click')
    expect(wrapper.emitted('adopt')).toBeUndefined()
  })

  it.each(['voice', 'photo', 'image', 'video', 'file'] as const)(
    'keeps %s preview and adopts a provider-pending generation intent into Composer staging',
    async (type) => {
      const candidate: YanceReplyBrainCandidate = {
        ...baseCandidate,
        id: type,
        type,
        runtimeState: undefined,
      }
      const wrapper = mount(YanceReplyBrainCandidateCard, { props: { candidate } })
      const preview = wrapper.get('[data-yance-modality-preview]')
      expect(preview.attributes('data-modality')).toBe(type)
      expect(preview.attributes('data-runtime-state')).toBe('runtime-pending')
      expect(preview.attributes('data-adoption-kind')).toBe('generation-intent')
      const adopt = wrapper.get('[data-yance-adopt]')
      expect(adopt.attributes('disabled')).toBeUndefined()
      await adopt.trigger('click')
      expect(wrapper.emitted('adopt')?.[0]).toEqual([candidate])
      expect(wrapper.emitted('send')).toBeUndefined()
    },
  )

  it('adopts a materialized canonical FileAttachment even while its generation provider is unavailable', async () => {
    const candidate: YanceReplyBrainCandidate = {
      ...baseCandidate,
      type: 'image',
      attachmentId: 321,
      runtimeState: 'unavailable',
    }
    const wrapper = mount(YanceReplyBrainCandidateCard, { props: { candidate } })
    expect(wrapper.get('[data-yance-modality-preview]').attributes('data-adoption-kind')).toBe('attachment')
    await wrapper.get('[data-yance-adopt]').trigger('click')
    expect(wrapper.emitted('adopt')?.[0]).toEqual([candidate])
  })

  it('disables adoption only when the admitted owner/runtime is unavailable', async () => {
    const candidate: YanceReplyBrainCandidate = {
      ...baseCandidate,
      type: 'video',
      runtimeState: 'unavailable',
    }
    const wrapper = mount(YanceReplyBrainCandidateCard, { props: { candidate } })
    expect(wrapper.get('[data-yance-modality-preview]').attributes('data-runtime-state')).toBe('unavailable')
    const adopt = wrapper.get('[data-yance-adopt]')
    expect(adopt.attributes('disabled')).toBeDefined()
    await adopt.trigger('click')
    expect(wrapper.emitted('adopt')).toBeUndefined()
  })
})
