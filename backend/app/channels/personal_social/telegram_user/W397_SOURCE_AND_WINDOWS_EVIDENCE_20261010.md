# W397 Telegram PERSONAL MTProto: V21 GramJS source recovery and isolated receipt
Date: 2026-10-10
Authority: W362 latest pointer and superseding GitHub V21 GramJS addendum
Worktree: C:\Users\1\YanceWorktrees\yance-chattermate-window397-telegram-personal
Base: b627b92122d373b96d27e2450290d4dd35df6868
Mode: EXCLUSIVE SOURCE WRITER; NO DEPLOY; NO PERSONAL LOGIN WITHOUT TEST ACTOR

## Provenance (old GitHub main, read only)
Repo: https://github.com/laiqian0239-glitch/yance
Exact source commit: 5c31f8b11dc8d775bc687eaa7cacc37528280eeb (local Windows clone verified; origin untouched)
- backend/services/telegramAdapter.js, blob 954b9d64bffb8a5b0503df5aaf8f4028a47ca675, 103519 bytes: TelegramClient/StringSession/NewMessage, QR, phone OTP, 2FA, sendText/sendMedia/read/revoke, generations, backfill and media.
- backend/services/platformDriverRegistry.js, blob beccfa86907da9ab72596dd8aa9452e478669055: telegram-personal-mtproto old driver (not new native ready).
- backend/services/platformAuthConfig.js, blob 88926e6679445e88794019a16d0f505feef82d0f: strict apiId/apiHash.
- backend/repositories/accountRepository.js, blob 522a9b48c739860495331b2fe0489de516deee30: old account binding, not transplanted DB.
- package.json, blob f3b95587bb28604b342526b7a63818048fe28d11: telegram dependency ^2.26.22.
- old tests inspected: backend/tests/batch39TelegramSessionFence.test.js (stale callback, disconnect fencing); backend/tests/telegramHistorySyncRegression.test.js (chrono/unread, live ingest, backfill offsets, high-water gaps). Old V21 tests not executed.

## Newly implemented narrow transport
- adapter.py: the original PersonalSocialTransportAdapter contract, private GramJS subprocess, exact organization/account scoping, optional expected user identity, injected encrypted native custody, bounded queues, health fail-closed. QR/phone/code/password/logout require explicitly interactive caller.
- worker.cjs: pin GramJS 2.26.22; legacy TelegramClient/StringSession/NewMessage and signInUserWithQrCode/client.start flows. No MessageStore/Matrix/Synapse/second DB/CRM/queue/scheduler. No logging of OTP, 2FA, QR tokens or session.
- package.json + lock: exact source lock; node_modules ignored, not vendored. Each account has its own child process and session.
- Session arrives via local child pipe and must be saved by injected native encrypted credential custody before Connected. Failed custody or wrong identity blocks Connected.
- Inbound keeps provider provenance and is_customer_turn flag; message identity uses conversation:message composite because native ChatHistory provider index omits conversation.
- Outbound text/media returns remote Accepted only (not delivered); uncertain outcome degrades without automatic retry. Native message_delivery remains authoritative.
- Media is bounded bytes, native FileAttachment owns durable assets; history/dialog discovery surfaces cursors for native commit-after-persist. Bot untouched.

## Real Windows evidence (NOT real provider login)
- Python: D:\Yance-Windows-Runtime-20261005\qualification\w351-08e-package\qa-unsigned-payload\private-runtime\python\python.exe, 3.12.15.
- Private test Node: C:\Users\1\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe; Windows distributable private Node unproven.
- npm ci --ignore-scripts --no-audit --no-fund: 46 dependencies installed, exit 0.
- node --check worker.cjs: exit 0; actual GramJS import version 2.26.22, exit 0.
- pytest -q --no-cov: 21 PASS, 0 FAIL, exit 0, including real Windows Node IPC against invalid credentials without network or login. Full output W397_WINDOWS_TEST_LOG.txt.
- Python compileall exit 0.
- npm audit --omit=dev --audit-level=moderate --json: 0 reported vulnerabilities. WARNING: telegram@2.26.22 is archived/deprecated; audit is not full production security approval.

## CURRENT INTEGRATION / RELEASE: HOLD
1. W362 has not granted native route/ingest/delivery/UI write access. Adapter is deliberately UNREGISTERED; Bot is unchanged.
2. No user-supervised personal Telegram QR/OTP/2FA login, two-way message, media, reconnect, restart or test-peer E2E. No live message sent.
3. Native ChannelAccountRepository stores Fernet credentials; W362 must select/authorize a single existing encrypted session owner, including DPAPI Windows runtime needs. No new secret vault/database/plaintext session.
4. Native ChatHistory idempotent upsert, ChannelConversation.extra history checkpoints and message_delivery failure/receipt reconciliation need integration.
5. Production Windows private Node signing/supervision not yet qualified.
6. GramJS package archived: security/product must compare maintenance risk to existing Telethon 1.45.0 fallback, not misrepresent npm audit 0 as safety approval.
7. Full native E2E, independent review, C3 admission and deploy remain pending. No GitHub push or formal C3 change by W397.

Do not mark Telegram PERSONAL Connected from Bot API, process start or unit tests.
