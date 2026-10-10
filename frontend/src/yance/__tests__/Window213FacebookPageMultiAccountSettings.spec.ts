import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('Window 213 Facebook Page multi-account Settings gate', () => {
  it('renders every Messenger ChannelAccount explicitly instead of choosing a hidden default', () => {
    const settings = read('../../views/settings/IntegrationsSettings.vue')

    expect(settings).toContain('data-messenger-account-selector')
    expect(settings).toContain('v-for="account in accountsFor(\'messenger\')"')
    expect(settings).toContain(':data-channel-account-id="account.id"')
    expect(settings).toContain("openMetaAccount('messenger', account)")
    expect(settings).toContain("account.is_active ? 'Connected' : 'Needs attention'")
    expect(settings).not.toContain('handleDisconnectMessenger')
  })

  it('keeps add-page on the existing Facebook Login for Business path', () => {
    const settings = read('../../views/settings/IntegrationsSettings.vue')
    const meta = read('../../components/integrations/MetaChannelConnect.vue')
    const signup = read('../../composables/useMetaSignup.ts')

    expect(settings).toContain('data-add-facebook-page')
    expect(settings).toContain("openMetaAccount('messenger', null)")
    expect(meta).toContain("v-if=\"channel !== 'messenger'\"")
    expect(meta).toContain('data-messenger-login-unavailable')
    expect(signup).toContain('runBusinessLogin')
    expect(signup).toContain('listMessengerSignupPages')
    expect(signup).toContain('connectMessengerSignup')
  })

  it('disconnects one exact Facebook Page and preserves sibling account rows', () => {
    const settings = read('../../views/settings/IntegrationsSettings.vue')

    expect(settings).toContain("showDisconnectConfirmation('messenger', account)")
    expect(settings).toContain('data-disconnect-facebook-page')
    expect(settings).toContain('await channelsService.disconnectMeta(account.id)')
    expect(settings).toContain(
      'channelAccounts.value = channelAccounts.value.filter(candidate => candidate.id !== account.id)',
    )
    expect(settings).toContain('Other connected Pages stay unchanged.')
    expect(settings).toContain('Leave sibling Facebook Pages, credentials, and conversations untouched')
  })

  it('does not introduce a second Facebook owner or persistence surface', () => {
    const settings = read('../../views/settings/IntegrationsSettings.vue')
    const signup = read('../../composables/useMetaSignup.ts')

    expect(settings + signup).not.toMatch(
      /YanceFacebookAccountManager|YanceMetaOAuthRuntime|YanceFacebookAccountDB|localStorage|indexedDB/i,
    )
  })
})
