import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import FaqCategoryGroup from '@/components/faq/FaqCategoryGroup.vue'

describe('W464 FAQ real screenshot provenance/count Chinese', () => {
  it('renders real category counts and publishes in Chinese while retaining numeric state', () => {
    const view = mount(FaqCategoryGroup, {
      props: { category: '业务反馈', count: 1, publishedCount: 1, selectedCount: 0, open: true },
    })
    expect(view.find('.category-group__count').text()).toBe('共 1 条常见问题 · 已发布 1 条')
    expect(view.find('.category-group__check').attributes('aria-label')).toBe('全选业务反馈主题下的常见问题')
    expect(view.find('.category-group__name').text()).toBe('业务反馈')
    expect(view.find('.category-group__check').attributes('checked')).toBeUndefined()
    expect(view.find('.category-group__toggle').attributes('aria-expanded')).toBe('true')
  })
  it('still emits original select and toggle events', async () => {
    const view = mount(FaqCategoryGroup, {props:{category:'主题',count:2,publishedCount:0,selectedCount:0,open:false}})
    await view.find('.category-group__toggle').trigger('click')
    expect(view.emitted('toggle')).toHaveLength(1)
    await view.find('.category-group__check').setValue(true)
    expect(view.emitted('toggle-all')?.[0]).toEqual([true])
    expect(view.find('.category-group__count').text()).toContain('共 2 条常见问题 · 已发布 0 条')
  })
  it('maps only official provenance display labels, not persisted backend provenance or custom source names', () => {
    const source=readFileSync(resolve(process.cwd(),'src/components/faq/FaqCard.vue'),'utf8')
    expect(source).toContain("if (!raw || raw === 'Generated') return '自动生成'")
    expect(source).toContain("if (raw === 'Added manually') return '手动添加'")
    expect(source).toContain('return raw')
    expect(source).toContain('const sourceLabel = ()')
    expect(source).toContain('{{ sourceLabel() }}')
  })
})
