import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('Window 16 Home + People no-duplicate-owner structural gate', () => {
  it('keeps /yance on the admitted native host and gives Home only its thin route', () => {
    const router = read('../../router/index.ts')
    expect(router).toContain("path: '/yance/home'")
    expect(router).toContain("component: () => import('@/yance/YanceHomeNativeComposition.vue')")
    expect(router).toContain("path: '/yance'")
    expect(router).toContain("component: () => import('@/yance/YanceNativeHostView.vue')")
    expect(router).not.toContain("component: () => import('@/yance/YanceShellView.vue')")
    const nativeHost = read('../YanceNativeHostView.vue')
    expect(nativeHost).toContain('data-yance-home-entry')
    expect(nativeHost).toContain('href="/yance/home"')
    expect(nativeHost).not.toContain('YanceShellView')
  })

  it('builds Home from the native Inbox query and existing ChatterMate primitives', () => {
    const home = read('../YanceHomeNativeComposition.vue')
    expect(home).toContain("import DashboardLayout from '@/layouts/DashboardLayout.vue'")
    expect(home).toContain("import ChannelBadge from '@/components/common/ChannelBadge.vue'")
    expect(home).toContain("import HandlerBadge from '@/components/conversations/HandlerBadge.vue'")
    expect(home).toContain("import { useConversationsList } from '@/composables/useConversationsList'")
    expect(home).toContain("chatService.getRecentChats({ limit: 12, status: 'all' })")
    expect(home).not.toMatch(/peopleService|defineStore|createPinia|localStorage|sessionStorage/)
    expect(home).not.toMatch(/YanceShellView|<textarea|yance-theme|--yance-/)
  })

  it('keeps native PeopleView and PersonDetailDrawer as the list/detail owners', () => {
    const people = read('../../views/PeopleView.vue')
    const drawer = read('../../components/people/PersonDetailDrawer.vue')
    expect(people).toContain("PersonDetailDrawer")
    expect(people).toContain("peopleService.listPeople")
    expect(people).toContain("personProfileLine")
    expect(drawer).toContain("peopleService.getPerson")
    expect(drawer).toContain("data-person-profile-projection")
    expect(people + drawer).not.toMatch(/defineStore|createPinia|ContactStore|ProfileStore/)
  })

  it('keeps profile storage a bounded projection instead of a second persistence owner', () => {
    const schema = read('../../../../backend/app/models/schemas/people.py')
    const peopleRepo = read('../../../../backend/app/repositories/people.py')
    expect(schema).toContain('Customer.meta_data.person_profile')
    expect(schema).toContain('def project_person_profile(')
    expect(peopleRepo).toContain('project_person_profile(customer.meta_data)')
    expect(schema + peopleRepo).not.toMatch(/create_table|ProfileModel|ContactProfile|profile_repository/i)
  })
})
