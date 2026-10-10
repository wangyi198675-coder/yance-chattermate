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

Thin native wiring for admitted generative-media providers.

Provider execution is owned by OpenAI Images and Runway Dev. Durable assets are
always materialized through ChatterMate's existing FileAttachment/storage path.
This module owns no queue, asset table, or delivery path.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.file_attachment import FileAttachment
from app.repositories.file_attachment import FileAttachmentRepository
from app.services.file_storage import load_upload
from app.services.file_upload_service import (
    ALLOWED_IMAGE_TYPES,
    ALLOWED_VIDEO_TYPES,
    MAX_VIDEO_SIZE,
    FileUploadService,
)


class GenerativeMediaError(RuntimeError):
    pass


class ProviderNotConfigured(GenerativeMediaError):
    pass


class ProviderTaskNotReady(GenerativeMediaError):
    def __init__(self, status: str):
        super().__init__(f"provider task is not complete: {status}")
        self.status = status


_IMAGE_OUTPUT_TYPES = {
    "png": ("image/png", ".png"),
    "jpeg": ("image/jpeg", ".jpg"),
    "webp": ("image/webp", ".webp"),
}


def make_runway_task_handle(organization_id: UUID, task_id: str) -> str:
    """Bind a provider task id to one organization without creating task storage."""
    payload = f"runway:{organization_id}:{task_id}".encode("utf-8")
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return f"{task_id}.{signature}"


def resolve_runway_task_handle(organization_id: UUID, handle: str) -> str:
    try:
        task_id, provided = handle.rsplit(".", 1)
    except ValueError as exc:
        raise GenerativeMediaError("invalid Runway task handle") from exc
    expected = make_runway_task_handle(organization_id, task_id).rsplit(".", 1)[1]
    if not hmac.compare_digest(provided, expected):
        raise GenerativeMediaError("Runway task handle is not valid for this organization")
    return task_id


def _require_org_attachment(
    db: Session,
    organization_id: UUID,
    attachment_id: int,
    *,
    allowed_content_types: set[str],
) -> FileAttachment:
    row = FileAttachmentRepository(db).get_attachment(int(attachment_id))
    if row is None or row.organization_id != organization_id:
        raise GenerativeMediaError("attachment is unavailable to this organization")
    if row.content_type not in allowed_content_types:
        raise GenerativeMediaError(f"unsupported attachment content type: {row.content_type}")
    return row


def _named_buffer(data: bytes, filename: str) -> BytesIO:
    handle = BytesIO(data)
    handle.name = Path(filename).name or "input.bin"
    return handle


def _openai_result_bytes(response) -> bytes:
    data = getattr(response, "data", None)
    if not data:
        raise GenerativeMediaError("OpenAI Images returned no output")
    encoded = getattr(data[0], "b64_json", None)
    if not encoded and isinstance(data[0], dict):
        encoded = data[0].get("b64_json")
    if not encoded:
        raise GenerativeMediaError("OpenAI Images returned no base64 image")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise GenerativeMediaError("OpenAI Images returned invalid base64 image") from exc
    if not decoded:
        raise GenerativeMediaError("OpenAI Images returned an empty image")
    return decoded


async def _persist_generated(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by_user_id: Optional[UUID],
    content: bytes,
    filename: str,
    content_type: str,
) -> FileAttachment:
    stored = await FileUploadService.store_bytes(
        content,
        filename,
        content_type,
        str(organization_id),
    )
    return FileAttachmentRepository(db).create_attachment(
        file_url=stored["file_url"],
        filename=stored["filename"],
        content_type=stored["content_type"],
        file_size=stored["size"],
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
    )


async def generate_openai_image(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by_user_id: Optional[UUID],
    prompt: str,
    size: str = "1024x1024",
    quality: str = "auto",
    background: str = "auto",
    output_format: str = "png",
) -> FileAttachment:
    if not settings.OPENAI_API_KEY:
        raise ProviderNotConfigured("OPENAI_API_KEY is not configured")
    if output_format not in _IMAGE_OUTPUT_TYPES:
        raise GenerativeMediaError("unsupported image output format")
    content_type, suffix = _IMAGE_OUTPUT_TYPES[output_format]

    def call_provider() -> bytes:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.images.generate(
            model=settings.OPENAI_IMAGE_GENERATION_MODEL,
            prompt=prompt,
            size=size,
            quality=quality,
            background=background,
            output_format=output_format,
            n=1,
        )
        return _openai_result_bytes(response)

    content = await asyncio.to_thread(call_provider)
    return await _persist_generated(
        db,
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
        content=content,
        filename=f"openai-generated{suffix}",
        content_type=content_type,
    )


async def edit_openai_image(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by_user_id: Optional[UUID],
    prompt: str,
    source_attachment_ids: Iterable[int],
    mask_attachment_id: Optional[int] = None,
    size: str = "1024x1024",
    quality: str = "auto",
    background: str = "auto",
    output_format: str = "png",
) -> FileAttachment:
    if not settings.OPENAI_API_KEY:
        raise ProviderNotConfigured("OPENAI_API_KEY is not configured")
    ids = list(dict.fromkeys(int(value) for value in source_attachment_ids))
    if not ids or len(ids) > 16:
        raise GenerativeMediaError("image edit requires 1-16 source attachments")
    if output_format not in _IMAGE_OUTPUT_TYPES:
        raise GenerativeMediaError("unsupported image output format")
    supported_inputs = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    rows = [
        _require_org_attachment(
            db, organization_id, attachment_id, allowed_content_types=supported_inputs
        )
        for attachment_id in ids
    ]
    source_bytes = [await load_upload(row.file_url) for row in rows]

    mask_row = None
    mask_bytes = None
    if mask_attachment_id is not None:
        mask_row = _require_org_attachment(
            db,
            organization_id,
            mask_attachment_id,
            allowed_content_types={"image/png"},
        )
        mask_bytes = await load_upload(mask_row.file_url)
        if len(mask_bytes) >= 4 * 1024 * 1024:
            raise GenerativeMediaError("OpenAI image mask must be smaller than 4MB")

    content_type, suffix = _IMAGE_OUTPUT_TYPES[output_format]

    def call_provider() -> bytes:
        from openai import OpenAI

        images = [
            _named_buffer(content, row.filename)
            for content, row in zip(source_bytes, rows)
        ]
        kwargs = {
            "model": settings.OPENAI_IMAGE_EDIT_MODEL,
            "image": images,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "background": background,
            "output_format": output_format,
            "n": 1,
        }
        if mask_row is not None and mask_bytes is not None:
            kwargs["mask"] = _named_buffer(mask_bytes, mask_row.filename)
        response = OpenAI(api_key=settings.OPENAI_API_KEY).images.edit(**kwargs)
        return _openai_result_bytes(response)

    content = await asyncio.to_thread(call_provider)
    return await _persist_generated(
        db,
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
        content=content,
        filename=f"openai-edited{suffix}",
        content_type=content_type,
    )


def _runway_client():
    if not settings.RUNWAYML_API_SECRET:
        raise ProviderNotConfigured("RUNWAYML_API_SECRET is not configured")
    from runwayml import RunwayML

    return RunwayML(api_key=settings.RUNWAYML_API_SECRET)


async def _runway_upload_uri(row: FileAttachment) -> str:
    content = await load_upload(row.file_url)

    def upload() -> str:
        response = _runway_client().uploads.create_ephemeral(
            file=(Path(row.filename).name or "input.bin", content)
        )
        uri = getattr(response, "uri", None)
        if not uri:
            raise GenerativeMediaError("Runway ephemeral upload returned no URI")
        return uri

    return await asyncio.to_thread(upload)


async def start_runway_video_generation(
    db: Session,
    *,
    organization_id: UUID,
    prompt: str,
    image_attachment_id: Optional[int] = None,
    ratio: str = "1280:720",
    duration: int = 5,
) -> str:
    prompt_image = None
    if image_attachment_id is not None:
        row = _require_org_attachment(
            db,
            organization_id,
            image_attachment_id,
            allowed_content_types=set(ALLOWED_IMAGE_TYPES),
        )
        prompt_image = await _runway_upload_uri(row)

    def start() -> str:
        client = _runway_client()
        kwargs = {
            "model": settings.RUNWAY_VIDEO_GENERATION_MODEL,
            "prompt_text": prompt,
            "ratio": ratio,
            "duration": duration,
            "output_format": "mp4",
        }
        if prompt_image:
            task = client.image_to_video.create(
                prompt_image=prompt_image,
                **kwargs,
            )
        else:
            # Current Gen-4.5 text-to-video accepts only landscape/portrait.
            # Fail closed locally instead of relying on a provider-side 4xx.
            if settings.RUNWAY_VIDEO_GENERATION_MODEL == "gen4.5" and ratio not in {
                "1280:720",
                "720:1280",
            }:
                raise GenerativeMediaError(
                    "Gen-4.5 text-to-video supports 1280:720 or 720:1280"
                )
            task = client.text_to_video.create(**kwargs)
        task_id = getattr(task, "id", None)
        if not task_id:
            raise GenerativeMediaError("Runway returned no task id")
        return str(task_id)

    return await asyncio.to_thread(start)


async def start_runway_video_edit(
    db: Session,
    *,
    organization_id: UUID,
    prompt: str,
    video_attachment_id: int,
) -> str:
    row = _require_org_attachment(
        db,
        organization_id,
        video_attachment_id,
        allowed_content_types=set(ALLOWED_VIDEO_TYPES),
    )
    video_uri = await _runway_upload_uri(row)

    def start() -> str:
        task = _runway_client().video_to_video.create(
            model=settings.RUNWAY_VIDEO_EDIT_MODEL,
            video_uri=video_uri,
            prompt_text=prompt,
            output_format="mp4",
        )
        task_id = getattr(task, "id", None)
        if not task_id:
            raise GenerativeMediaError("Runway returned no task id")
        return str(task_id)

    return await asyncio.to_thread(start)


async def get_runway_task(task_id: str) -> dict:
    def retrieve() -> dict:
        task = _runway_client().tasks.retrieve(task_id)
        status = getattr(task, "status", None)
        if hasattr(status, "value"):
            status = status.value
        output = getattr(task, "output", None) or []
        return {
            "id": str(getattr(task, "id", task_id)),
            "status": str(status or "UNKNOWN").upper(),
            "output": list(output),
        }

    return await asyncio.to_thread(retrieve)


async def materialize_runway_video(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by_user_id: Optional[UUID],
    task_id: str,
) -> FileAttachment:
    filename = f"runway-{task_id}.mp4"
    existing = FileAttachmentRepository(db).get_by_filename_and_organization(
        filename, organization_id
    )
    if existing is not None:
        return existing

    task = await get_runway_task(task_id)
    if task["status"] != "SUCCEEDED":
        raise ProviderTaskNotReady(task["status"])
    if not task["output"]:
        raise GenerativeMediaError("Runway task succeeded without an output URL")
    output_url = str(task["output"][0])
    parsed = urlparse(output_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise GenerativeMediaError("Runway output URL is not a valid HTTPS URL")

    async with httpx.AsyncClient(timeout=90.0, follow_redirects=False) as client:
        response = await client.get(output_url)
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_VIDEO_SIZE:
            raise GenerativeMediaError("Runway output exceeds canonical video size limit")
        content = response.content
    if not content:
        raise GenerativeMediaError("Runway returned an empty video")

    return await _persist_generated(
        db,
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
        content=content,
        filename=filename,
        content_type="video/mp4",
    )
