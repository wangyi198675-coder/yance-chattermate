/** Derived exclusively from native ChannelAccount.is_active; no status shadow. */
export const lineAccountState = (accounts: ReadonlyArray<{ is_active: boolean }>) => {
  const inactiveCount = accounts.filter(account => !account.is_active).length
  return {
    connected: accounts.some(account => account.is_active),
    needsAttention: inactiveCount > 0,
    inactiveCount,
  }
}
