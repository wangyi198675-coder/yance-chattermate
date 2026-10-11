import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('Window 23 Frozen Settings native composition structural gate', () => {
  it('keeps /yance native-hosted and adds a thin Frozen Settings route without reactivating YanceShellView', () => {
    const router = read('../../router/index.ts')
    expect(router).toContain("path: '/yance/settings'")
    expect(router).toContain(
      "component: () => import('@/yance/YanceSettingsNativeComposition.vue')",
    )
    expect(router).toContain("path: '/yance'")
    expect(router).toContain("component: () => import('@/yance/YanceNativeHostView.vue')")
    expect(router).not.toContain("component: () => import('@/yance/YanceShellView.vue')")

    const wiring = read('../capabilityWiring.ts')
    expect(wiring).toContain("settings: '/yance/settings'")
  })

  it('routes executable Settings concerns to existing native owners rather than cloned settings implementations', () => {
    const settings = read('../YanceSettingsNativeComposition.vue')
    expect(settings).toContain('to="/yance/platform-accounts"')
    expect(settings).toContain('to="/yance/manage/ai"')
    expect(settings).toContain('to="/yance/manage/user"')
    expect(settings).toContain('to="/yance/manage/organization"')
    expect(settings).toContain("import { useTheme, type ThemeMode } from '@/composables/useTheme'")
    expect(settings).toContain("import { useAISetup } from '@/composables/useAISetup'")
    expect(settings).toContain("import { useNotificationSettings } from '@/composables/useNotificationSettings'")
    expect(settings).toContain("import channelsService")
    expect(settings).toContain('data-native-owner="IntegrationsSettings"')
    expect(settings).toContain('data-native-owner="AIConfigSettings"')
    expect(settings).toContain('data-native-owner="UserSettingsNotifications"')
    expect(settings).toContain('data-native-owner="useTheme"')
  })

  it('proves AI, integration, notification/user, organization and theme owners remain the ChatterMate native implementations', () => {
    const ai = read('../../views/settings/AIConfigSettings.vue')
    const integrations = read('../../views/settings/IntegrationsSettings.vue')
    const user = read('../../components/user/UserSettings.vue')
    const organization = read('../../components/organization/Organizations.vue')
    const theme = read('../../composables/useTheme.ts')

    expect(ai).toContain("import AISetup from '@/components/ai/AISetup.vue'")
    expect(integrations).toContain('import channelsService')
    expect(integrations).toContain(
      "import TelegramConnectModal from '@/components/integrations/TelegramConnectModal.vue'",
    )
    expect(integrations).toContain(
      "import MetaChannelConnect from '@/components/integrations/MetaChannelConnect.vue'",
    )
    expect(integrations).toContain(
      "import ChannelConnectModal from '@/components/integrations/ChannelConnectModal.vue'",
    )
    expect(user).toContain('useNotificationSettings')
    expect(organization).toContain('useOrganizationSettings')
    expect(organization).toContain('v-model="formData.timezone"')
    expect(organization).toContain("applyPreset('always')")
    expect(organization).toContain('Outside these hours, AI handles every chat.')
    expect(theme).toContain("const STORAGE_KEY = 'cm-theme'")
  })

  it('projects admitted Translation and runtime health while keeping unavailable families truthful', () => {
    const settings = read('../YanceSettingsNativeComposition.vue')
    expect(settings).toContain('translationService.health()')
    expect(settings).toContain('data-native-owner="backend /health"')
    expect(settings).toContain('data-settings-runtime-state="memory-readonly"')
    expect(settings).toContain('data-settings-runtime-state="voice-media-runtime-unverified"')
    expect(settings).not.toMatch(/memoryService|voiceService|mediaService|backupService|updateService/)
  })

  it('does not create a second settings/provider/integration/notification/organization/theme owner or persistence surface', () => {
    const settings = read('../YanceSettingsNativeComposition.vue')
    expect(settings).not.toMatch(
      /defineStore|createPinia|YanceSettingsStore|YanceSettingsRouter|ProviderRegistry|IntegrationManager|NotificationStore|OrganizationStore|ThemeStore/i,
    )
    expect(settings).not.toMatch(
      /localStorage|sessionStorage|indexedDB|create_table|migration|schema/i,
    )
    expect(settings).not.toMatch(/--yance-|!important|custom_css/i)
  })

  it('hides commercial presentation from Frozen Settings without deleting upstream routes', () => {
    const settings = read('../YanceSettingsNativeComposition.vue')
    const router = read('../../router/index.ts')
    expect(settings).not.toContain('/settings/subscription')
    expect(settings).not.toContain('/settings/subscription/setup')
    expect(router).toContain("path: '/settings/subscription'")
    expect(router).toContain("path: '/settings/subscription/setup/:planId'")
    expect(router).toContain("path: '/settings/widget-apps'")
  })

  it('keeps Window 14/16 Conversation, Home and People native ownership intact', () => {
    const host = read('../YanceNativeHostView.vue')
    const home = read('../YanceHomeNativeComposition.vue')
    const people = read('../../views/PeopleView.vue')
    expect(host).toContain('ConversationsView')
    expect(home).toContain("chatService.getRecentChats({ limit: 12, status: 'all' })")
    expect(people).toContain('PersonDetailDrawer')
    expect(home).toContain("router.push('/yance/settings')")
  })
})
