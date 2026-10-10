"""Window 36 regression coverage for canonical audio/video transport."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.channels.base import InboundMessage, RetrievedMedia, SendResult, WindowStatus
from app.services import channel_chat, message_delivery


@pytest.mark.asyncio
async def test_inbound_media_is_materialized_before_fileattachment_persistence(monkeypatch):
    inbound = InboundMessage(
        external_account_id="acct",
        external_conversation_id="conv",
        external_user_id="user",
        external_message_id="provider-mid",
        attachments=[{
            "provider_type": "audio",
            "provider_id": "media-1",
            "url": "https://provider.example/expiring",
            "file_url": "https://provider.example/expiring",
            "content_type": "audio/ogg",
            "filename": "voice.ogg",
        }],
    )
    adapter = MagicMock()
    adapter.fetch_inbound_media = AsyncMock(return_value=RetrievedMedia(
        content=b"OggS" + b"\x00" * 16,
        filename="voice.ogg",
        content_type="audio/ogg",
    ))
    store = AsyncMock(return_value={
        "file_url": "/uploads/chat_attachments/org/voice.ogg",
        "filename": "voice.ogg",
        "content_type": "audio/ogg",
        "size": 20,
    })
    monkeypatch.setattr(channel_chat.FileUploadService, "store_bytes", store)
    # Window 40 owns transcription. This Window 36 transport fixture uses only
    # synthetic Ogg header bytes, so keep it a media-materialization test rather
    # than making it download/run a speech model.
    monkeypatch.setattr(
        channel_chat,
        "transcribe_voice_note",
        lambda *_args: {"status": "succeeded", "text": "fixture", "provider": "faster-whisper"},
    )

    await channel_chat._materialize_inbound_media(
        adapter,
        SimpleNamespace(channel_type="telegram"),
        inbound,
        "org",
    )

    assert inbound.attachments[0]["url"] == "https://provider.example/expiring"
    assert inbound.attachments[0]["file_url"].startswith("/uploads/chat_attachments/")
    assert "materialization_error" not in inbound.attachments[0]
    store.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_materialization_never_persists_provider_url_as_canonical(monkeypatch):
    inbound = InboundMessage(
        external_account_id="acct",
        external_conversation_id="conv",
        external_user_id="user",
        external_message_id="provider-mid",
        attachments=[{
            "provider_type": "video",
            "provider_id": "media-2",
            "url": "https://provider.example/expiring.mp4",
            "file_url": "https://provider.example/expiring.mp4",
            "content_type": "video/mp4",
            "filename": "clip.mp4",
        }],
    )
    adapter = MagicMock()
    adapter.fetch_inbound_media = AsyncMock(side_effect=RuntimeError("provider unavailable"))

    await channel_chat._materialize_inbound_media(
        adapter,
        SimpleNamespace(channel_type="messenger"),
        inbound,
        "org",
    )

    assert "file_url" not in inbound.attachments[0]
    assert inbound.attachments[0]["materialization_error"] == "provider unavailable"


def _delivery_harness(monkeypatch, initial_attributes=None):
    message = SimpleNamespace(id=123, attributes=dict(initial_attributes or {}))
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = message

    class FakeChatRepository:
        def __init__(self, _db):
            pass

        def update_message_attributes(self, _message_id, attributes):
            message.attributes = {**message.attributes, **attributes}
            return message

    conversation = SimpleNamespace(channel_account_id=uuid4())
    account = SimpleNamespace(is_active=True)
    monkeypatch.setattr(message_delivery, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(
        message_delivery, "ChannelConversationRepository",
        lambda _db: SimpleNamespace(get_by_session=lambda _sid: conversation),
    )
    monkeypatch.setattr(
        message_delivery, "ChannelAccountRepository",
        lambda _db: SimpleNamespace(get_by_id=lambda _id: account),
    )

    adapter = MagicMock()
    adapter.check_delivery_window.return_value = WindowStatus.OK
    adapter.format_outbound.side_effect = lambda value: value
    monkeypatch.setattr(message_delivery, "get_adapter", lambda _channel: adapter)
    session = SimpleNamespace(session_id=uuid4())
    return db, message, adapter, session


@pytest.mark.asyncio
async def test_provider_receipt_is_correlated_to_same_chathistory(monkeypatch):
    db, message, adapter, session = _delivery_harness(monkeypatch)
    adapter.send_text = AsyncMock(return_value=SendResult(
        ok=True, external_message_id="provider-text-77"
    ))

    result = await message_delivery._deliver_to_channel(
        db, session, "telegram", {"message_id": 123, "message": "hello"}
    )

    assert result.ok is True
    assert result.provider_receipts[0]["external_message_id"] == "provider-text-77"
    assert message.attributes["provider_delivery"]["state"] == "succeeded"
    assert message.attributes["provider_delivery"]["receipts"][0]["external_message_id"] == "provider-text-77"


@pytest.mark.asyncio
async def test_ambiguous_send_is_persisted_and_restart_replay_is_blocked(monkeypatch):
    db, message, adapter, session = _delivery_harness(monkeypatch)
    adapter.send_text = AsyncMock(return_value=SendResult(
        ok=False, error="connection reset", ambiguous=True
    ))

    first = await message_delivery._deliver_to_channel(
        db, session, "telegram", {"message_id": 123, "message": "hello"}
    )
    assert first.ok is False
    assert first.ambiguous is True
    assert message.attributes["provider_delivery"]["state"] == "ambiguous"
    assert adapter.send_text.await_count == 1

    second = await message_delivery._deliver_to_channel(
        db, session, "telegram", {"message_id": 123, "message": "hello"}
    )
    assert second.ok is False
    assert second.reason == "ambiguous_previous_send"
    assert second.ambiguous is True
    assert adapter.send_text.await_count == 1


def test_audio_video_upload_validation_uses_real_signatures_and_limits():
    from app.services.file_upload_service import FileUploadService, MAX_VIDEO_SIZE

    assert FileUploadService.validate_magic_bytes(b"ID3" + b"\x00" * 20, "audio/mpeg") == (True, None)
    assert FileUploadService.validate_magic_bytes(b"OggS" + b"\x00" * 20, "audio/ogg") == (True, None)
    assert FileUploadService.validate_magic_bytes(
        b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 12, "audio/wav"
    ) == (True, None)
    assert FileUploadService.validate_magic_bytes(
        b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12, "video/mp4"
    ) == (True, None)
    assert FileUploadService.validate_file_size(MAX_VIDEO_SIZE, "video/mp4") == (True, None)
    assert FileUploadService.validate_file_size(MAX_VIDEO_SIZE + 1, "video/mp4")[0] is False


@pytest.mark.asyncio
async def test_whatsapp_video_send_uses_existing_graph_delivery_seam(monkeypatch):
    from app.channels.whatsapp import WhatsAppAdapter

    graph = AsyncMock(return_value=SendResult(ok=True, external_message_id="wamid.OUT"))
    monkeypatch.setattr("app.channels.whatsapp.graph_post", graph)
    adapter = WhatsAppAdapter()
    monkeypatch.setattr(adapter, "access_token", lambda _account: "token")

    result = await adapter.send_media(
        SimpleNamespace(external_account_id="PN123"),
        SimpleNamespace(external_conversation_id="447000000001"),
        "https://cdn.example/video.mp4",
        "video/mp4",
    )

    assert result.ok is True
    payload = graph.await_args.args[2]
    assert payload["type"] == "video"
    assert payload["video"]["link"] == "https://cdn.example/video.mp4"


@pytest.mark.asyncio
async def test_protected_local_media_never_reopens_private_static_for_provider(monkeypatch):
    """Provider projection preserves the authenticated owner instead of /uploads."""
    protected = (
        "/api/v1/files/download/chat_attachments/"
        "bab82aab-d095-46f8-bf16-da638671bcf4/voice.ogg"
    )
    monkeypatch.setattr(message_delivery.settings, "BACKEND_URL", "http://127.0.0.1:8000")

    provider_url = await message_delivery._provider_media_url(protected)

    assert provider_url == f"http://127.0.0.1:8000{protected}"
    assert "/api/v1/uploads/chat_attachments/" not in provider_url


def test_generated_fileattachment_is_adopted_not_copied():
    from app.repositories.file_attachment import FileAttachmentRepository

    organization_id = uuid4()
    user_id = uuid4()
    row = SimpleNamespace(
        id=7,
        organization_id=organization_id,
        uploaded_by_user_id=None,
        chat_history_id=None,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [row]
    repo = FileAttachmentRepository(db)

    adopted = repo.adopt_attachments(
        attachment_ids=[7],
        chat_history_id=99,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
    )

    assert adopted == [row]
    assert row.chat_history_id == 99
    assert row.uploaded_by_user_id == user_id
    db.commit.assert_called_once()
