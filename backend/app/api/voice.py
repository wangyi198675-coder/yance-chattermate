"""Authenticated voice actions that adopt existing ChatterMate owners."""
import asyncio
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.repositories.file_attachment import FileAttachmentRepository
from app.services.file_upload_service import ALLOWED_AUDIO_TYPES, FileUploadService
from app.services.voice_runtime import (
    ProfessionalVoiceCloneGateError,
    VoiceProviderCredentialUnavailable,
    VoiceProviderError,
    synthesize_speech,
    verify_professional_voice_clone,
)

router = APIRouter()


class TextToSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voice_id: Optional[str] = Field(default=None, max_length=128)
    voice_kind: Literal["standard", "professional_clone"] = "standard"
    explicit_voice_owner_consent: bool = False


class ProfessionalVoiceCloneEligibilityRequest(BaseModel):
    voice_id: str = Field(min_length=1, max_length=128)
    explicit_voice_owner_consent: bool


def _provider_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, VoiceProviderCredentialUnavailable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, ProfessionalVoiceCloneGateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="voice_provider_failed",
    )


@router.post("/tts")
async def generate_text_to_speech(
    payload: TextToSpeechRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate one canonical unlinked FileAttachment for composer adoption."""
    professional_clone = payload.voice_kind == "professional_clone"
    try:
        audio, provider_meta = await asyncio.to_thread(
            synthesize_speech,
            payload.text,
            payload.voice_id,
            professional_clone=professional_clone,
            explicit_consent=payload.explicit_voice_owner_consent,
        )
    except VoiceProviderError as exc:
        raise _provider_http_error(exc) from exc

    org_id = str(current_user.organization_id)
    filename = f"voice-{uuid.uuid4()}.mp3"
    try:
        stored = await FileUploadService.store_bytes(
            file_content=audio,
            filename=filename,
            content_type="audio/mpeg",
            org_id=org_id,
            allowed_types=ALLOWED_AUDIO_TYPES,
        )
        attachment = FileAttachmentRepository(db).create_attachment(
            file_url=stored["file_url"],
            filename=stored["filename"],
            content_type=stored["content_type"],
            file_size=stored["size"],
            organization_id=current_user.organization_id,
            uploaded_by_user_id=current_user.id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="voice_asset_persistence_failed",
        ) from exc

    return {
        "attachment": {
            "id": attachment.id,
            "file_url": attachment.file_url,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "file_size": attachment.file_size,
        },
        "provider": provider_meta,
        "send_authority": "message_delivery/ChannelAdapter.send_media",
    }


@router.post("/pvc/eligibility")
async def check_professional_voice_clone_eligibility(
    payload: ProfessionalVoiceCloneEligibilityRequest,
    current_user: User = Depends(get_current_user),
):
    """Fail closed unless ElevenLabs confirms a verified, fine-tuned PVC."""
    _ = current_user
    try:
        return await asyncio.to_thread(
            verify_professional_voice_clone,
            payload.voice_id,
            payload.explicit_voice_owner_consent,
        )
    except VoiceProviderError as exc:
        raise _provider_http_error(exc) from exc
