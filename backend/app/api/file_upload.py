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
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, status, Header, Request
from fastapi.responses import JSONResponse
from typing import Optional
import uuid
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.s3 import upload_file_to_s3, get_s3_signed_url
from app.core.logger import get_logger
from app.core.security import verify_conversation_token
from app.models import User
from app.core.auth import CHAT_MANAGE_PERMISSIONS, get_current_user, require_any_permission
from app.database import get_db
from app.services.file_upload_service import FileUploadService
from app.repositories.file_attachment import FileAttachmentRepository
from app.schemas.file_attachment_identity import (
    IdentityRole,
    IdentityConsent,
    IdentityProviderProfileRef,
    IdentityProvenance,
    IdentityEligibility,
    IdentityQuality,
    FileAttachmentIdentityMetadataUpdate,
    FileAttachmentIdentityRevoke,
)


logger = get_logger(__name__)


router = APIRouter()



def _identity_metadata_payload(attachment) -> dict:
    return {
        "attachment_id": attachment.id,
        "organization_id": str(attachment.organization_id),
        "identity_metadata": dict(attachment.identity_metadata or {}),
    }


require_identity_media_user = require_any_permission(*CHAT_MANAGE_PERMISSIONS)

# Allowed file types and size limits
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml'}
ALLOWED_DOCUMENT_TYPES = {'application/pdf', 'application/msword', 
                          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                          'text/plain', 'text/csv', 'application/vnd.ms-excel',
                          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
ALLOWED_FILE_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_DOCUMENT_TYPES

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB


def get_cors_headers(request: Request) -> dict:
    """
    Get CORS headers for responses with credentials support
    """
    origin = request.headers.get('origin', '*')
    return {
        'Access-Control-Allow-Origin': origin,
        'Access-Control-Allow-Credentials': 'true',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Conversation-Token',
        'Access-Control-Max-Age': '3600'
    }


async def get_current_user_or_widget(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
    x_conversation_token: Optional[str] = Header(None)
) -> dict:
    """
    Get current user from JWT token, cookies, or widget conversation token
    Returns dict with user info or widget info
    """
    # Try to get user from cookies or Authorization header (admin/agent users)
    try:
        # Call get_current_user with the request - it handles both cookies and headers
        user = await get_current_user(request, None, db)
        if user:
            return {
                "type": "user",
                "user_id": str(user.id),
                "org_id": str(user.organization_id)
            }
    except HTTPException:
        # User auth failed, continue to try other methods
        pass
    except Exception as e:
        logger.error(f"Error authenticating user: {str(e)}")
    
    # Try to get widget info from conversation token
    if x_conversation_token:
        try:
            payload = verify_conversation_token(x_conversation_token)
            if payload:
                return {
                    "type": "widget",
                    "widget_id": payload.get("widget_id"),
                    "org_id": payload.get("org_id"),
                    "customer_id": payload.get("customer_id")
                }
        except Exception as e:
            logger.error(f"Error verifying conversation token: {str(e)}")
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required"
    )


def authorized_attachment_key(file_path: str, org_id: Optional[str]) -> str:
    """Resolve a download path to a storage key the caller is allowed to read.

    Uploads only ever land at `chat_attachments/<org_id>/<uuid>.<ext>` (see
    FileUploadService.upload_file), so anything else is not a servable
    attachment. Matching that shape exactly is what both scopes the read to the
    caller's organization and rules out traversal — no `..` segment can
    survive a three-part match on a UUID directory.
    """
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Request-key parsing is a security boundary. FastAPI decodes path
    # separators before this function sees them, so reject non-canonical
    # slash forms before applying the narrow legacy "uploads/" projection.
    if (
        not file_path
        or file_path.startswith('/')
        or '//' in file_path
        or '\\' in file_path
        or '\x00' in file_path
        or '%' in file_path
        or ':' in file_path
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    clean_path = file_path
    if clean_path.startswith('uploads/'):
        clean_path = clean_path[len('uploads/'):]

    parts = clean_path.split('/')
    if len(parts) != 3 or parts[0] != 'chat_attachments' or not parts[2]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    try:
        path_org_id = uuid.UUID(parts[1])
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    object_name = parts[2]
    if (
        object_name in {'.', '..'}
        or any(
            not (char.isascii() and (char.isalnum() or char in {'-', '_', '.'}))
            for char in object_name
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # 404 rather than 403: whether another org's attachment exists is itself
    # something the caller shouldn't learn.
    if str(path_org_id) != str(org_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    return '/'.join(('chat_attachments', str(path_org_id), object_name))


@router.get("/download/{file_path:path}")
async def download_file(
    file_path: str,
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
    x_conversation_token: Optional[str] = Header(None)
):
    """
    Download/serve a file from AWS S3 or local storage

    Usage: GET /api/v1/files/download/chat_attachments/org-id/filename.jpg
    """
    try:
        from fastapi.responses import StreamingResponse
        from app.core.s3 import get_s3_client
        import io

        # Authentication is required, and the result is what authorizes the
        # read below. This used to swallow the failure and serve the file
        # anyway, making every org's attachments world-readable by path.
        auth_info = await get_current_user_or_widget(
            request, db, authorization, x_conversation_token)
        storage_key = authorized_attachment_key(file_path, auth_info.get("org_id"))

        if not settings.S3_FILE_STORAGE:
            # Authentication and org authorization above must happen before any
            # local filesystem probe. The existing FileUploadService owns the
            # one durable local resolver under YANCE_DATA_ROOT/media.
            try:
                local_file_path = FileUploadService.resolve_local_attachment_path(storage_key)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found"
                )
            except RuntimeError as exc:
                logger.error("Private media storage unavailable", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="File storage unavailable"
                ) from exc

            try:
                if not local_file_path.is_file():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="File not found"
                    )
                file_content = local_file_path.read_bytes()
            except HTTPException:
                raise
            except FileNotFoundError:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found"
                )
            except OSError as exc:
                logger.error("Private media read failed", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="File storage unavailable"
                ) from exc

            import mimetypes
            content_type, _ = mimetypes.guess_type(str(local_file_path))
            content_type = content_type or "application/octet-stream"

            return StreamingResponse(
                io.BytesIO(file_content),
                media_type=content_type,
                headers={"Content-Disposition": f"inline; filename={local_file_path.name}"}
            )
        
        # For AWS S3 - stream file from S3
        try:
            s3_client = get_s3_client()
        except Exception as client_err:
            logger.error(f"Failed to create S3 client: {str(client_err)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create S3 client"
            )
        
        # S3 keys don't include the /uploads/ prefix
        s3_key = storage_key
        bucket = settings.S3_BUCKET
        
        # Check if the file exists
        try:
            s3_client.head_object(Bucket=bucket, Key=s3_key)
        except s3_client.exceptions.NoSuchKey:
            logger.warning(f"File not found in S3: {s3_key}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        except Exception as head_err:
            logger.error(f"Error checking file in S3: {str(head_err)}", exc_info=True)
        
        # Get the object from S3
        try:
            response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        except s3_client.exceptions.NoSuchKey:
            logger.warning(f"File not found in S3: {s3_key}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        except Exception as s3_err:
            logger.error(f"S3 error: {str(s3_err)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve file from S3"
            )
        
        # Stream the file back to client
        def generate():
            while True:
                chunk = response['Body'].read(8192)
                if not chunk:
                    break
                yield chunk
        
        # Determine content type
        content_type = response.get('ContentType', 'application/octet-stream')
        
        # Extract filename from the validated key
        filename = storage_key.split('/')[-1]
        
        logger.info(f"Streaming file from S3: {filename}, content-type: {content_type}")
        return StreamingResponse(
            generate(),
            media_type=content_type,
            headers={"Content-Disposition": f"inline; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception:
        logger.error("Unexpected private file download failure", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download file"
        )


@router.get("/attachments/{attachment_id}/identity-metadata")
async def get_attachment_identity_metadata(
    attachment_id: int,
    current_user: User = Depends(require_identity_media_user),
    db: Session = Depends(get_db),
):
    attachment = FileAttachmentRepository(db).get_attachment_for_organization(
        attachment_id, current_user.organization_id
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return _identity_metadata_payload(attachment)


@router.put("/attachments/{attachment_id}/identity-metadata")
async def put_attachment_identity_metadata(
    attachment_id: int,
    payload: FileAttachmentIdentityMetadataUpdate,
    current_user: User = Depends(require_identity_media_user),
    db: Session = Depends(get_db),
):
    storage_payload = payload.model_dump(mode="json")
    try:
        attachment = FileAttachmentRepository(db).update_identity_metadata(
            attachment_id,
            current_user.organization_id,
            storage_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return _identity_metadata_payload(attachment)


@router.post("/attachments/{attachment_id}/identity-metadata/revoke")
async def revoke_attachment_identity_metadata(
    attachment_id: int,
    payload: FileAttachmentIdentityRevoke,
    current_user: User = Depends(require_identity_media_user),
    db: Session = Depends(get_db),
):
    try:
        attachment = FileAttachmentRepository(db).revoke_identity_metadata(
            attachment_id,
            current_user.organization_id,
            payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return _identity_metadata_payload(attachment)


@router.delete("/attachments/{attachment_id}/identity-asset")
async def delete_identity_attachment(
    attachment_id: int,
    current_user: User = Depends(require_identity_media_user),
    db: Session = Depends(get_db),
):
    deleted = FileAttachmentRepository(db).delete_identity_attachment_for_organization(
        attachment_id, current_user.organization_id
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return {"attachment_id": attachment_id, "deleted": True}
