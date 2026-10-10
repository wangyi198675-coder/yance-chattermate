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

import base64
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional, List, Set
from app.core.config import settings
from app.core.s3 import upload_file_to_s3, get_s3_signed_url
from app.core.logger import get_logger

logger = get_logger(__name__)

# Allowed file types and size limits
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'}
ALLOWED_DOCUMENT_TYPES = {'application/pdf', 'application/msword',
                          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                          'text/plain', 'text/csv', 'application/vnd.ms-excel',
                          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
ALLOWED_AUDIO_TYPES = {'audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/mp4'}
ALLOWED_VIDEO_TYPES = {'video/mp4', 'video/webm'}
ALLOWED_FILE_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_DOCUMENT_TYPES | ALLOWED_AUDIO_TYPES | ALLOWED_VIDEO_TYPES

# Security: SVG removed from default allowed types due to XSS risks
# Can be enabled per-agent if needed with proper sanitization

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB (documents/audio)
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_VIDEO_SIZE = 20 * 1024 * 1024  # bounded canonical video transport

# Magic byte signatures for file type validation
# This prevents MIME type spoofing attacks
MAGIC_BYTES = {
    # Images
    'image/jpeg': [
        (b'\xff\xd8\xff\xe0', 0),  # JPEG JFIF
        (b'\xff\xd8\xff\xe1', 0),  # JPEG EXIF
        (b'\xff\xd8\xff\xe2', 0),  # JPEG ICC
        (b'\xff\xd8\xff\xe8', 0),  # JPEG SPIFF
        (b'\xff\xd8\xff\xdb', 0),  # JPEG DQT
        (b'\xff\xd8\xff\xee', 0),  # JPEG Adobe
    ],
    'image/jpg': [
        (b'\xff\xd8\xff\xe0', 0),
        (b'\xff\xd8\xff\xe1', 0),
        (b'\xff\xd8\xff\xe2', 0),
        (b'\xff\xd8\xff\xe8', 0),
        (b'\xff\xd8\xff\xdb', 0),
        (b'\xff\xd8\xff\xee', 0),
    ],
    'image/png': [
        (b'\x89PNG\r\n\x1a\n', 0),
    ],
    'image/gif': [
        (b'GIF87a', 0),
        (b'GIF89a', 0),
    ],
    'image/webp': [
        (b'RIFF', 0),  # WebP starts with RIFF, then has WEBP at offset 8
    ],
    # Documents
    'application/pdf': [
        (b'%PDF-', 0),
    ],
    'application/msword': [
        (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 0),  # OLE Compound File (DOC)
    ],
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': [
        (b'PK\x03\x04', 0),  # ZIP-based (DOCX)
    ],
    'application/vnd.ms-excel': [
        (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 0),  # OLE Compound File (XLS)
    ],
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': [
        (b'PK\x03\x04', 0),  # ZIP-based (XLSX)
    ],
    'text/plain': [],  # Text files don't have magic bytes, validated by content
    'text/csv': [],  # CSV files don't have magic bytes, validated by content
    # Audio / video. Container-specific checks below tighten RIFF/ftyp handling.
    'audio/mpeg': [(b'ID3', 0), (b'\xff', 0)],
    'audio/ogg': [(b'OggS', 0)],
    'audio/wav': [(b'RIFF', 0)],
    'audio/mp4': [(b'ftyp', 4)],
    'video/mp4': [(b'ftyp', 4)],
    'video/webm': [(b'\x1a\x45\xdf\xa3', 0)],
}

# File extension to MIME type mapping for validation
EXTENSION_TO_MIME = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.txt': 'text/plain',
    '.csv': 'text/csv',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.mp3': 'audio/mpeg',
    '.ogg': 'audio/ogg',
    '.oga': 'audio/ogg',
    '.wav': 'audio/wav',
    '.m4a': 'audio/mp4',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
}

# Category labels for display
FILE_TYPE_CATEGORIES = {
    'images': {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'},
    'documents': {'application/pdf'},
    'office': {'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
               'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
    'text': {'text/plain', 'text/csv'},
    'audio': set(ALLOWED_AUDIO_TYPES),
    'video': set(ALLOWED_VIDEO_TYPES),
}


class FileUploadService:
    """Service for handling file uploads to S3 or local storage with enhanced security"""
    
    @staticmethod
    def validate_magic_bytes(file_content: bytes, claimed_content_type: str) -> tuple[bool, Optional[str]]:
        """
        Validate file content against magic byte signatures to prevent MIME type spoofing.
        
        Args:
            file_content: The raw binary content of the file
            claimed_content_type: The MIME type claimed by the client
            
        Returns:
            (is_valid, error_message)
        """
        if claimed_content_type not in MAGIC_BYTES:
            logger.warning(f"Unknown content type for magic byte validation: {claimed_content_type}")
            return False, f"File type '{claimed_content_type}' is not allowed"
        
        signatures = MAGIC_BYTES[claimed_content_type]
        
        # Text files don't have magic bytes - validate as text content
        if not signatures:
            if claimed_content_type in {'text/plain', 'text/csv'}:
                # Check if content is valid text (not binary)
                try:
                    # Try to decode as UTF-8, allowing for some common encodings
                    sample = file_content[:8192]  # Check first 8KB
                    sample.decode('utf-8')
                    return True, None
                except UnicodeDecodeError:
                    try:
                        sample.decode('latin-1')
                        return True, None
                    except UnicodeDecodeError:
                        return False, "File content does not appear to be valid text"
            return True, None
        
        # Container formats need a second discriminator after their generic header.
        if claimed_content_type == 'image/webp':
            if len(file_content) >= 12 and file_content[:4] == b'RIFF' and file_content[8:12] == b'WEBP':
                return True, None
            return False, "File content does not match WebP format signature"
        if claimed_content_type == 'audio/wav':
            if len(file_content) >= 12 and file_content[:4] == b'RIFF' and file_content[8:12] == b'WAVE':
                return True, None
            return False, "File content does not match WAV format signature"
        if claimed_content_type == 'audio/mpeg':
            if file_content.startswith(b'ID3') or (
                len(file_content) >= 2 and file_content[0] == 0xFF and (file_content[1] & 0xE0) == 0xE0
            ):
                return True, None
            return False, "File content does not match MPEG audio format signature"
        
        # Check against all possible signatures for this MIME type
        for signature, offset in signatures:
            end_offset = offset + len(signature)
            if len(file_content) >= end_offset:
                if file_content[offset:end_offset] == signature:
                    return True, None
        
        return False, f"File content does not match the claimed type '{claimed_content_type}'. The file may be corrupted or mislabeled."
    
    @staticmethod
    def validate_extension(filename: str, claimed_content_type: str) -> tuple[bool, Optional[str]]:
        """
        Validate that file extension matches the claimed content type.
        
        Args:
            filename: The name of the file
            claimed_content_type: The MIME type claimed by the client
            
        Returns:
            (is_valid, error_message)
        """
        ext = os.path.splitext(filename.lower())[1]
        
        if not ext:
            return False, "File must have an extension"
        
        if ext not in EXTENSION_TO_MIME:
            return False, f"File extension '{ext}' is not allowed. Allowed extensions: {', '.join(sorted(EXTENSION_TO_MIME.keys()))}"
        
        expected_mime = EXTENSION_TO_MIME[ext]
        
        # Handle jpg/jpeg equivalence
        if claimed_content_type in {'image/jpeg', 'image/jpg'} and expected_mime in {'image/jpeg', 'image/jpg'}:
            return True, None
        
        if expected_mime != claimed_content_type:
            return False, f"File extension '{ext}' does not match content type '{claimed_content_type}'"
        
        return True, None
    
    @staticmethod
    def validate_file_type(content_type: str, allowed_types: Optional[Set[str]] = None) -> bool:
        """
        Validate if the file type is allowed.
        
        Args:
            content_type: The MIME type to validate
            allowed_types: Optional set of allowed MIME types. If None, uses default ALLOWED_FILE_TYPES.
        """
        types_to_check = allowed_types if allowed_types is not None else ALLOWED_FILE_TYPES
        return content_type in types_to_check
    
    @staticmethod
    def get_allowed_types_for_agent(agent_allowed_types: Optional[List[str]] = None) -> Set[str]:
        """
        Get the set of allowed file types for an agent.
        
        Args:
            agent_allowed_types: List of category names like ['images', 'documents', 'office', 'text']
                                 If None or empty, returns all default allowed types.
        
        Returns:
            Set of MIME types that are allowed
        """
        if not agent_allowed_types:
            return ALLOWED_FILE_TYPES
        
        allowed = set()
        for category in agent_allowed_types:
            category_lower = category.lower()
            if category_lower in FILE_TYPE_CATEGORIES:
                allowed.update(FILE_TYPE_CATEGORIES[category_lower])
        
        # If no valid categories found, return default
        if not allowed:
            return ALLOWED_FILE_TYPES
        
        return allowed
    
    @staticmethod
    def validate_file_size(file_size: int, content_type: str) -> tuple[bool, Optional[str]]:
        """
        Validate file size based on content type
        Returns: (is_valid, error_message)
        """
        if content_type in ALLOWED_IMAGE_TYPES and file_size > MAX_IMAGE_SIZE:
            return False, f"Image file size exceeds maximum allowed size of {MAX_IMAGE_SIZE / (1024*1024):.1f}MB"
        if content_type in ALLOWED_VIDEO_TYPES and file_size > MAX_VIDEO_SIZE:
            return False, f"Video file size exceeds maximum allowed size of {MAX_VIDEO_SIZE / (1024*1024):.1f}MB"
        
        if file_size > MAX_FILE_SIZE and content_type not in ALLOWED_VIDEO_TYPES:
            return False, f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024*1024):.1f}MB"
        
        return True, None
    
    @staticmethod
    def get_friendly_allowed_types_message(allowed_types: Optional[Set[str]] = None) -> str:
        """Generate a user-friendly message listing allowed file types."""
        types_to_use = allowed_types if allowed_types is not None else ALLOWED_FILE_TYPES
        
        extensions = []
        for ext, mime in EXTENSION_TO_MIME.items():
            if mime in types_to_use:
                extensions.append(ext.upper().replace('.', ''))
        
        return ', '.join(sorted(set(extensions)))

    @staticmethod
    def _local_media_root(*, create: bool = False) -> Path:
        """Return the single durable local media root.

        Desktop production must provide YANCE_DATA_ROOT. Private attachment
        storage never falls back to the process working directory.
        """
        raw_root = str(settings.YANCE_DATA_ROOT or "").strip()
        if not raw_root:
            raise RuntimeError("Yance data root is not configured")

        data_root = Path(raw_root).expanduser()
        if not data_root.is_absolute():
            raise RuntimeError("Yance data root must be absolute")

        media_root = data_root / "media"
        try:
            if create:
                media_root.mkdir(parents=True, exist_ok=True)
            elif not media_root.is_dir():
                raise RuntimeError("Private media storage is unavailable")
            return media_root.resolve(strict=True)
        except RuntimeError:
            raise
        except OSError as exc:
            raise RuntimeError("Private media storage is unavailable") from exc

    @staticmethod
    def resolve_local_attachment_path(
        storage_key: str,
        *,
        create_parent: bool = False,
    ) -> Path:
        """Resolve one canonical private attachment key under Yance data/media.

        Only chat_attachments/<org UUID>/<object> is accepted. Resolution is
        containment-checked after following existing filesystem links so a
        symlink/reparse escape cannot become an alternate file-serving path.
        """
        key = str(storage_key or "").strip().lstrip("/")
        if key.startswith("uploads/"):
            key = key[len("uploads/"):]
        if (
            not key
            or "\\" in key
            or "\x00" in key
            or "%" in key
            or ":" in key
        ):
            raise ValueError("Invalid attachment storage key")

        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "chat_attachments":
            raise ValueError("Invalid attachment storage key")

        try:
            org_id = str(uuid.UUID(parts[1]))
        except (ValueError, AttributeError) as exc:
            raise ValueError("Invalid attachment storage key") from exc
        if org_id != parts[1].lower():
            raise ValueError("Invalid attachment storage key")

        object_name = parts[2]
        if (
            not object_name
            or object_name in {".", ".."}
            or any(
                not (char.isascii() and (char.isalnum() or char in {"-", "_", "."}))
                for char in object_name
            )
        ):
            raise ValueError("Invalid attachment storage key")

        media_root = FileUploadService._local_media_root(create=create_parent)
        candidate = media_root / "chat_attachments" / org_id / object_name
        try:
            if create_parent:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                resolved_parent = candidate.parent.resolve(strict=True)
                resolved_parent.relative_to(media_root)
                candidate = resolved_parent / object_name
            resolved_candidate = candidate.resolve(strict=False)
            resolved_candidate.relative_to(media_root)
        except (OSError, ValueError) as exc:
            raise ValueError("Invalid attachment storage key") from exc
        return resolved_candidate

    @staticmethod
    def local_attachment_exists(storage_key: str) -> bool:
        path = FileUploadService.resolve_local_attachment_path(storage_key)
        try:
            return path.is_file()
        except OSError as exc:
            raise RuntimeError("Private media storage is unavailable") from exc
    
    @staticmethod
    async def store_bytes(
        file_content: bytes,
        filename: str,
        content_type: str,
        org_id: str,
        allowed_types: Optional[Set[str]] = None,
        storage_identity: Optional[str] = None,
    ) -> Dict[str, any]:
        """Validate raw bytes once, then persist through the existing chat-attachment storage."""
        try:
            if not file_content or not filename:
                raise ValueError("Missing required file data: content and filename")
            content_type = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
            types_allowed = allowed_types if allowed_types is not None else ALLOWED_FILE_TYPES
            friendly_types = FileUploadService.get_friendly_allowed_types_message(types_allowed)

            is_valid, error = FileUploadService.validate_extension(filename, content_type)
            if not is_valid:
                logger.warning(f"Extension validation failed for {filename}: {error}")
                raise ValueError(error)
            if not FileUploadService.validate_file_type(content_type, types_allowed):
                raise ValueError(f"File type '{content_type}' is not allowed. Allowed types: {friendly_types}")

            file_size = len(file_content)
            is_valid, error = FileUploadService.validate_file_size(file_size, content_type)
            if not is_valid:
                raise ValueError(error)
            is_valid, error = FileUploadService.validate_magic_bytes(file_content, content_type)
            if not is_valid:
                logger.warning(f"Magic byte validation failed for {filename}: {error}")
                raise ValueError(f"Security check failed: {error}")

            file_extension = os.path.splitext(filename)[1].lower()
            if storage_identity is not None:
                storage_identity = str(storage_identity).strip()
                if (
                    not storage_identity
                    or len(storage_identity) > 160
                    or any(
                        not (char.isalnum() or char in {"-", "_"})
                        for char in storage_identity
                    )
                ):
                    raise ValueError("Invalid attachment storage identity")
                unique_filename = f"{storage_identity}{file_extension}"
            else:
                unique_filename = f"{uuid.uuid4()}{file_extension}"
            folder = f"chat_attachments/{org_id}"

            if settings.S3_FILE_STORAGE:
                file_url = await upload_file_to_s3(
                    file_content=file_content,
                    folder=folder,
                    filename=unique_filename,
                    content_type=content_type,
                )
                signed_url = await get_s3_signed_url(file_url)
            else:
                storage_key = f"{folder}/{unique_filename}"
                file_path = FileUploadService.resolve_local_attachment_path(
                    storage_key,
                    create_parent=True,
                )

                # W89 same-intent replay reuses its deterministic object key. If
                # a crash happened after materialization but before FileAttachment
                # commit, identical bytes are already the canonical physical
                # object and must not be duplicated.
                if file_path.exists():
                    existing = file_path.read_bytes()
                    if existing != file_content:
                        raise ValueError("Attachment storage identity conflict")
                else:
                    temp_path: Optional[Path] = None
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="wb",
                            dir=str(file_path.parent),
                            prefix=f".{file_path.name}.",
                            suffix=".tmp",
                            delete=False,
                        ) as handle:
                            temp_path = Path(handle.name)
                            handle.write(file_content)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temp_path, file_path)
                        temp_path = None
                    finally:
                        if temp_path is not None:
                            try:
                                temp_path.unlink(missing_ok=True)
                            except OSError:
                                logger.warning(
                                    "Could not remove failed attachment staging file",
                                    exc_info=True,
                                )

                # FileAttachment stores only a logical authenticated route, never
                # the absolute durable path. Legacy /uploads/... rows remain
                # readable through the same download endpoint but the private
                # static prefix is closed in main.py.
                file_url = f"{settings.API_V1_STR}/files/download/{storage_key}"
                signed_url = file_url

            logger.info(f"Stored validated attachment: {filename} -> {file_url}")
            return {
                "file_url": file_url,
                "signed_url": signed_url,
                "filename": filename,
                "content_type": content_type,
                "size": file_size,
            }
        except ValueError:
            raise
        except Exception as exc:
            logger.error(f"Error storing attachment bytes: {exc}", exc_info=True)
            raise ValueError(f"Failed to upload file: {exc}")

    @staticmethod
    async def upload_file(
        file_data: dict,
        org_id: str,
        customer_id: Optional[str] = None,
        user_id: Optional[str] = None,
        allowed_types: Optional[Set[str]] = None,
        storage_identity: Optional[str] = None,
    ) -> Dict[str, any]:
        """Decode a client upload and pass it through the canonical byte validator/storage path."""
        filename = file_data.get("filename", "")
        if not file_data.get("content") or not filename:
            raise ValueError("Missing required file data: content and filename")
        try:
            file_content = base64.b64decode(file_data["content"], validate=True)
        except Exception as exc:
            logger.error(f"Error decoding base64 content: {exc}")
            raise ValueError("Invalid file content encoding")
        return await FileUploadService.store_bytes(
            file_content=file_content,
            filename=filename,
            content_type=file_data.get("content_type", "application/octet-stream"),
            org_id=org_id,
            allowed_types=allowed_types,
            storage_identity=storage_identity,
        )

