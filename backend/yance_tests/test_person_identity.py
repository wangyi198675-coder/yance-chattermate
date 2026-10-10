from pathlib import Path
import sys
import types

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_APP_ROOT = _BACKEND_ROOT / "app"
for name, path in {
    "app": _APP_ROOT,
    "app.models": _APP_ROOT / "models",
    "app.repositories": _APP_ROOT / "repositories",
    "app.channels": _APP_ROOT / "channels",
}.items():
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]
        sys.modules[name] = pkg
import importlib
import uuid

import pytest


def test_person_identity_module_exists_and_exposes_thin_customer_identity_model():
    module = importlib.import_module("app.models.person_identity")
    PersonIdentity = module.PersonIdentity
    assert PersonIdentity.__tablename__ == "person_identities"
    assert {
        "id", "organization_id", "customer_id", "channel_account_id",
        "identity_type", "raw_value", "normalized_value", "provenance",
        "merged_into_identity_id", "is_active", "created_at", "updated_at",
    }.issubset(PersonIdentity.__table__.columns.keys())
    index_names = {idx.name for idx in PersonIdentity.__table__.indexes}
    assert "uix_person_identity_global_active" in index_names
    assert "uix_person_identity_account_active" in index_names


def test_person_identity_normalization_and_stale_redirect_are_customer_centric():
    repo = importlib.import_module("app.repositories.person_identity")
    assert repo.normalize_identity_value("email", "  Alice@Example.COM ") == "alice@example.com"
    assert repo.normalize_identity_value("messenger", "  12345 ") == "12345"

    PersonIdentity = importlib.import_module("app.models.person_identity").PersonIdentity
    survivor_id = uuid.uuid4()
    stale_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    survivor = PersonIdentity(id=survivor_id, organization_id=uuid.uuid4(), customer_id=customer_id,
                              identity_type="messenger", raw_value="123", normalized_value="123")
    stale = PersonIdentity(id=stale_id, organization_id=survivor.organization_id, customer_id=customer_id,
                           identity_type="messenger", raw_value="old", normalized_value="old",
                           merged_into_identity_id=survivor_id, is_active=False)
    resolved = repo.follow_identity_redirect(stale, lambda ident_id: {survivor_id: survivor}.get(ident_id))
    assert resolved.id == survivor_id
    assert resolved.customer_id == customer_id


def test_person_identity_redirect_loop_fails_closed():
    repo = importlib.import_module("app.repositories.person_identity")
    PersonIdentity = importlib.import_module("app.models.person_identity").PersonIdentity
    a_id, b_id, customer_id, org_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    a = PersonIdentity(id=a_id, organization_id=org_id, customer_id=customer_id,
                       identity_type="telegram", raw_value="a", normalized_value="a", merged_into_identity_id=b_id)
    b = PersonIdentity(id=b_id, organization_id=org_id, customer_id=customer_id,
                       identity_type="telegram", raw_value="b", normalized_value="b", merged_into_identity_id=a_id)
    with pytest.raises(repo.IdentityRedirectLoop):
        repo.follow_identity_redirect(a, lambda ident_id: {a_id: a, b_id: b}.get(ident_id))

