"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Authenticated API seam for canonical generative and deterministic media.
"""
from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import CHAT_MANAGE_PERMISSIONS, require_any_permission
from app.database import get_db
from app.models.user import User
from app.services.deterministic_media import (
    DeterministicMediaError,
    transform_image,
    transform_video,
)
from app.services.file_storage import resolve_public_url
from app.services.generative_media import (
    GenerativeMediaError,
    ProviderNotConfigured,
    ProviderTaskNotReady,
    edit_openai_image,
    generate_openai_image,
    get_runway_task,
    make_runway_task_handle,
    materialize_runway_video,
    resolve_runway_task_handle,
    start_runway_video_edit,
    start_runway_video_generation,
)


router = APIRouter()
require_media_user = require_any_permission(*CHAT_MANAGE_PERMISSIONS)


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    size: str = Field(default="1024x1024", min_length=3, max_length=32)
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "auto"
    background: Literal["transparent", "opaque", "auto"] = "auto"
    output_format: Literal["png", "jpeg", "webp"] = "png"


class ImageEditRequest(ImageGenerateRequest):
    source_attachment_ids: list[int] = Field(min_length=1, max_length=16)
    mask_attachment_id: Optional[int] = None


class VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    image_attachment_id: Optional[int] = None
    ratio: Literal[
        "1280:720",
        "720:1280",
        "1104:832",
        "960:960",
        "832:1104",
        "1584:672",
        "672:1584",
    ] = "1280:720"
    duration: int = Field(default=5, ge=2, le=10)


class VideoEditRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    video_attachment_id: int


class DeterministicImageRequest(BaseModel):
    attachment_id: int
    operation: Literal["resize", "crop", "convert"]
    output_format: Literal["png", "jpeg", "webp"] = "png"
    width: Optional[int] = Field(default=None, ge=1, le=8192)
    height: Optional[int] = Field(default=None, ge=1, le=8192)
    x: int = Field(default=0, ge=0)
    y: int = Field(default=0, ge=0)


class DeterministicVideoRequest(BaseModel):
    attachment_id: int
    operation: Literal["trim", "transcode"]
    start_seconds: float = Field(default=0, ge=0)
    duration_seconds: Optional[float] = Field(default=None, gt=0, le=3600)


async def _attachment_payload(row) -> dict:
    return {
        "id": row.id,
        "filename": row.filename,
        "file_url": await resolve_public_url(row.file_url),
        "content_type": row.content_type,
        "file_size": row.file_size,
    }


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProviderNotConfigured):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, ProviderTaskNotReady):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "provider_status": exc.status},
        )
    if isinstance(exc, (GenerativeMediaError, DeterministicMediaError, ValueError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="media provider failed")


@router.post("/image/generate")
async def create_image(
    body: ImageGenerateRequest,
    current_user: User = Depends(require_media_user),
    db: Session = Depends(get_db),
):
    try:
        row = await generate_openai_image(
            db,
            organization_id=UUID(str(current_user.organization_id)),
            uploaded_by_user_id=UUID(str(current_user.id)),
            **body.model_dump(),
        )
        return {"provider": "openai", "attachment": await _attachment_payload(row)}
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/image/edit")
async def edit_image(
    body: ImageEditRequest,
    current_user: User = Depends(require_media_user),
    db: Session = Depends(get_db),
):
    try:
        row = await edit_openai_image(
            db,
            organization_id=UUID(str(current_user.organization_id)),
            uploaded_by_user_id=UUID(str(current_user.id)),
            **body.model_dump(),
        )
        return {"provider": "openai", "attachment": await _attachment_payload(row)}
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/video/generate", status_code=status.HTTP_202_ACCEPTED)
async def create_video(
    body: VideoGenerateRequest,
    current_user: User = Depends(require_media_user),
    db: Session = Depends(get_db),
):
    try:
        task_id = await start_runway_video_generation(
            db,
            organization_id=UUID(str(current_user.organization_id)),
            **body.model_dump(),
        )
        return {
            "provider": "runway",
            "task_id": task_id,
            "task_handle": make_runway_task_handle(
                UUID(str(current_user.organization_id)), task_id
            ),
            "status": "PENDING",
        }
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/video/edit", status_code=status.HTTP_202_ACCEPTED)
async def edit_video(
    body: VideoEditRequest,
    current_user: User = Depends(require_media_user),
    db: Session = Depends(get_db),
):
    try:
        task_id = await start_runway_video_edit(
            db,
            organization_id=UUID(str(current_user.organization_id)),
            **body.model_dump(),
        )
        return {
            "provider": "runway",
            "task_id": task_id,
            "task_handle": make_runway_task_handle(
                UUID(str(current_user.organization_id)), task_id
            ),
            "status": "PENDING",
        }
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/video/tasks/{task_handle}")
async def video_task_status(
    task_handle: str,
    current_user: User = Depends(require_media_user),
):
    try:
        organization_id = UUID(str(current_user.organization_id))
        task_id = resolve_runway_task_handle(organization_id, task_handle)
        task = await get_runway_task(task_id)
        return {
            "provider": "runway",
            "id": task["id"],
            "status": task["status"],
            "output_ready": bool(task["output"]),
        }
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/video/tasks/{task_handle}/materialize")
async def materialize_video(
    task_handle: str,
    current_user: User = Depends(require_media_user),
    db: Session = Depends(get_db),
):
    try:
        organization_id = UUID(str(current_user.organization_id))
        task_id = resolve_runway_task_handle(organization_id, task_handle)
        row = await materialize_runway_video(
            db,
            organization_id=organization_id,
            uploaded_by_user_id=UUID(str(current_user.id)),
            task_id=task_id,
        )
        return {"provider": "runway", "attachment": await _attachment_payload(row)}
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/deterministic/image")
async def deterministic_image(
    body: DeterministicImageRequest,
    current_user: User = Depends(require_media_user),
    db: Session = Depends(get_db),
):
    try:
        row = await transform_image(
            db,
            organization_id=UUID(str(current_user.organization_id)),
            uploaded_by_user_id=UUID(str(current_user.id)),
            **body.model_dump(),
        )
        return {"provider": "imagemagick", "attachment": await _attachment_payload(row)}
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/deterministic/video")
async def deterministic_video(
    body: DeterministicVideoRequest,
    current_user: User = Depends(require_media_user),
    db: Session = Depends(get_db),
):
    try:
        row = await transform_video(
            db,
            organization_id=UUID(str(current_user.organization_id)),
            uploaded_by_user_id=UUID(str(current_user.id)),
            **body.model_dump(),
        )
        return {"provider": "ffmpeg", "attachment": await _attachment_payload(row)}
    except Exception as exc:
        raise _translate_error(exc) from exc
