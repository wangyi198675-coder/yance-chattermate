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

from sqlalchemy.orm import Session
from app.models.file_attachment import FileAttachment
from app.schemas.file_attachment_identity import (
    FileAttachmentIdentityMetadataUpdate,
    FileAttachmentIdentityMetadataStored,
)
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime, timezone


class FileAttachmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_attachment(
        self,
        file_url: str,
        filename: str,
        content_type: str,
        file_size: int,
        organization_id: UUID,
        chat_history_id: Optional[int] = None,
        uploaded_by_user_id: Optional[UUID] = None,
        uploaded_by_customer_id: Optional[UUID] = None
    ) -> FileAttachment:
        """Create a new file attachment record"""
        attachment = FileAttachment(
            file_url=file_url,
            filename=filename,
            content_type=content_type,
            file_size=file_size,
            chat_history_id=chat_history_id,
            organization_id=organization_id,
            uploaded_by_user_id=uploaded_by_user_id,
            uploaded_by_customer_id=uploaded_by_customer_id
        )
        self.db.add(attachment)
        self.db.commit()
        self.db.refresh(attachment)
        return attachment

    def get_attachment(self, attachment_id: int) -> Optional[FileAttachment]:
        """Get a file attachment by ID"""
        return self.db.query(FileAttachment).filter(
            FileAttachment.id == attachment_id
        ).first()

    def get_attachment_for_organization(
        self, attachment_id: int, organization_id: UUID
    ) -> Optional[FileAttachment]:
        """Get one attachment without leaking cross-organization existence."""
        return self.db.query(FileAttachment).filter(
            FileAttachment.id == attachment_id,
            FileAttachment.organization_id == organization_id,
        ).first()

    def update_identity_metadata(
        self,
        attachment_id: int,
        organization_id: UUID,
        identity_metadata: Dict[str, Any],
    ) -> Optional[FileAttachment]:
        """Replace the bounded identity namespace on the canonical asset row."""
        attachment = self.get_attachment_for_organization(attachment_id, organization_id)
        if attachment is None:
            return None

        current = dict(attachment.identity_metadata or {})
        if current.get("revoked"):
            raise ValueError(
                "Revoked identity metadata is terminal; approve a replacement asset instead"
            )

        # Repository methods are callable without the API. Never persist raw dicts.
        # Reject extra keys (including credentials) at every nested level, then
        # serialize only the exact bounded, consented, approved model.
        payload = FileAttachmentIdentityMetadataUpdate.model_validate(
            identity_metadata
        ).model_dump(mode="json")
        payload.update(
            revoked=False, revoked_at=None, revocation_reason=None
        )
        attachment.identity_metadata = FileAttachmentIdentityMetadataStored.model_validate(
            payload
        ).model_dump(mode="json")
        self.db.commit()
        self.db.refresh(attachment)
        return attachment

    def revoke_identity_metadata(
        self,
        attachment_id: int,
        organization_id: UUID,
        reason: str,
    ) -> Optional[FileAttachment]:
        """Fail closed: a revoked identity asset cannot remain eligible for use."""
        attachment = self.get_attachment_for_organization(attachment_id, organization_id)
        if attachment is None:
            return None

        payload = dict(attachment.identity_metadata or {})
        if not payload:
            raise ValueError("Attachment has no identity metadata to revoke")
        # A revoke must not re-persist corrupted/legacy unbounded fields.
        payload = FileAttachmentIdentityMetadataStored.model_validate(
            payload
        ).model_dump(mode="json")
        if payload["revoked"]:
            raise ValueError("Revoked identity metadata is terminal")
        eligibility = dict(payload["eligibility"])
        for key in ("reference_image", "avatar", "voice", "video", "generation"):
            eligibility[key] = False

        payload.update(
            {
                "active": False,
                "revoked": True,
                "revoked_at": datetime.now(timezone.utc).isoformat(),
                "revocation_reason": reason,
                "eligibility": eligibility,
            }
        )
        attachment.identity_metadata = FileAttachmentIdentityMetadataStored.model_validate(
            payload
        ).model_dump(mode="json")
        self.db.commit()
        self.db.refresh(attachment)
        return attachment

    def delete_identity_attachment_for_organization(
        self, attachment_id: int, organization_id: UUID
    ) -> bool:
        """Delete one identity-marked canonical asset without crossing org boundaries."""
        attachment = self.get_attachment_for_organization(attachment_id, organization_id)
        if attachment is None or not dict(attachment.identity_metadata or {}):
            return False
        self.db.delete(attachment)
        self.db.commit()
        return True

    def get_by_filename_and_organization(
        self, filename: str, organization_id: UUID
    ) -> Optional[FileAttachment]:
        """Find one canonical attachment for provider-task materialization idempotence."""
        return self.db.query(FileAttachment).filter(
            FileAttachment.filename == filename,
            FileAttachment.organization_id == organization_id,
        ).order_by(FileAttachment.id.asc()).first()

    def get_attachments_by_chat_history(
        self, chat_history_id: int
    ) -> List[FileAttachment]:
        """Get all attachments for a chat message"""
        return self.db.query(FileAttachment).filter(
            FileAttachment.chat_history_id == chat_history_id
        ).all()

    def get_attachments_by_organization(
        self, organization_id: UUID, limit: int = 100
    ) -> List[FileAttachment]:
        """Get all attachments for an organization"""
        return self.db.query(FileAttachment).filter(
            FileAttachment.organization_id == organization_id
        ).order_by(FileAttachment.created_at.desc()).limit(limit).all()

    def delete_attachment(self, attachment_id: int) -> bool:
        """Delete a file attachment"""
        attachment = self.get_attachment(attachment_id)
        if attachment:
            self.db.delete(attachment)
            self.db.commit()
            return True
        return False

    def link_attachment_to_message(
        self, attachment_id: int, chat_history_id: int
    ) -> Optional[FileAttachment]:
        """Link an existing attachment to a chat message"""
        attachment = self.get_attachment(attachment_id)
        if attachment:
            attachment.chat_history_id = chat_history_id
            self.db.commit()
            self.db.refresh(attachment)
            return attachment
        return None

    def adopt_attachments(
        self,
        attachment_ids: List[int],
        chat_history_id: int,
        organization_id: UUID,
        uploaded_by_user_id: Optional[UUID] = None,
    ) -> List[FileAttachment]:
        """Adopt pre-generated canonical FileAttachment rows into one message.

        This is deliberately an ownership-preserving link operation: it never
        copies file bytes and never creates a second asset record.
        """
        ids = list(dict.fromkeys(int(value) for value in attachment_ids))
        if not ids:
            return []
        rows = self.db.query(FileAttachment).filter(
            FileAttachment.id.in_(ids),
            FileAttachment.organization_id == organization_id,
        ).all()
        if len(rows) != len(ids):
            raise ValueError("One or more attachments are unavailable to this organization")
        by_id = {row.id: row for row in rows}
        ordered = [by_id[value] for value in ids]
        for row in ordered:
            if row.chat_history_id not in (None, chat_history_id):
                raise ValueError(f"Attachment {row.id} is already linked to another message")
            row.chat_history_id = chat_history_id
            if uploaded_by_user_id is not None and row.uploaded_by_user_id is None:
                row.uploaded_by_user_id = uploaded_by_user_id
        self.db.commit()
        for row in ordered:
            self.db.refresh(row)
        return ordered
