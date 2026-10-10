# PERSONAL_SOCIAL_PRODUCTION_QUALIFICATION_PLAN

No Wave-F transport integration in this batch. `PersonalSocialTransportAdapter` remains contract-only.

- Baileys 6.7.24: QR/link, reconnect, auth persistence, inbound, outbound, receipt, media, backfill, logout, multi-account, update compatibility.
- Telethon 1.45.0: session lifecycle, reconnect, inbound/outbound/receipt-equivalent/media/backfill/logout/multi-account.
- instagrapi 3.0.20: remains EXPERIMENTAL until account-safety and live qualification passes.
- Personal Messenger: `WAIT_NO_OWNER`; no private-protocol implementation.

Every transport must map into ChatterMate `ChannelAccount/ChannelConversation/Customer/ChatHistory`; transport session state never becomes Person/Relationship/Persona/Memory truth.
