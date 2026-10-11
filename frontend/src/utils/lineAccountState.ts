import type { ChannelAccount } from '@/services/channels'

// Only canonical native ChannelAccount provider health can prove LINE readiness.
// An activated row with missing/unverified health is saved, not Connected.
type LineAccount = Pick<ChannelAccount, 'is_active' | 'provider_health'>

export const lineAccountUsable = (account: LineAccount): boolean => {
  if (!account.is_active) return false
  const health = account.provider_health
  if (!health) return false

  const readiness = health.readiness?.trim().toUpperCase()
  if (readiness !== 'READY' && readiness !== 'HEALTHY') return false
  if (health.reconnect_needed || health.last_provider_error) return false
  if (health.credential_status != null &&
      health.credential_status.trim().toUpperCase() !== 'VALID') return false

  return true
}

export const lineAccountState = (accounts: ReadonlyArray<LineAccount>) => {
  const attentionCount = accounts.filter(account => !lineAccountUsable(account)).length
  return {
    connected: accounts.some(lineAccountUsable),
    needsAttention: attentionCount > 0,
    // Preserve the existing card consumer's property while counting all
    // accounts requiring attention, not just those with is_active=false.
    inactiveCount: attentionCount,
  }
}
