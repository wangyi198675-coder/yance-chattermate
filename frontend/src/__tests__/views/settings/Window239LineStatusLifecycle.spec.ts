import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { lineAccountState } from '@/utils/lineAccountState'

const vue = readFileSync('src/views/settings/IntegrationsSettings.vue', 'utf8')
const yance = readFileSync('src/yance/YanceSettingsNativeComposition.vue', 'utf8')

describe('Window239 LINE native ChannelAccount status and per-account UI', () => {
  it('never reports inactive-only accounts as connected', () => {
    expect(lineAccountState([{ is_active: false }])).toEqual({
      connected: false,
      needsAttention: true,
      inactiveCount: 1,
    })
    expect(lineAccountState([])).toEqual({
      connected: false,
      needsAttention: false,
      inactiveCount: 0,
    })
  })

  it('truthfully reports mixed accounts as connected plus attention', () => {
    expect(lineAccountState([{ is_active: true }, { is_active: false }])).toEqual({
      connected: true,
      needsAttention: true,
      inactiveCount: 1,
    })
    expect(lineAccountState([{ is_active: true }, { is_active: true }])).toEqual({
      connected: true,
      needsAttention: false,
      inactiveCount: 0,
    })
  })

  it('wires the canonical status projection and keeps inactive accounts manageable', () => {
    expect(vue).toContain("channel === 'line' ? lineAccountState(accounts) : null")
    expect(vue).toContain('connected: lineState ? lineState.connected : accounts.length > 0')
    expect(vue).toContain('v-else-if="integration.needsAttention"')
    expect(vue).toContain("integration.id === 'line' && accountsFor('line').length > 0")
    expect(vue).toContain("account.is_active ? 'Connected' : 'Needs attention'")
    expect(vue).toContain('@click="manageLineAccount(account)"')
    expect(vue).toContain('@click="showLineDisconnect(account)"')
    expect(vue).toContain('@click="addLineAccount"')
    expect(vue).toContain('await channelsService.disconnectLine(account.id)')
    expect(yance).toContain("else if (active.length > 0) state = 'Connected'")
    expect(yance).toContain("else if (accounts.length > 0) state = 'Needs attention'")
    expect(yance).toContain("platform.type === 'line' && platform.accounts.length > platform.active.length")
  })
})
