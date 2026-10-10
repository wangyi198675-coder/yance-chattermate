import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')
const settings = read('../../views/settings/IntegrationsSettings.vue')
const meta = read('../../components/integrations/MetaChannelConnect.vue')
const signup = read('../../composables/useMetaSignup.ts')

describe('W292 consolidated cross-channel Settings regression', () => {
  it('keeps five distinct account-level controls, including admitted LINE', () => {
    expect(settings).toContain('data-line-account-list')
    expect(settings).toContain("accountsFor('line')")
    expect(settings).toContain("accountsFor('slack')")
    expect(settings).toContain("accountsFor('messenger')")
    expect(settings).toContain('v-for="ig in instagramAccounts"')
    expect(settings).toContain('v-for="account in accountsFor(\'whatsapp\')"')
    expect(settings).toContain('disconnectWhatsAppAccount')
    expect(settings).toContain('disconnectMessengerPage(disconnectingAccount)')
    expect(settings).toContain("showDisconnectConfirmation('instagram', ig.id)")
    expect(settings).toContain('confirmSlackDisconnect(account)')
    expect(settings).toContain('showLineDisconnect(account)')
  })

  it('preserves truthful inactive and exact-identity behavior without a second status owner', () => {
    expect(settings).toContain('whatsappAccountUsable')
    expect(settings).toContain("connected: accountsFor('slack').some(a => a.is_active)")
    expect(settings).toContain("needsAttention: accountsFor('slack').some(a => !a.is_active)")
    expect(settings).toContain("channel === 'instagram' && accounts.some(a => !a.is_active)")
    expect(settings).toContain("integration.id === 'slack' && accountsFor('slack').length > 0")
    expect(settings).toContain('messengerState.value.connected')
    expect(settings).toContain('Needs attention')
    expect(settings).toContain('Not configured')
    expect(settings).toContain('messengerPageEpochs')
    expect(settings).toContain('reconnectWhatsAppAccount')
    expect(settings).toContain('replaceChannelAccount(updated)')
    expect(meta).toContain('reconnectAccountId: props.reconnectAccount?.id')
    expect(signup).toContain('onConnectionFailed?.')
    expect(signup).toContain('connectInstagramLogin(code, redirectUri, reconnectAccountId)')
    expect(settings).not.toContain("disconnectChannelAccounts('instagram', 'Instagram')")
    expect(settings).not.toContain('handleDisconnectMessenger')
    expect(settings).not.toMatch(/localStorage|indexedDB|YanceSocialChannelStatusDB/)
  })
})
