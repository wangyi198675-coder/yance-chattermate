# W398 WhatsApp PERSONAL Baileys transport — reviewer packet

No deploy. No real account connected. This directory is an optional linked-device PERSONAL WhatsApp adapter, not the ChatterMate WhatsApp Business Cloud API.

## Inherited actual V21 implementation

Old public main SHA: 5c31f8b11dc8d775bc687eaa7cacc37528280eeb.
Actually inspected V21 backend/services/whatsappAdapter.js (132,938 bytes), whatsappAuthResolver.js, whatsappAccountReconciliationService.js, platformDriverRegistry.js, accountRepository.js and package.json. Old source implements real Baileys connection.update QR, creds.update, messages.upsert/messages.update, personal send/media and socket-generation fencing. Old tests identified: whatsappQrChallenge, batch39WhatsappSessionFence, whatsappCanonicalGuardRegression, whatsappMediaRecoveryClosure and whatsappReceiptRecoveryRegression.

Version evidence: old driver pins @whiskeysockets/baileys **7.0.0-rc14** (7 RC). New-project October 5 audit selected **6.7.24** but implemented no new driver. W398 preserves old exact 7.0.0-rc14 in local package.json and package-lock.json; do not silently downgrade/upgrade. Exact-version and unofficial WhatsApp Web client risks remain; install with npm ci --ignore-scripts.

Not copied: old plaintext useMultiFileAuthState, r32SqliteStore, eventBus, custom message queue, second CRM, second account persistence or migration. Legacy credentials are not auto-imported, since that requires separate secure migration authorization.

## Implemented transport and guards

- adapter.py implements existing PersonalSocialTransportAdapter; runner.mjs uses process-local stdin/stdout JSON line pipe (no port, webhook or network listener); core.mjs delegates provider operations to actual Baileys 7.0.0-rc14.
- User-triggered connect only. QR content originates only from actual Baileys connection.update.qr; 60-second expiration, cancel, no static demo login code and no auto-scan. Native UI QR rendering requires a separately authorized consumer.
- Authenticated CONNECTED only on provider connection=open and socket.user.id. Degraded/error on expired QR, canceled socket, provider disconnect or revoked session. Reconnect bounded to six exponential retry attempts. Provider loggedOut does not trigger reconnect.
- Idempotent local send bound to canonical caller physical-attempt id, with payload conflict rejection; no autonomous resend. Baileys text/image/video/audio/document byte payloads, explicit JID validation, maximum media payload and MIME check, outbound generation fence. Provider message IDs + delivery/read receipt events, inbound message provenance and dedupe key.
- vault.mjs: full creds and Signal key map encrypted in AES-256-GCM envelope; envelope key wrapped using real Windows DPAPI CurrentUser with per-account entropy; per-account hashed directories, exclusive session lock, atomic replace, key rotation, restart restoration, authenticated tamper rejection. No plaintext auth directory. Different Windows users cannot seamlessly share the DPAPI session.
- Ephemeral inbound mediaRef resolves only while the same live socket generation is active. The canonical consumer must immediately ingest media into FileAttachment; the adapter is not a media database. Backfill deliberately fails closed until an authorized native history bridge exists.
- Failed or unverified device logout cannot report Connected and does not silently erase the encrypted session. True logout erases only after Baileys logout succeeds.

## Canonical integration boundaries still requiring W362 exact path authorization

1. backend/app/models/channels/channel_account.py and backend/app/repositories/channels/accounts.py: resolve a personal account identity/UUID. Channel type must distinguish personal whatsapp-personal from official whatsapp; never use Business Cloud token to claim personal account.
2. backend/app/models/channels/channel_conversation.py and backend/app/services/channel_chat.py: bind JID/participant to native Customer/session/conversation.
3. backend/app/models/chat_history.py: use its real provider identity UNIQUE index (provider_channel, external_account_id, external_message_id) for restart durable dedupe and native client_send_intent_id for outbound replay safety.
4. backend/app/services/message_delivery.py: claim native physical attempt before send, persist provider ACK/receipt and manage ambiguous outcomes after process crash; the sidecar must never own retry truth.
5. backend/app/models/file_attachment.py + existing media ingestion: store inbound bytes with the native owner rather than keeping provider media indefinitely in a sidecar.
6. backend/app/api/channels/accounts.py, backend/app/channels/registry.py and authorized frontend: authenticated user-first QR/expiration/cancel/reconnect/logout UI, never fake Connected. Assign separate source writers and avoid collisions with W392/W394.

No changes to any of these six native surfaces were made by W398. Full native integration and account E2E remain HOLD.

## Offline reproducibility and security review

Native Windows Node >=22.19; package lock pins V21 Baileys; npm ci --ignore-scripts; npm run check; node --test tests/transport.test.mjs; Windows Python 3.12 + pytest backend/yance_tests/test_whatsapp_user_personal_contract.py. Node tests use simulated provider emitter for *negative* scenarios, plus REAL Windows DPAPI seal/restore/rotation/tamper tests. Python tests include an actual pinned private Node process boot and refusal of offline send and concurrent duplicate login; no test calls live connect. npm audit --omit=dev at implementation time reported zero known vulnerabilities, not a guarantee of platform account safety.

Private Windows Node test: copied node.exe v24.18.0 from local installed runtime into user TEMP W398_PRIVATE_NODE_20261010; SHA-256 equality verified. Put private path first on PATH and repeat tests. Product-quality signed private Node distribution, frozen package ZIP, Node ABI acceptance and upgrade gate remain separate Windows packaging work.

**Release HOLD:** WhatsApp platform Terms-of-Service and account safety, RC protocol churn, secure recovery of V21 legacy credentials, native source admission, backend/ChatterMate UI, QR actual phone scanning, designated contact real inbound/outbound/media, restart/reconnect and sibling account testing, independent security review and final Windows distribution. No personal WhatsApp READY claim or deployment.
