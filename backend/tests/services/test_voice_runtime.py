"""Window 40 coverage for native voice runtime wiring."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories.chat import ChatRepository
from app.models.chat_history import ChatHistory
from app.models.file_attachment import FileAttachment
from app.services import voice_runtime


def test_provider_audio_detection_is_narrow():
    assert voice_runtime.is_voice_note_attachment({
        "provider_type": "voice",
        "content_type": "audio/ogg",
    })
    assert voice_runtime.is_voice_note_attachment({
        "provider_type": "audio",
        "content_type": "audio/mpeg",
    })
    assert not voice_runtime.is_voice_note_attachment({
        "provider_type": "document",
        "content_type": "audio/mpeg",
    })
    assert not voice_runtime.is_voice_note_attachment({
        "provider_type": "audio",
        "content_type": "image/png",
    })


def test_invalid_audio_fails_closed_before_whisper(monkeypatch):
    model = MagicMock()
    monkeypatch.setattr(voice_runtime, "_get_whisper_model", lambda: model)

    with pytest.raises(voice_runtime.VoiceTranscriptionError) as exc:
        voice_runtime.transcribe_voice_note(
            b"not-a-real-audio-file",
            "voice.mp3",
            "audio/mpeg",
        )

    assert str(exc.value) == "invalid_audio_content"
    model.transcribe.assert_not_called()


def test_faster_whisper_transcript_projection_is_bounded(monkeypatch):
    fake_segments = [
        SimpleNamespace(text=" hello "),
        SimpleNamespace(text=" world "),
    ]
    fake_info = SimpleNamespace(
        language="en",
        language_probability=0.98765,
        duration=1.23456,
    )
    model = MagicMock()
    model.transcribe.return_value = (iter(fake_segments), fake_info)
    monkeypatch.setattr(voice_runtime, "_get_whisper_model", lambda: model)
    monkeypatch.setattr(voice_runtime.settings, "VOICE_TRANSCRIPT_MAX_CHARS", 12000)

    result = voice_runtime._transcribe_path(Path("fixture.wav"))

    assert result["status"] == "succeeded"
    assert result["text"] == "hello world"
    assert result["language"] == "en"
    assert result["language_probability"] == 0.9877
    assert result["duration_seconds"] == 1.235
    assert result["provider"] == "faster-whisper"
    model.transcribe.assert_called_once()


class _FakeVoices:
    def __init__(self, voice):
        self.voice = voice
        self.get = MagicMock(return_value=voice)


class _FakeTTS:
    def __init__(self):
        self.convert = MagicMock(return_value=[b"ID3", b"voice-bytes"])


class _FakeElevenLabs:
    def __init__(self, voice):
        self.voices = _FakeVoices(voice)
        self.text_to_speech = _FakeTTS()


def _professional_voice(model_id: str, verified: bool = True, state: str = "fine_tuned"):
    return SimpleNamespace(
        category="professional",
        fine_tuning=SimpleNamespace(
            is_verified=verified,
            state={model_id: state},
        ),
    )


def test_pvc_gate_requires_explicit_consent_before_provider_lookup(monkeypatch):
    model_id = "eleven_multilingual_v2"
    client = _FakeElevenLabs(_professional_voice(model_id))
    monkeypatch.setattr(voice_runtime.settings, "ELEVENLABS_TTS_MODEL_ID", model_id)

    with pytest.raises(voice_runtime.ProfessionalVoiceCloneGateError) as exc:
        voice_runtime._verify_professional_voice_clone_with_client(
            client,
            "voice-1",
            False,
        )

    assert str(exc.value) == "professional_voice_clone_consent_required"
    client.voices.get.assert_not_called()


@pytest.mark.parametrize(
    "voice,expected",
    [
        (
            SimpleNamespace(
                category="cloned",
                fine_tuning=SimpleNamespace(
                    is_verified=True,
                    state={"eleven_multilingual_v2": "fine_tuned"},
                ),
            ),
            "professional_voice_clone_required",
        ),
        (
            _professional_voice("eleven_multilingual_v2", verified=False),
            "professional_voice_clone_provider_verification_required",
        ),
        (
            _professional_voice("eleven_multilingual_v2", state="fine_tuning"),
            "professional_voice_clone_not_ready",
        ),
    ],
)
def test_pvc_gate_fails_closed_on_noneligible_provider_state(monkeypatch, voice, expected):
    monkeypatch.setattr(
        voice_runtime.settings,
        "ELEVENLABS_TTS_MODEL_ID",
        "eleven_multilingual_v2",
    )
    client = _FakeElevenLabs(voice)

    with pytest.raises(voice_runtime.ProfessionalVoiceCloneGateError) as exc:
        voice_runtime._verify_professional_voice_clone_with_client(
            client,
            "voice-1",
            True,
        )

    assert str(exc.value) == expected


def test_verified_professional_clone_can_generate_tts(monkeypatch):
    model_id = "eleven_multilingual_v2"
    client = _FakeElevenLabs(_professional_voice(model_id))
    monkeypatch.setattr(voice_runtime, "_elevenlabs_client", lambda: client)
    monkeypatch.setattr(voice_runtime.settings, "ELEVENLABS_TTS_MODEL_ID", model_id)
    monkeypatch.setattr(voice_runtime.settings, "ELEVENLABS_TTS_OUTPUT_FORMAT", "mp3_44100_128")
    monkeypatch.setattr(voice_runtime.settings, "ELEVENLABS_TTS_MAX_CHARS", 5000)

    audio, meta = voice_runtime.synthesize_speech(
        "Hello from Window 40",
        "voice-1",
        professional_clone=True,
        explicit_consent=True,
    )

    assert audio == b"ID3voice-bytes"
    assert meta["provider"] == "elevenlabs"
    assert meta["professional_clone"] is True
    assert meta["pvc_gate"]["provider_verified"] is True
    client.voices.get.assert_called_once_with(voice_id="voice-1")
    client.text_to_speech.convert.assert_called_once_with(
        voice_id="voice-1",
        text="Hello from Window 40",
        model_id=model_id,
        output_format="mp3_44100_128",
        use_pvc_as_ivc=False,
    )


def test_missing_elevenlabs_credential_is_explicit_hold(monkeypatch):
    monkeypatch.setattr(voice_runtime.settings, "ELEVENLABS_API_KEY", "")
    with pytest.raises(voice_runtime.VoiceProviderCredentialUnavailable) as exc:
        voice_runtime._elevenlabs_client()
    assert str(exc.value) == "elevenlabs_credential_unavailable"


def test_transcript_persists_on_chat_history_linked_to_fileattachment():
    org_id = uuid4()
    customer_id = uuid4()
    added = []

    db = MagicMock()

    def add(row):
        added.append(row)
        if isinstance(row, ChatHistory):
            row.id = 41
        if isinstance(row, FileAttachment):
            row.id = 73

    db.add.side_effect = add
    repo = ChatRepository(db)

    message = repo.create_message({
        "message": "",
        "message_type": "user",
        "organization_id": org_id,
        "customer_id": customer_id,
        "attributes": {"channel": "telegram"},
        "attachments": [{
            "file_url": "/uploads/chat_attachments/org/voice.ogg",
            "filename": "voice.ogg",
            "content_type": "audio/ogg",
            "file_size": 1234,
            "voice_transcription": {
                "status": "succeeded",
                "text": "canonical transcript",
                "language": "en",
                "provider": "faster-whisper",
                "model": "small",
            },
        }],
    })

    attachment_rows = [row for row in added if isinstance(row, FileAttachment)]
    assert len(attachment_rows) == 1
    assert attachment_rows[0].chat_history_id == 41
    transcript = message.attributes["voice_transcriptions"][0]
    assert transcript["attachment_id"] == 73
    assert transcript["text"] == "canonical transcript"
    assert transcript["provider"] == "faster-whisper"
    db.commit.assert_called_once()


def test_received_audio_has_no_cloning_enrollment_surface():
    from pathlib import Path

    source = Path(voice_runtime.__file__).read_text(encoding="utf-8")
    assert "pvc.samples" not in source
    assert "instant_voice" not in source.lower()
    assert "clone_from_audio" not in source.lower()


@pytest.mark.asyncio
async def test_tts_endpoint_persists_fileattachment_for_existing_adoption(monkeypatch):
    from app.api import voice as voice_api

    user = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    db = MagicMock()
    payload = voice_api.TextToSpeechRequest(text="Generate this voice")
    provider_meta = {
        "provider": "elevenlabs",
        "voice_id": "voice-default",
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_44100_128",
        "professional_clone": False,
        "pvc_gate": None,
    }
    monkeypatch.setattr(
        voice_api,
        "synthesize_speech",
        lambda *_args, **_kwargs: (b"ID3generated", provider_meta),
    )
    store = AsyncMock(return_value={
        "file_url": "/uploads/chat_attachments/org/generated.mp3",
        "filename": "generated.mp3",
        "content_type": "audio/mpeg",
        "size": 12,
    })
    monkeypatch.setattr(voice_api.FileUploadService, "store_bytes", store)

    created = SimpleNamespace(
        id=88,
        file_url="/uploads/chat_attachments/org/generated.mp3",
        filename="generated.mp3",
        content_type="audio/mpeg",
        file_size=12,
        chat_history_id=None,
    )
    repo = MagicMock()
    repo.create_attachment.return_value = created
    monkeypatch.setattr(voice_api, "FileAttachmentRepository", lambda _db: repo)

    result = await voice_api.generate_text_to_speech(payload, user, db)

    assert result["attachment"]["id"] == 88
    assert result["attachment"]["content_type"] == "audio/mpeg"
    assert result["send_authority"] == "message_delivery/ChannelAdapter.send_media"
    repo.create_attachment.assert_called_once()
    kwargs = repo.create_attachment.call_args.kwargs
    assert kwargs["organization_id"] == user.organization_id
    assert kwargs["uploaded_by_user_id"] == user.id
    assert "chat_history_id" not in kwargs


def test_ffmpeg_normalization_is_only_a_decode_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(voice_runtime.settings, "VOICE_FFMPEG_BINARY", "C:/tools/ffmpeg.exe")
    monkeypatch.setattr(voice_runtime.settings, "VOICE_FFMPEG_TIMEOUT_SECONDS", 30)

    def fake_transcribe(path):
        calls.append(("transcribe", Path(path).suffix))
        if len([c for c in calls if c[0] == "transcribe"]) == 1:
            raise voice_runtime.VoiceTranscriptionError("transcription_failed")
        return {
            "status": "succeeded",
            "text": "normalized speech",
            "provider": "faster-whisper",
            "model": "small",
        }

    def fake_run(command, timeout_seconds):
        calls.append(("ffmpeg", timeout_seconds, tuple(command)))
        destination = Path(command[-1])
        destination.write_bytes(
            b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 32
        )
        return destination

    monkeypatch.setattr(voice_runtime, "_transcribe_path", fake_transcribe)
    monkeypatch.setattr(voice_runtime, "run_external_media", fake_run)

    wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 32
    result = voice_runtime.transcribe_voice_note(wav, "voice.wav", "audio/wav")

    assert result["text"] == "normalized speech"
    assert calls[0] == ("transcribe", ".wav")
    assert calls[1][0] == "ffmpeg"
    assert calls[2] == ("transcribe", ".wav")


def test_elevenlabs_provider_failure_fails_closed(monkeypatch):
    client = _FakeElevenLabs(_professional_voice("eleven_multilingual_v2"))
    client.text_to_speech.convert.side_effect = RuntimeError("provider down")
    monkeypatch.setattr(voice_runtime, "_elevenlabs_client", lambda: client)
    monkeypatch.setattr(voice_runtime.settings, "ELEVENLABS_TTS_MODEL_ID", "eleven_multilingual_v2")
    monkeypatch.setattr(voice_runtime.settings, "ELEVENLABS_TTS_OUTPUT_FORMAT", "mp3_44100_128")
    monkeypatch.setattr(voice_runtime.settings, "ELEVENLABS_TTS_MAX_CHARS", 5000)

    with pytest.raises(voice_runtime.VoiceProviderError) as exc:
        voice_runtime.synthesize_speech(
            "This must not silently succeed",
            "voice-1",
        )

    assert str(exc.value) == "elevenlabs_tts_failed"


def test_voice_state_survives_database_session_restart(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.models.organization import Organization

    database_path = tmp_path / "voice-restart.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            ChatHistory.__table__,
            FileAttachment.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    org_id = uuid4()
    first = Session()
    first.add(Organization(
        id=org_id,
        name="Window 40 Restart",
        domain=f"window40-{org_id}.test",
        timezone="UTC",
    ))
    message = ChatHistory(
        organization_id=org_id,
        message="",
        message_type="user",
        attributes={
            "voice_transcriptions": [{
                "attachment_id": 501,
                "attachment_index": 0,
                "filename": "restart-voice.ogg",
                "status": "succeeded",
                "text": "persisted after restart",
                "provider": "faster-whisper",
                "model": "small",
            }],
        },
    )
    first.add(message)
    first.flush()
    first.add(FileAttachment(
        id=501,
        file_url="/uploads/chat_attachments/org/restart-voice.ogg",
        filename="restart-voice.ogg",
        content_type="audio/ogg",
        file_size=321,
        chat_history_id=message.id,
        organization_id=org_id,
    ))
    first.commit()
    message_id = message.id
    first.close()
    engine.dispose()

    restarted_engine = create_engine(f"sqlite:///{database_path}")
    RestartedSession = sessionmaker(bind=restarted_engine)
    restarted = RestartedSession()
    persisted_message = restarted.query(ChatHistory).filter(
        ChatHistory.id == message_id
    ).one()
    persisted_attachment = restarted.query(FileAttachment).filter(
        FileAttachment.id == 501
    ).one()

    assert persisted_message.attributes["voice_transcriptions"][0]["text"] == "persisted after restart"
    assert persisted_message.attributes["voice_transcriptions"][0]["attachment_id"] == 501
    assert persisted_attachment.chat_history_id == message_id
    assert persisted_attachment.content_type == "audio/ogg"

    restarted.close()
    restarted_engine.dispose()


def test_tts_preview_adopt_send_reuses_existing_composer_contract():
    repo_root = Path(__file__).resolve().parents[3]
    conversation = (
        repo_root
        / "frontend"
        / "src"
        / "components"
        / "conversations"
        / "ConversationChat.vue"
    ).read_text(encoding="utf-8")
    composer = (
        repo_root
        / "frontend"
        / "src"
        / "composables"
        / "useConversationFiles.ts"
    ).read_text(encoding="utf-8")

    assert "voiceService.generateSpeech(sourceText)" in conversation
    assert "adoptExistingAttachment(generated.attachment.id)" in conversation
    assert 'v-if="ttsPreview"' in conversation
    assert "<audio" in conversation
    assert '@click="handleComposerSend"' in conversation
    assert "handleSendMessageWithAttachments()" in conversation

    assert "existingAttachmentIds" in composer
    assert "attachment_ids: [...existingAttachmentIds.value]" in composer
    assert "socketService.emitWithPersistenceAck<" in composer
    assert "}>('agent_message', payload)" in composer
