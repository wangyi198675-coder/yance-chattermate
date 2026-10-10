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

Canonical deterministic media transforms backed by ImageMagick and FFmpeg.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.file_attachment import FileAttachment
from app.repositories.file_attachment import FileAttachmentRepository
from app.services.external_media_cli import (
    image_convert_command,
    image_crop_command,
    image_resize_command,
    run_external_media,
    video_transcode_command,
    video_trim_command,
)
from app.services.file_storage import load_upload
from app.services.file_upload_service import ALLOWED_IMAGE_TYPES, ALLOWED_VIDEO_TYPES, FileUploadService


class DeterministicMediaError(RuntimeError):
    pass


_IMAGE_FORMATS = {
    "png": ("image/png", ".png"),
    "jpeg": ("image/jpeg", ".jpg"),
    "webp": ("image/webp", ".webp"),
}


def _get_attachment(
    db: Session,
    organization_id: UUID,
    attachment_id: int,
    allowed_types: set[str],
) -> FileAttachment:
    row = FileAttachmentRepository(db).get_attachment(int(attachment_id))
    if row is None or row.organization_id != organization_id:
        raise DeterministicMediaError("attachment is unavailable to this organization")
    if row.content_type not in allowed_types:
        raise DeterministicMediaError(f"unsupported attachment content type: {row.content_type}")
    return row


async def _persist(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by_user_id: Optional[UUID],
    content: bytes,
    filename: str,
    content_type: str,
) -> FileAttachment:
    stored = await FileUploadService.store_bytes(
        content, filename, content_type, str(organization_id)
    )
    return FileAttachmentRepository(db).create_attachment(
        file_url=stored["file_url"],
        filename=stored["filename"],
        content_type=stored["content_type"],
        file_size=stored["size"],
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
    )


async def transform_image(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by_user_id: Optional[UUID],
    attachment_id: int,
    operation: str,
    output_format: str = "png",
    width: Optional[int] = None,
    height: Optional[int] = None,
    x: int = 0,
    y: int = 0,
) -> FileAttachment:
    if output_format not in _IMAGE_FORMATS:
        raise DeterministicMediaError("unsupported deterministic image output format")
    row = _get_attachment(db, organization_id, attachment_id, set(ALLOWED_IMAGE_TYPES))
    source_bytes = await load_upload(row.file_url)
    content_type, suffix = _IMAGE_FORMATS[output_format]

    def execute() -> bytes:
        with tempfile.TemporaryDirectory(prefix="yance-imagemagick-") as temp_dir:
            temp = Path(temp_dir)
            source_suffix = Path(row.filename).suffix.lower() or ".png"
            source = temp / f"source{source_suffix}"
            destination = temp / f"result{suffix}"
            source.write_bytes(source_bytes)
            if operation == "resize":
                if not width or not height or width <= 0 or height <= 0:
                    raise DeterministicMediaError("resize requires positive width and height")
                command = image_resize_command(
                    settings.IMAGEMAGICK_BINARY, source, destination, width, height
                )
            elif operation == "crop":
                if not width or not height or width <= 0 or height <= 0 or x < 0 or y < 0:
                    raise DeterministicMediaError(
                        "crop requires positive width/height and non-negative x/y"
                    )
                command = image_crop_command(
                    settings.IMAGEMAGICK_BINARY, source, destination, width, height, x, y
                )
            elif operation == "convert":
                command = image_convert_command(
                    settings.IMAGEMAGICK_BINARY, source, destination
                )
            else:
                raise DeterministicMediaError("unsupported deterministic image operation")
            run_external_media(command)
            return destination.read_bytes()

    result = await asyncio.to_thread(execute)
    return await _persist(
        db,
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
        content=result,
        filename=f"imagemagick-{operation}{suffix}",
        content_type=content_type,
    )


async def transform_video(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by_user_id: Optional[UUID],
    attachment_id: int,
    operation: str,
    start_seconds: float = 0,
    duration_seconds: Optional[float] = None,
) -> FileAttachment:
    row = _get_attachment(db, organization_id, attachment_id, set(ALLOWED_VIDEO_TYPES))
    source_bytes = await load_upload(row.file_url)

    def execute() -> bytes:
        with tempfile.TemporaryDirectory(prefix="yance-ffmpeg-") as temp_dir:
            temp = Path(temp_dir)
            source_suffix = Path(row.filename).suffix.lower() or ".mp4"
            source = temp / f"source{source_suffix}"
            destination = temp / "result.mp4"
            source.write_bytes(source_bytes)
            if operation == "trim":
                if start_seconds < 0 or duration_seconds is None or duration_seconds <= 0:
                    raise DeterministicMediaError(
                        "trim requires non-negative start_seconds and positive duration_seconds"
                    )
                command = video_trim_command(
                    settings.FFMPEG_BINARY,
                    source,
                    destination,
                    start_seconds,
                    duration_seconds,
                )
            elif operation == "transcode":
                command = video_transcode_command(
                    settings.FFMPEG_BINARY,
                    source,
                    destination,
                    "libx264",
                    "aac",
                )
            else:
                raise DeterministicMediaError("unsupported deterministic video operation")
            run_external_media(command)
            return destination.read_bytes()

    result = await asyncio.to_thread(execute)
    return await _persist(
        db,
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
        content=result,
        filename=f"ffmpeg-{operation}.mp4",
        content_type="video/mp4",
    )
