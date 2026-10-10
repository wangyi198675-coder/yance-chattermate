import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('Window 45 Home + Relationship World structural gate', () => {
  it('adds only a thin Relationship World route while preserving native Conversation and People routes', () => {
    const router = read('../../router/index.ts')
    expect(router).toContain("path: '/yance/relationship/:customerId?'")
    expect(router).toContain("component: () => import('@/yance/YanceRelationshipWorld.vue')")
    expect(router).toContain("path: '/yance'")
    expect(router).toContain("component: () => import('@/yance/YanceNativeHostView.vue')")
    expect(router).toContain("path: '/people'")
    expect(router).toContain("component: () => import('../views/PeopleView.vue')")
    expect(router).not.toContain("component: () => import('@/yance/YanceShellView.vue')")
  })

  it('keeps Home on one Inbox projection plus the existing channel-account status API', () => {
    const home = read('../YanceHomeNativeComposition.vue')
    expect(home.match(/chatService\.getRecentChats\(\{ limit: 12, status: 'all' \}\)/g)).toHaveLength(1)
    expect(home).toContain('channelsService.listAccounts()')
    expect(home).toContain('data-home-recent-activity')
    expect(home).toContain('data-home-attention')
    expect(home).toContain('data-home-runtime-exceptions')
    expect(home).toContain("router.push('/yance/platform-accounts')")
    expect(home).not.toMatch(/peopleService|defineStore|createPinia|localStorage|sessionStorage/)
    expect(home).not.toContain('开放事项 5')
    expect(home).not.toContain('关系风险 1')
    expect(home).not.toContain('canonical owners')
    expect(home).not.toContain('第二份 Home 消息库')
  })

  it('keeps Relationship World a read-only projection of the native Person detail', () => {
    const world = read('../YanceRelationshipWorld.vue')
    expect(world).toContain("import { peopleService } from '@/services/people'")
    expect(world).toContain('peopleService.getPerson(customerId.value)')
    expect(world).toContain('data-truth-kind="fact"')
    expect(world).toContain('data-truth-kind="inference"')
    expect(world).toContain('data-truth-kind="derived-insight"')
    expect(world).toContain('data-truth-kind="evidence"')
    expect(world).toContain('data-truth-kind="unavailable-runtime"')
    expect(world).not.toMatch(/defineStore|createPinia|localStorage|sessionStorage|indexedDB/i)
    expect(world).not.toMatch(/peopleService\.(markAsCustomer|updatePerson|syncToCrm)/)
    expect(world).not.toMatch(/api\.(post|put|patch|delete)\(/)
  })

  it('does not materialize Frozen sample relationship intelligence as runtime truth', () => {
    const world = read('../YanceRelationshipWorld.vue')
    expect(world).not.toContain('58/100')
    expect(world).not.toContain('朋友 · 专业交流为主')
    expect(world).not.toContain('喜欢摄影与周末短途旅行')
    expect(world).not.toContain('这个人不要太主动')
    expect(world).toContain('暂不生成关系阶段、关系温度、互动节奏、风险、开放事项、承诺、意图或下一步建议')
  })

  it('keeps the Conversation surface linked to the bounded Relationship World surface', () => {
    const host = read('../YanceNativeHostView.vue')
    expect(host).toContain('data-yance-relationship-entry')
    expect(host).toContain('href="/yance/relationship"')
    expect(host).not.toContain('YanceShellView')
  })
})
