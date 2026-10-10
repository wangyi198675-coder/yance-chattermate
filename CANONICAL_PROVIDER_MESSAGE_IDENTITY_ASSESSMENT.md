# CANONICAL_PROVIDER_MESSAGE_IDENTITY_ASSESSMENT

Status: ASSESSED. `FACEBOOK_PAGE_HISTORY_BACKFILL = NATIVE_GAP`. No backfill implementation was added in this round.

Branch: `fix/facebook-page-thin-native-extension-20261005`
Base: `fca3b80ccdb0988adc44eee544339eb0c3d25324`
Implementation commit: `740ff0b7851b81644820bce36f9197d4a3002e89`

## Canonical realtime identity

For Messenger inbound user messages the provider identity now carried into canonical `ChatHistory.attributes` is:

`(channel, external_account_id, external_message_id)`

For Facebook Page this is effectively:

`(messenger, Page ID, Messenger MID)`

This is the correct identity scope because Messenger PSIDs and message delivery belong to a Page/account context. `ChannelConversation` remains the canonical conversation mapping and `Customer` remains the canonical person authority.

## Existing retry protection

The existing Meta webhook performs transient Redis SETNX dedupe. The key passed to the helper contains `account.id:external_message_id`, and the helper prefixes channel type. TTL is one hour. A regression test proves two Pages receiving the same MID do not collide.

This is sufficient for ordinary webhook redelivery suppression but is not durable history/backfill idempotence because:
- Redis TTL expires.
- Redis absence/failure is intentionally fail-open.
- `ChatHistory.attributes` currently has no database-enforced provider identity uniqueness.

## Future backfill direction, proposal only

`THIN_HISTORY_BACKFILL_ADAPTER_CANDIDATE` may later ingest provider history only through the same ChatterMate channel-processing and canonical `ChatHistory` authority. It must not create a replay DB, sync DB, Facebook mirror, second message table, or second message owner.

Before enabling historical backfill, add a durable uniqueness contract on canonical inbound provider identity. Preferred candidates for Master review are:

1. A minimal PostgreSQL partial/expression unique index over canonical `ChatHistory` provider attributes (`channel`, `external_account_id`, `external_message_id`) for inbound user rows with a provider MID; or
2. If cross-database portability makes the JSON expression unsuitable, nullable first-class provider identity columns on `ChatHistory` with a scoped unique index.

No schema/index/migration is implemented by Window 10. The proposal must be separately admitted before any backfill worker is allowed.

## Recovery/health audit

Existing native capabilities already provide:
- token validation during Messenger connect via `debug_token`;
- existing reconnect/upsert of `ChannelAccount` credentials;
- provider error propagation via existing `graph_post` / `SendResult`;
- existing `ChannelAccount.settings` JSON as a possible native location for future non-secret event-driven health markers.

Current gap:
- subscription failure is logged but not persisted as `last_provider_error` / `reconnect_required`;
- send failures are surfaced to the caller but are not persisted as account health state.

No health daemon, polling scheduler, recovery service, or periodic Facebook owner is justified merely to record errors that are already observed during connect/send. If Master later requires proactive expiry detection before any user action or provider event, that requirement is `NEEDS_PERIODIC_OWNER` and must be separately owned; it is not implemented here.
