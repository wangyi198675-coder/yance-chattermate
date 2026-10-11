# W397 -> W362 exact native source write-permission request (NO CURRENT AUTHORIZATION)
Date 2026-10-10
Candidate branch: isolated W397 child of b627b92122d373b96d27e2450290d4dd35df6868
Source under W397 allowed subtree is implemented/tested. No change is authorized to the paths below by this window.

## Requested exclusive additional paths (only after W362 preflight and conflict lock)
1. backend/app/api/channels/telegram.py
   - Keep current bot-token POST and bot webhook/delete endpoint behavior EXACTLY.
   - Add separate personal MTProto start/QR/phone/OTP/2FA/logout controls with authenticated org RBAC and explicit actor approval.
2. backend/app/repositories/channels/accounts.py
   - Inject scoped encrypted session custody through existing ChannelAccount.encrypted_credentials and approved Windows private key custody (DO NOT add a second vault/table).
   - Atomic credential update, verified account identity binding and fail-closed provider_health.
3. backend/app/services/channel_chat.py
   - Route PERSONAL inbound only after independent account-kind check to native Customer / ChannelConversation / ChatHistory; media via FileAttachment, dedup before AI handling. Outgoing echoes are not customer turns.
4. backend/app/services/message_delivery.py
   - Dispatch PERSONAL send via scoped adapter and canonical existing message_delivery and its idempotent send claim. Keep Bot path unchanged; never auto-retry ambiguous provider result.
5. backend/app/channels/registry.py
   - Only if needed after proving account-based dispatch cannot be implemented without a registry change; preserve ChannelType.TELEGRAM bot registration untouched.
6. frontend/src/views/settings/IntegrationsSettings.vue
   - Separate pre-approved frontend owner/lock, not W397: visible Bot vs PERSONAL settings and real, user-first QR/phone/2FA challenge handling; NEVER fake Connected. Requires independent UI integration owner allocation.
7. Application lifespan/startup native owner file: NOT YET QUALIFIED. W362 must first identify exact lifecycle source and assign a separate path lock for supervised private Node start/stop/restart. W397 will not guess/change it.

## Invariants
- No modification to bot adapter backend/app/channels/telegram.py or backend/app/api/webhooks/telegram.py.
- No changes to models/migrations or a new database without a proved native schema constraint and separate W362 authorization.
- One actual external Telegram user identity maps to a single native ChannelAccount; exact org/account isolation.
- Native owner persists History/Attachments/Receipts/Backfill cursor. Transport never becomes a second canonical engine.
- Live login/test peer only after interactive owner permission; no OTP/session extraction.
- W392/W393/W394/W396 source and reviewer ownership unaffected; no main/C3 cherry-pick by W397.

This file is a request, not approval. Until W362 grants the above scope, route and live provider UAT remain HOLD.
