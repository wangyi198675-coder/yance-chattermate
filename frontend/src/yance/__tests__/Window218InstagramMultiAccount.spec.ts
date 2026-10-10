import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), 'utf8')

describe('Window 218 Instagram native multi-account isolation', () => {
  it('retains Instagram Login, not Facebook Page OAuth or a second registry', () => {
    const signup = read('../../composables/useMetaSignup.ts')
    const service = read('../../services/channels.ts')
    expect(signup).toContain('runInstagramLogin')
    expect(signup).toContain('connectInstagramLogin(code, redirectUri, reconnectAccountId)')
    expect(service).toContain("/channels/meta/instagram/login/connect")
    expect(service).toContain('reconnect_account_id: reconnectAccountId')
  })

  it('Settings renders and modifies accounts individually', () => {
    const settings = read('../../views/settings/IntegrationsSettings.vue')
    expect(settings).toContain('v-for="ig in instagramAccounts"')
    expect(settings).toContain('ig.external_account_id')
    expect(settings).toContain("showDisconnectConfirmation('instagram', ig.id)")
    expect(settings).toContain('await channelsService.disconnectMeta(accountId)')
    expect(settings).toContain('Connect another Instagram account')
    expect(settings).not.toContain("disconnectChannelAccounts('instagram', 'Instagram')")
  })

  it('reconnect propagates selected target and hides legacy manual Page-token fallback', () => {
    const modal = read('../../components/integrations/MetaChannelConnect.vue')
    expect(modal).toContain('reconnectAccountId: props.reconnectAccount?.id')
    expect(modal).toContain('v-if="!reconnectAccount"')
    expect(modal).toContain('v-else-if="!reconnectAccount"')
  })
})
