# Window56 Browser-Assisted Profile Enrichment

This directory is intentionally a thin standards bridge, not a browser automation runtime.

Flow:

1. The user explicitly clicks the extension toolbar action.
2. Manifest V3 `activeTab` grants temporary access to that one current tab.
3. A bundled static extractor reads only admitted identity/name/avatar fields.
4. Unknown/disallowed pages fail closed before Native Messaging.
5. `runtime.sendNativeMessage` launches a one-shot stateless host.
6. The host validates the exact payload again, resolves the existing Messenger
   `ChannelAccount -> ChannelConversation -> Customer` chain, and merges only
   into `Customer.meta_data.person_profile`.

No cookies, passwords, tokens, local/session storage, outerHTML, message history,
browser profile files, Knowledge ingestion, browser DB, queue, broker, daemon,
scheduler, localhost browser-control server, CDP, Playwright, or Business Suite
scraping are used.

## Extension identity

Fixed extension id:

`hfcmihknnigilcafmalchjopmhhkihjf`

Native host:

`com.yance.browser_profile_enrichment`

Manifest permissions are exactly:

- `activeTab`
- `scripting`
- `nativeMessaging`

There are no host permissions.

## Deterministic DOM/URL gate

Admitted origins are only the top-level Facebook/Messenger origins declared in
`extractor.js`. `business.facebook.com` is rejected.

The extractor supports exactly two deterministic identity modes:

- `DIRECT_PROVIDER_USER`: preserves the Window56 shape. The Page/account id is
  independently visible, and the direct-message path id must exactly equal the
  visible Page-scoped provider-user id.
- `CANONICAL_PROVIDER_MESSAGE`: for ordinary Facebook/Messenger shapes where
  `/messages/t/<id>` is Page context rather than contact identity. The extractor
  collects at most five visible `message_id=mid...` href identities whose
  `thread_id` matches that Page context. It never reads message text/body.

The backend always re-validates `page_account_id` against the existing active
Messenger `ChannelAccount.external_account_id`. Canonical-message mode then uses
the existing `ChatHistory(provider_channel, external_account_id, external_message_id)`
identity to converge to exactly one session, one `ChannelConversation`, and one
`Customer`. Unknown, cross-Page, cross-conversation, or conflicting identities
fail closed with no write.

At least one visible display name or https avatar is still required. There is
deliberately no name matching, avatar similarity matching, or fallback guessing.

## Windows Native Messaging

Install for the current Windows user:

`powershell -ExecutionPolicy Bypass -File native_host\install.ps1 -BackendRoot <repo>\backend -PythonExe <python.exe>`

Chrome and Opera both use Chromium Native Messaging and the same Windows
`HKCU\Software\Google\Chrome\NativeMessagingHosts` registration path for this host.

Uninstall:

`powershell -ExecutionPolicy Bypass -File native_host\uninstall.ps1`

The install directory contains only the host script, launcher, and host manifest.
No profile payload is persisted there.
