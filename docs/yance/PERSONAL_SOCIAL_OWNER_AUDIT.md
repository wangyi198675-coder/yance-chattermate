# PERSONAL_SOCIAL_OWNER_AUDIT

Date: 2026-10-05

Business/official ChatterMate channels remain intact. Personal transports are optional thin adapters only; they never own Person, relationship, memory, persona, route truth or message history.

| Surface | Mature owner candidate | Stable | License | Status | Key risk |
|---|---|---|---|---|---|
| Personal WhatsApp | Baileys | 6.7.24 | MIT | SELECT_THIN_ADAPTER / QUALIFICATION_REQUIRED | Unofficial WhatsApp Web protocol; platform/account churn. v7 remains RC, so do not chase it. |
| Telegram user / MTProto | Telethon | 1.45.0 | MIT | SELECT_THIN_ADAPTER / QUALIFICATION_REQUIRED | User-session security and MTProto layer migrations |
| Personal Instagram | instagrapi | 3.0.20 | MIT | CONDITIONAL_EXPERIMENTAL | Unofficial private API/account-safety risk |
| Personal Messenger | None selected | N/A | N/A | WAIT_NO_OWNER | Current unofficial libraries rely on brittle cookie/browser emulation or weak stable provenance |

## Native channels preserved

ChatterMate v1.0.25 already owns business/official WhatsApp, Telegram bot, Messenger/Facebook Page, Instagram business, Slack, email, LINE and SMS transport abstractions. No personal adapter may replace those owners.

## Hard rule

Personal Messenger remains a known capability gap. This is **not** permission to implement a custom Facebook protocol stack. Re-audit periodically for a mature owner.
