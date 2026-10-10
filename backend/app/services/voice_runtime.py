"""Native voice runtime seams owned by faster-whisper and ElevenLabs.

This module deliberately owns no persistence, delivery, background execution,
or registry lifecycle. Callers persist generated audio through FileAttachment
and deliver it through the canonical ChatterMate message_delivery path.
"""
from functools import lru_cache
from pathlib import Path
import tempfile
from typing import Any, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.services.external_media_cli import (
    ExternalMediaUnavailable,
    audio_normalize_command,
    run_external_media,
)
from app.services.file_upload_service import FileUploadService

logger = get_logger(__name__)

VOICE_PROVIDER = "elevenlabs"
TRANSCRIPTION_PROVIDER = "faster-whisper"
VOICE_NOTE_PROVIDER_TYPES = frozenset({"audio", "voice", "voice_note"})


class VoiceRuntimeError(RuntimeError):
    """Base fail-closed voice runtime error."""


class VoiceTranscriptionError(VoiceRuntimeError):
    pass


class VoiceProviderError(VoiceRuntimeError):
    pass


class VoiceProviderCredentialUnavailable(VoiceProviderError):
    pass


class ProfessionalVoiceCloneGateError(VoiceProviderError):
    pass


def is_voice_note_attachment(attachment: dict) -> bool:
    """Only provider-originated voice/audio attachments are auto-transcribed."""
    if not isinstance(attachment, dict):
        return False
    provider_type = str(attachment.get("provider_type") or "").strip().lower()
    content_type = str(attachment.get("content_type") or "").split(";", 1)[0].strip().lower()
    return provider_type in VOICE_NOTE_PROVIDER_TYPES and content_type.startswith("audio/")


def _validate_audio_bytes(file_content: bytes, filename: str, content_type: str) -> None:
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if not normalized_type.startswith("audio/"):
        raise VoiceTranscriptionError("unsupported_audio_type")
    valid, _ = FileUploadService.validate_extension(filename, normalized_type)
    if not valid:
        raise VoiceTranscriptionError("invalid_audio_extension")
    valid, _ = FileUploadService.validate_magic_bytes(file_content, normalized_type)
    if not valid:
        raise VoiceTranscriptionError("invalid_audio_content")


@lru_cache(maxsize=1)
def _get_whisper_model():
    """Lazily construct the admitted faster-whisper owner."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise VoiceTranscriptionError("faster_whisper_unavailable") from exc
    try:
        return WhisperModel(
            settings.FASTER_WHISPER_MODEL,
            device=settings.FASTER_WHISPER_DEVICE,
            compute_type=settings.FASTER_WHISPER_COMPUTE_TYPE,
        )
    except Exception as exc:
        logger.warning("faster-whisper model initialization failed: %s", type(exc).__name__)
        raise VoiceTranscriptionError("faster_whisper_initialization_failed") from exc


def _transcribe_path(path: Path) -> dict:
    try:
        segments, info = _get_whisper_model().transcribe(
            str(path),
            vad_filter=True,
            beam_size=5,
        )
        pieces: list[str] = []
        current_length = 0
        max_chars = max(1, int(settings.VOICE_TRANSCRIPT_MAX_CHARS))
        for segment in segments:
            text = str(getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            remaining = max_chars - current_length
            if remaining <= 0:
                break
            bounded = text[:remaining]
            pieces.append(bounded)
            current_length += len(bounded)
        transcript = " ".join(pieces).strip()
        if not transcript:
            raise VoiceTranscriptionError("empty_transcription")
        language_probability = getattr(info, "language_probability", None)
        duration = getattr(info, "duration", None)
        return {
            "status": "succeeded",
            "text": transcript[:max_chars],
            "language": getattr(info, "language", None),
            "language_probability": (
                round(float(language_probability), 4)
                if language_probability is not None else None
            ),
            "duration_seconds": (
                round(float(duration), 3) if duration is not None else None
            ),
            "provider": TRANSCRIPTION_PROVIDER,
            "model": settings.FASTER_WHISPER_MODEL,
        }
    except VoiceTranscriptionError:
        raise
    except Exception as exc:
        logger.warning("faster-whisper transcription failed: %s", type(exc).__name__)
        raise VoiceTranscriptionError("transcription_failed") from exc


def transcribe_voice_note(file_content: bytes, filename: str, content_type: str) -> dict:
    """Transcribe validated voice-note bytes, with optional admitted FFmpeg fallback."""
    _validate_audio_bytes(file_content, filename, content_type)
    suffix = Path(filename).suffix or ".audio"
    with tempfile.TemporaryDirectory(prefix="chattermate-voice-") as temp_dir:
        source = Path(temp_dir) / f"source{suffix}"
        source.write_bytes(file_content)
        try:
            return _transcribe_path(source)
        except VoiceTranscriptionError as primary:
            binary = str(settings.VOICE_FFMPEG_BINARY or "").strip()
            if not binary:
                raise primary
            normalized = Path(temp_dir) / "normalized.wav"
            try:
                run_external_media(
                    audio_normalize_command(binary, source, normalized),
                    timeout_seconds=int(settings.VOICE_FFMPEG_TIMEOUT_SECONDS),
                )
                return _transcribe_path(normalized)
            except (ExternalMediaUnavailable, VoiceTranscriptionError) as exc:
                raise VoiceTranscriptionError("transcription_failed") from exc


def _elevenlabs_client():
    api_key = str(settings.ELEVENLABS_API_KEY or "").strip()
    if not api_key:
        raise VoiceProviderCredentialUnavailable("elevenlabs_credential_unavailable")
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError as exc:
        raise VoiceProviderError("elevenlabs_sdk_unavailable") from exc
    return ElevenLabs(api_key=api_key)


def _value(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_state_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    return {}


def _verify_professional_voice_clone_with_client(client, voice_id: str, explicit_consent: bool) -> dict:
    if not explicit_consent:
        raise ProfessionalVoiceCloneGateError("professional_voice_clone_consent_required")
    if not voice_id:
        raise ProfessionalVoiceCloneGateError("professional_voice_clone_voice_id_required")
    try:
        voice = client.voices.get(voice_id=voice_id)
    except Exception as exc:
        logger.warning("ElevenLabs PVC verification lookup failed: %s", type(exc).__name__)
        raise ProfessionalVoiceCloneGateError("professional_voice_clone_provider_verification_failed") from exc

    category = str(_value(voice, "category", "") or "").lower()
    fine_tuning = _value(voice, "fine_tuning", {}) or {}
    is_verified = bool(_value(fine_tuning, "is_verified", False))
    states = _as_state_dict(_value(fine_tuning, "state", {}) or {})
    model_state = str(states.get(settings.ELEVENLABS_TTS_MODEL_ID, "") or "").lower()

    if category != "professional":
        raise ProfessionalVoiceCloneGateError("professional_voice_clone_required")
    if not is_verified:
        raise ProfessionalVoiceCloneGateError("professional_voice_clone_provider_verification_required")
    if model_state != "fine_tuned":
        raise ProfessionalVoiceCloneGateError("professional_voice_clone_not_ready")

    return {
        "eligible": True,
        "provider": VOICE_PROVIDER,
        "voice_id": voice_id,
        "category": category,
        "provider_verified": True,
        "model_id": settings.ELEVENLABS_TTS_MODEL_ID,
        "model_state": model_state,
        "explicit_consent": True,
    }


def verify_professional_voice_clone(voice_id: str, explicit_consent: bool) -> dict:
    """Provider-authoritative PVC gate. No samples or conversation audio are accepted."""
    return _verify_professional_voice_clone_with_client(
        _elevenlabs_client(), voice_id, explicit_consent
    )


def _coerce_audio_bytes(audio: Any) -> bytes:
    if isinstance(audio, bytes):
        return audio
    if isinstance(audio, bytearray):
        return bytes(audio)
    try:
        return b"".join(bytes(chunk) for chunk in audio if chunk)
    except Exception as exc:
        raise VoiceProviderError("elevenlabs_invalid_audio_response") from exc


def synthesize_speech(
    text: str,
    voice_id: Optional[str] = None,
    *,
    professional_clone: bool = False,
    explicit_consent: bool = False,
) -> tuple[bytes, dict]:
    """Generate TTS bytes only. Persistence/delivery remain canonical owners."""
    bounded_text = str(text or "").strip()
    if not bounded_text:
        raise VoiceProviderError("tts_text_required")
    if len(bounded_text) > int(settings.ELEVENLABS_TTS_MAX_CHARS):
        raise VoiceProviderError("tts_text_too_long")

    selected_voice = str(voice_id or settings.ELEVENLABS_DEFAULT_VOICE_ID or "").strip()
    if not selected_voice:
        raise VoiceProviderCredentialUnavailable("elevenlabs_default_voice_unavailable")

    client = _elevenlabs_client()
    pvc_gate = None
    if professional_clone:
        pvc_gate = _verify_professional_voice_clone_with_client(
            client, selected_voice, explicit_consent
        )

    try:
        response = client.text_to_speech.convert(
            voice_id=selected_voice,
            text=bounded_text,
            model_id=settings.ELEVENLABS_TTS_MODEL_ID,
            output_format=settings.ELEVENLABS_TTS_OUTPUT_FORMAT,
            # Never coerce an admitted Professional Voice Clone through the
            # provider's instant-voice-clone compatibility path.
            use_pvc_as_ivc=False,
        )
        audio = _coerce_audio_bytes(response)
    except ProfessionalVoiceCloneGateError:
        raise
    except Exception as exc:
        logger.warning("ElevenLabs TTS request failed: %s", type(exc).__name__)
        raise VoiceProviderError("elevenlabs_tts_failed") from exc

    if not audio:
        raise VoiceProviderError("elevenlabs_empty_audio")
    return audio, {
        "provider": VOICE_PROVIDER,
        "voice_id": selected_voice,
        "model_id": settings.ELEVENLABS_TTS_MODEL_ID,
        "output_format": settings.ELEVENLABS_TTS_OUTPUT_FORMAT,
        "professional_clone": bool(professional_clone),
        "pvc_gate": pvc_gate,
    }
