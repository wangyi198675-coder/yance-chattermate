# PERSONAL_SOCIAL_TRANSPORT_ADAPTER_CONTRACT

A personal-social transport adapter MUST support:

- `connect`
- `disconnect`
- `reconnect`
- `session_status`
- `receive_inbound`
- `send_outbound`
- `receipt`
- `media`
- `backfill`
- `account_identity`
- `route`
- `error`
- `health`

The adapter MAY expose platform-specific opaque metadata needed to execute those operations.

The adapter MUST NOT own or persist canonical Person truth, Relationship truth, Persona, Memory, Girlfriend Brain decisions, Reply Brain decisions, or model authority. Those are resolved above the transport boundary.

Business WhatsApp, Telegram Bot, Facebook Page Messenger and Instagram Business availability MUST NOT be interpreted as Personal WhatsApp, Telegram User, Personal Messenger or personal Instagram GREEN.
