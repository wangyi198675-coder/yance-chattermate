import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import KnowledgePageEditor from '@/components/knowledge/KnowledgePageEditor.vue'
import KnowledgeSourceTree from '@/components/knowledge/KnowledgeSourceTree.vue'
import TicketEmptyState from '@/components/tickets/TicketEmptyState.vue'

describe('W421 native knowledge and ticket Chinese controls retain real events', () => {
  it('shows the genuine empty knowledge source state and emits search input', async () => {
    const wrapper = mount(KnowledgeSourceTree, {
      props: {
        sources: [],
        selectedPageId: null,
        selectedSourceId: null,
        query: '',
        statusOf: () => 'synced' as const,
        pageRowsOf: () => [],
      },
    })
    expect(wrapper.text()).toContain('暂无知识来源')
    const search = wrapper.get('input[type="search"]')
    expect(search.attributes('aria-label')).toBe('搜索页面')
    await search.setValue('退款')
    expect(wrapper.emitted('update:query')?.[0]).toEqual(['退款'])
  })

  it('editing keeps the canonical title/content emit and save enabled', async () => {
    const wrapper = mount(KnowledgePageEditor, {
      props: { title: '原始标题', content: '原文内容', saving: false },
    })
    expect(wrapper.text()).toContain('页面标题')
    expect(wrapper.text()).toContain('页面内容')
    await wrapper.get('#kb-page-title').setValue('新标题')
    expect(wrapper.emitted('update:title')?.[0]).toEqual(['新标题'])
    await wrapper.get('.editor__buttons .btn--primary').trigger('click')
    expect(wrapper.emitted('save')).toHaveLength(1)
  })

  it('the filtered-ticket state exposes a real clear action', async () => {
    const wrapper = mount(TicketEmptyState, { props: { filtered: true } })
    expect(wrapper.text()).toContain('没有符合条件的工单')
    await wrapper.get('button.action').trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
    expect(wrapper.emitted('create')).toBeUndefined()
  })

  it('the empty-ticket state exposes a real create action', async () => {
    const wrapper = mount(TicketEmptyState, { props: { filtered: false } })
    expect(wrapper.text()).toContain('暂无工单')
    await wrapper.get('button.action').trigger('click')
    expect(wrapper.emitted('create')).toHaveLength(1)
    expect(wrapper.emitted('clear')).toBeUndefined()
  })
})
