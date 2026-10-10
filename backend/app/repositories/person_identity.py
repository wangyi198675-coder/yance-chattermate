"""Repository helpers for Customer-owned external identities."""
import re
from typing import Callable, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.person_identity import PersonIdentity

class IdentityRedirectError(RuntimeError): pass
class IdentityRedirectLoop(IdentityRedirectError): pass
class IdentityRedirectTargetMissing(IdentityRedirectError): pass
class IdentityRedirectScopeMismatch(IdentityRedirectError): pass

def normalize_identity_value(identity_type: str, value: str) -> str:
    kind = identity_type.strip().lower()
    normalized = value.strip()
    if kind == "email": return normalized.lower()
    if kind == "phone": return re.sub(r"[\s().-]", "", normalized)
    return normalized

def follow_identity_redirect(identity: PersonIdentity, load_identity: Callable[[UUID], Optional[PersonIdentity]]) -> PersonIdentity:
    current = identity
    seen: set[UUID] = set()
    while current.merged_into_identity_id:
        if current.id in seen: raise IdentityRedirectLoop("person identity redirect loop")
        seen.add(current.id)
        target = load_identity(current.merged_into_identity_id)
        if target is None: raise IdentityRedirectTargetMissing("person identity redirect target missing")
        if target.organization_id != current.organization_id: raise IdentityRedirectScopeMismatch("person identity redirect crossed organization scope")
        current = target
    return current

class PersonIdentityRepository:
    def __init__(self, db: Session): self.db = db
    def get_by_id(self, organization_id: UUID, identity_id: UUID) -> Optional[PersonIdentity]:
        return self.db.query(PersonIdentity).filter(PersonIdentity.organization_id == organization_id, PersonIdentity.id == identity_id).first()
    def get_active(self, organization_id: UUID, identity_type: str, value: str, channel_account_id: UUID | None = None) -> Optional[PersonIdentity]:
        q = self.db.query(PersonIdentity).filter(
            PersonIdentity.organization_id == organization_id,
            PersonIdentity.identity_type == identity_type.strip().lower(),
            PersonIdentity.normalized_value == normalize_identity_value(identity_type, value),
            PersonIdentity.merged_into_identity_id.is_(None), PersonIdentity.is_active.is_(True))
        q = q.filter(PersonIdentity.channel_account_id.is_(None)) if channel_account_id is None else q.filter(PersonIdentity.channel_account_id == channel_account_id)
        return q.first()
    def create(self, *, organization_id: UUID, customer_id: UUID, identity_type: str, value: str, channel_account_id: UUID | None = None, provenance: dict | None = None) -> PersonIdentity:
        row = PersonIdentity(organization_id=organization_id, customer_id=customer_id, channel_account_id=channel_account_id,
                             identity_type=identity_type.strip().lower(), raw_value=value,
                             normalized_value=normalize_identity_value(identity_type, value), provenance=provenance or {})
        self.db.add(row); return row
    def redirect(self, stale: PersonIdentity, surviving: PersonIdentity) -> None:
        if stale.id == surviving.id: raise IdentityRedirectLoop("identity cannot redirect to itself")
        if stale.organization_id != surviving.organization_id: raise IdentityRedirectScopeMismatch("cannot redirect identity across organizations")
        stale.merged_into_identity_id = surviving.id; stale.is_active = False
    def resolve_customer(self, identity: PersonIdentity):
        resolved = follow_identity_redirect(identity, lambda identity_id: self.get_by_id(identity.organization_id, identity_id))
        from app.repositories.people import PeopleRepository
        return PeopleRepository(self.db).get_customer(resolved.organization_id, resolved.customer_id)
