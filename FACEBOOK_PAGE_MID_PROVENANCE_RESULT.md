# FACEBOOK_PAGE_MID_PROVENANCE_RESULT

Status: PASS

Branch: `fix/facebook-page-thin-native-extension-20261005`
Base: `fca3b80ccdb0988adc44eee544339eb0c3d25324`
Implementation commit: `740ff0b7851b81644820bce36f9197d4a3002e89`

## Result

Messenger provider identity now follows one canonical inbound path for both human-takeover and AI-owned conversations:

`Messenger webhook MID -> MessengerAdapter.parse_inbound -> InboundMessage.external_message_id -> channel_chat message_metadata -> ChatAgent/ChatRepository -> canonical ChatHistory.attributes`.

The persisted canonical user row records:
- `channel = messenger`
- `external_account_id = Facebook Page ID`
- `external_message_id = exact Messenger MID`

AI processing receives the metadata through one optional `message_metadata` argument on the existing `ChatAgent.get_response()` seam. No alternate message table, provider registry, message service, Facebook cache, or shadow persistence was added.

Human persistence uses the same metadata builder and continues to write the same canonical `ChatHistory` row. Attachments, when present, are projected through the existing `FileAttachment` authority in the same transaction.

## TDD evidence

RED baseline before implementation: targeted backend suite reported `14 failed, 68 passed`; failures included the AI MID provenance test and human attachment/MID persistence expectations.

GREEN final regression: `178 passed` across:
- `tests/channels/test_meta_adapters.py`
- `tests/services/test_channel_chat.py`
- `tests/services/test_message_delivery.py`
- `tests/agent/test_chat_agent.py`
- `tests/api/test_meta_channels_api.py`

Exact-text and exact-MID assertions pass for the AI path; human MID persistence remains GREEN.
