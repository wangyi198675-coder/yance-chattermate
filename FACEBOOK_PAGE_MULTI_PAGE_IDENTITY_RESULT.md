# FACEBOOK_PAGE_MULTI_PAGE_IDENTITY_RESULT

Status: PASS

Branch: `fix/facebook-page-thin-native-extension-20261005`
Base: `fca3b80ccdb0988adc44eee544339eb0c3d25324`
Implementation commit: `740ff0b7851b81644820bce36f9197d4a3002e89`

## Root cause

Messenger PSIDs are Page-scoped, but the pre-change fallback Customer identity was generated as:

`{PSID}@messenger.channel`

That omitted the Page/account scope. Inside one organization, Page A + PSID `123` and Page B + PSID `123` therefore resolved through the same unique Customer email and could merge incorrectly.

## Narrow fix

The existing ChatterMate `Customer` remains the only canonical person authority. Messenger fallback identity now includes the connected Page ID:

`{PAGE_ID}.{PSID}@messenger.channel`

No Facebook contacts table, identity mirror, provider registry, or cross-page merge subsystem was added.

Existing `ChannelConversation` already scopes provider conversations by `channel_account_id`; no schema change was needed there.

## Evidence

The regression test constructs two Messenger `ChannelAccount` rows, PAGE_A and PAGE_B, both receiving PSID `123`, and proves they resolve to different canonical Customer rows.

Realtime duplicate/retry identity is also Page/account scoped. The Meta webhook calls the existing dedupe helper with:

`channel_type + account.id + external_message_id`

A dedicated regression test proves the same `mid.same` and same `PSID123` on PAGE_A/PAGE_B generate different dedupe keys and both messages proceed independently.

Cross-Page merging is intentionally not inferred from raw PSID equality. Any future merge must use an explicit canonical identity/merge authority.
