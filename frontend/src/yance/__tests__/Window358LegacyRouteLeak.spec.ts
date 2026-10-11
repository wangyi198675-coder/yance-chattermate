import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const source = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('W358 exact-7efc Yance legacy navigation isolation', () => {
  const home = source('../YanceHomeNativeComposition.vue')
  const world = source('../YanceRelationshipWorld.vue')
  const settings = source('../YanceSettingsNativeComposition.vue')
  const wiring = source('../capabilityWiring.ts')
  const router = source('../../router/index.ts')
  const people = source('../YancePeopleDirectory.vue')
  const accounts = source('../YancePlatformAccounts.vue')
  const advanced = source('../YanceNativeSettingsTool.vue')

  it('repairs all 16 original product-owned upstream link destinations', () => {
    expect(home.match(/router.push\('\/yance\/people'\)/g)).toHaveLength(1)
    expect(home.match(/router.push\('\/yance\/platform-accounts'\)/g)).toHaveLength(4)
    expect(world.match(/router.push\('\/yance\/people'\)/g)).toHaveLength(3)
    expect(settings.match(/to="\/yance\/platform-accounts"/g)).toHaveLength(2)
    expect(settings.match(/to="\/yance\/manage\/ai"/g)).toHaveLength(2)
    expect(settings.match(/to="\/yance\/manage\/user"/g)).toHaveLength(3)
    expect(settings.match(/to="\/yance\/manage\/organization"/g)).toHaveLength(1)
    const product = [home, world, settings, wiring].join('\n')
    expect(product).not.toMatch(/(?:push\(|to="|:\s*)['"]\/(?:people|conversations|settings\/(?:integrations|ai-config|user|organization))['"]/)
  })

  it('resolves only Yance-scoped product routes with existing auth guard and no replacement shell', () => {
    for (const path of ['/yance/people','/yance/platform-accounts','/yance/manage/:tool(ai|user|organization)']) {
      expect(router).toContain(`path: '${path}'`)
    }
    expect(router).toContain("component: () => import('@/yance/YancePeopleDirectory.vue')")
    expect(router).toContain("component: () => import('@/yance/YancePlatformAccounts.vue')")
    expect(router).toContain("component: () => import('@/yance/YanceNativeSettingsTool.vue')")
    expect(wiring).toContain("home: '/yance/home'")
    expect(wiring).toContain("conversation: '/yance'")
    expect(wiring).toContain("relationship: '/yance/relationship'")
    expect(router).not.toContain("component: () => import('@/yance/YanceShellView.vue')")
  })

  it('reuses authoritative native People and platform ChannelAccount lifecycle', () => {
    expect(people).toContain('peopleService.listPeople(')
    expect(people).toContain("router.push('/yance/relationship/'")
    expect(people).toContain('正在读取真实人物资料')
    expect(people).toContain('人物目录读取失败')
    expect(accounts).toContain('channelsService.listAccounts()')
    expect(accounts).toContain('MetaChannelConnect')
    expect(accounts).toContain('TelegramConnectModal')
    expect(accounts).toContain('ChannelConnectModal')
    expect(accounts).toContain('channelsService.disconnectWhatsApp(account.id)')
    expect(accounts).toContain('window.confirm(')
    expect(accounts).toContain('channelsService.getSlackInstallUrl()')
    expect(accounts).toContain('@keydown.esc="closeModal"')
    expect(accounts).toContain('未验证实时收发')
    expect(settings).toContain('provider_health')
    expect(settings).toContain("persona: 'Verification pending'")
    expect(advanced).toContain('data-yance-advanced-consent')
    expect(advanced).toContain('AISetup')
    expect(advanced).toContain('UserSettings')
    expect(advanced).toContain('Organizations')
    expect([people,accounts,advanced].join('\n')).not.toMatch(/createPinia|defineStore|localStorage|sessionStorage|new\s+WebSocket|indexedDB/)
  })
})
