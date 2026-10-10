import { computed, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { facebookMessengerConnectionState } from '../facebookMessengerConnectionState'

const settings = readFileSync(resolve(process.cwd(), 'src/views/settings/IntegrationsSettings.vue'), 'utf8')

describe('Window238 truthful Messenger Page state', () => {
  it('reactively projects zero, inactive-only, active-only, and mixed pages', () => {
    const accounts = ref<Array<{ is_active: boolean }>>([])
    const state = computed(() => facebookMessengerConnectionState(accounts.value))

    expect(state.value).toEqual({ connected: false, label: 'Not configured' })
    accounts.value = [{ is_active: false }, { is_active: false }]
    expect(state.value).toEqual({ connected: false, label: 'Needs attention' })
    accounts.value = [{ is_active: true }]
    expect(state.value).toEqual({ connected: true, label: 'Connected' })
    accounts.value = [{ is_active: true }, { is_active: false }]
    expect(state.value).toEqual({ connected: true, label: 'Connected' })
    accounts.value[0].is_active = false
    expect(state.value).toEqual({ connected: false, label: 'Needs attention' })
  })

  it('wires aggregate status to active native accounts and shows inactive rows', () => {
    // Integrated status also gates WhatsApp on a usable exact phone account.
    expect(settings).toMatch(/connected:\s*channel === 'messenger'\s*\?\s*messengerState\.value\.connected/)
    expect(settings).toMatch(/channel === 'whatsapp'\s*\?\s*accounts\.some\(whatsappAccountUsable\)/)
    expect(settings).toContain('{{ messengerState.label }}')
    expect(settings).toContain(
      "integration.id === 'messenger' && accountsFor('messenger').length > 0",
    )
    expect(settings).toContain("account.is_active ? 'Connected' : 'Needs attention'")
    expect(settings).toContain("v-for=\"account in accountsFor('messenger')\"")
  })

  it('retains Add Facebook Page and exact-page Manage/Disconnect even without active pages', () => {
    expect(settings).toContain('v-else-if="integration.id === \'messenger\'" class="int-actions"')
    expect(settings).toContain('data-add-facebook-page')
    expect(settings).toContain("openMetaAccount('messenger', null)")
    expect(settings).toContain("openMetaAccount('messenger', account)")
    expect(settings).toContain("showDisconnectConfirmation('messenger', account)")
    expect(settings).toContain('await channelsService.disconnectMeta(account.id)')
    expect(settings).not.toContain('handleDisconnectMessenger')
  })
})
