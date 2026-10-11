import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const read = (file: string) => readFileSync(resolve(process.cwd(), 'src/components/faq', file), 'utf8')
describe('W461 native FAQ Help Center Chinese (preserves source CRUD and plan owner)', () => {
  it('renders Chinese empty, generation and import actions while preserving event contracts', () => {
    const b = read('FaqGenerateBar.vue')
    const empty = read('FaqEmptyState.vue')
    for (const v of ['正在生成常见问题','常见问题已准备好发布','生成常见问题','读取','个页面','导入','添加常见问题'])
      expect(b).toContain(v)
    for (const v of ['暂无常见问题','从知识库生成','导入已有常见问题','手动添加'])
      expect(empty).toContain(v)
    for (const evt of ["$emit('generate')","$emit('import')","$emit('add')"]) {
      expect(b).toContain(evt)
      expect(empty).toContain(evt)
    }
    for (const english of ['No FAQs yet','Generate from knowledge base','Reading from {{ sourceCount }} sources','Generating FAQs…','FAQs ready to publish'])
      expect(b + empty).not.toContain(english)
  })
  it('translates workspace status, bulk actions, confirmations and search without changing native backend function calls', () => {
    const s = read('FaqWorkspace.vue')
    for (const label of ['删除常见问题','生成常见问题','常见问题','外观与设置','已发布','草稿','全部主题','搜索问题和答案','显示 {{ filteredCount }}','正在加载设置','清除筛选','取消发布'])
      expect(s).toContain(label)
    for (const fn of ['useFaqWorkspace(', 'startGeneration(', 'bulkDelete()', 'togglePublish(', '@save="saveEdit"', 'deleteFaq(', 'submitImport(', 'refresh()'])
      expect(s).toContain(fn)
    for (const old of ['No FAQs match your filters.','Delete FAQ','Published articles will disappear','Search questions & answers…','Loading your FAQs…'])
      expect(s).not.toContain(old)
  })
  it('localizes feature gate without changing current plan entitlement or pricing authority', () => {
    const s = read('FaqProLockOverlay.vue')
    expect(s).toContain('升级 Pro 后自动生成常见问题')
    expect(s).toContain('比较套餐')
    expect(s).toContain('$39')
    expect(s).toContain("subscriptionStorage.hasFeature('help_center')")
    expect(s).toContain('props.planAllowed === false')
    expect(s).toContain("router.push('/settings/subscription')")
  })
})
