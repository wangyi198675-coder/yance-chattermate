/** A read-only projection of the native Messenger ChannelAccount rows. */
export function facebookMessengerConnectionState(
  accounts: ReadonlyArray<{ is_active: boolean }>,
): { connected: boolean; label: 'Connected' | 'Needs attention' | 'Not configured' } {
  const connected = accounts.some(account => account.is_active === true)
  return {
    connected,
    label: connected ? 'Connected' : accounts.length ? 'Needs attention' : 'Not configured',
  }
}
