"""Strict shared persistence boundary for same-table FileAttachment.identity_metadata.

No extensibility bag, second asset store, or provider credentials.
"""
import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BoundedIdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


IdentityRole = Literal[
    "approved-self-photo",
    "persona-reference-image",
    "avatar-source",
    "image-generation-reference",
    "video-source-reference",
    "approved-voice-reference",
    "provider-profile-reference",
]


class IdentityConsent(BoundedIdentityModel):
    granted: bool = False
    basis: Optional[str] = Field(default=None, max_length=128)
    evidence_ref: Optional[str] = Field(default=None, max_length=512)


_CREDENTIAL_VALUE_PREFIX = re.compile(
    # Known authentication-material prefixes, never legitimate profile/voice/avatar
    # reference namespaces. Keep this narrowly scoped to this metadata field.
    r"^(?:xox[a-z]-|sk[-_]|rk_(?:live|test)_|gh[pousr]_|github_pat_|"
    r"glpat-|(?:AKIA|ASIA)[A-Z0-9]{12,}|AIza[A-Za-z0-9_-]{20,}|"
    r"whsec_|shp(?:at|ss|pa|ua)_|ya29\.)",
    re.IGNORECASE,
)


class IdentityProviderProfileRef(BoundedIdentityModel):
    # Only a non-secret provider name and identifier, not a URL or API credential.
    provider: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    profile_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

    @field_validator("profile_id")
    @classmethod
    def non_secret_identifier(cls, value: str) -> str:
        # Field shape is bounded, but never accept a credential-shaped reference.
        lowered = value.lower()
        if (
            _CREDENTIAL_VALUE_PREFIX.match(value)
            or any(
                marker in lowered
                for marker in (
                    "token", "secret", "password", "credential", "api_key",
                    "api-key", "apikey", "access_key", "access-key",
                    "accesskey", "bearer", "private_key", "private-key",
                )
            )
        ):
            raise ValueError("provider profile reference must be a non-secret profile id")
        if re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value):
            raise ValueError("provider profile reference must not be a JWT")
        return value


class IdentityProvenance(BoundedIdentityModel):
    source: str = Field(min_length=1, max_length=128)
    source_ref: Optional[str] = Field(default=None, max_length=1024)
    note: Optional[str] = Field(default=None, max_length=512)


class IdentityEligibility(BoundedIdentityModel):
    reference_image: bool = False
    avatar: bool = False
    voice: bool = False
    video: bool = False
    generation: bool = False


class IdentityQuality(BoundedIdentityModel):
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: Literal["unrated", "approved", "needs_review", "rejected"] = "unrated"
    note: Optional[str] = Field(default=None, max_length=512)


class FileAttachmentIdentityMetadataUpdate(BoundedIdentityModel):
    schema_version: Literal[1] = 1
    identity_role: IdentityRole
    persona_reference: Optional[str] = Field(default=None, max_length=512)
    avatar_role: Optional[Literal["source", "enrollment", "live-avatar"]] = None
    voice_reference: Optional[str] = Field(default=None, max_length=512)
    provider_profile_ref: Optional[IdentityProviderProfileRef] = None
    provenance: list[IdentityProvenance] = Field(min_length=1, max_length=16)
    consent: IdentityConsent
    active: bool = True
    eligibility: IdentityEligibility = Field(default_factory=IdentityEligibility)
    quality: IdentityQuality = Field(default_factory=IdentityQuality)
    explicit_approval: bool

    @model_validator(mode="after")
    def require_explicit_authorization(self):
        if not self.explicit_approval:
            raise ValueError("identity media requires explicit approval")
        if not self.consent.granted:
            raise ValueError("identity media requires recorded consent")
        return self


class FileAttachmentIdentityRevoke(BoundedIdentityModel):
    reason: str = Field(min_length=1, max_length=500)


class FileAttachmentIdentityMetadataStored(FileAttachmentIdentityMetadataUpdate):
    """Exactly bounded on-disk shape; only the repository controls revocation fields."""

    revoked: bool = False
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def terminal_revocation(self):
        if self.revoked:
            if self.active or not self.revoked_at or not self.revocation_reason:
                raise ValueError("revoked identity must be inactive with recorded revocation")
            if any(self.eligibility.model_dump().values()):
                raise ValueError("revoked identity cannot remain eligible")
        elif self.revoked_at is not None or self.revocation_reason is not None:
            raise ValueError("non-revoked identity cannot have a revocation receipt")
        return self
