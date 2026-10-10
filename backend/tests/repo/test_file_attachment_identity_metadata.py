from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.file_upload import (
    FileAttachmentIdentityMetadataUpdate,
    FileAttachmentIdentityRevoke,
    IdentityConsent,
    IdentityEligibility,
    IdentityProvenance,
    IdentityProviderProfileRef,
    IdentityQuality,
    get_attachment_identity_metadata,
    put_attachment_identity_metadata,
    revoke_attachment_identity_metadata,
    delete_identity_attachment,
)
from app.models.organization import Organization
from app.repositories.file_attachment import FileAttachmentRepository


def _make_attachment(repo, organization_id, user_id=None):
    return repo.create_attachment(
        file_url="chat_attachments/%s/identity.jpg" % organization_id,
        filename="identity.jpg",
        content_type="image/jpeg",
        file_size=1234,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
    )


def _payload():
    return FileAttachmentIdentityMetadataUpdate(
        identity_role="approved-self-photo",
        persona_reference="persona:primary",
        avatar_role="source",
        voice_reference=None,
        provider_profile_ref=IdentityProviderProfileRef(
            provider="heygen", profile_id="avatar-profile-1"
        ),
        provenance=[
            IdentityProvenance(
                source="explicit-user-upload",
                source_ref="conversation:42",
                note="approved source portrait",
            )
        ],
        consent=IdentityConsent(
            granted=True,
            basis="self-owned",
            evidence_ref="approval:42",
        ),
        active=True,
        eligibility=IdentityEligibility(
            reference_image=True,
            avatar=True,
            generation=True,
        ),
        quality=IdentityQuality(score=0.94, status="approved"),
        explicit_approval=True,
    )


def test_identity_metadata_defaults_empty_and_is_same_table(db, test_organization, test_user):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    assert row.identity_metadata == {}
    assert "identity_metadata" in row.__table__.c
    assert row.__table__.name == "file_attachments"


def test_identity_metadata_requires_approval_and_consent():
    base = dict(
        identity_role="persona-reference-image",
        provenance=[IdentityProvenance(source="upload")],
        consent=IdentityConsent(granted=True),
        explicit_approval=False,
    )
    with pytest.raises(ValueError, match="explicit approval"):
        FileAttachmentIdentityMetadataUpdate(**base)

    base["explicit_approval"] = True
    base["consent"] = IdentityConsent(granted=False)
    with pytest.raises(ValueError, match="recorded consent"):
        FileAttachmentIdentityMetadataUpdate(**base)


def test_identity_metadata_org_isolation_revoke_terminal_and_delete(
    db, test_organization, test_user
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)

    other_org = Organization(
        id=uuid4(),
        name="Other Organization",
        domain="other.example",
        timezone="UTC",
    )
    db.add(other_org)
    db.commit()

    assert repo.get_attachment_for_organization(row.id, other_org.id) is None
    assert repo.update_identity_metadata(row.id, other_org.id, _payload().model_dump(mode="json")) is None
    assert repo.revoke_identity_metadata(row.id, other_org.id, "wrong org") is None
    assert repo.delete_identity_attachment_for_organization(row.id, other_org.id) is False

    updated = repo.update_identity_metadata(
        row.id, test_organization.id, _payload().model_dump(mode="json")
    )
    assert updated.identity_metadata["identity_role"] == "approved-self-photo"
    assert updated.identity_metadata["explicit_approval"] is True
    assert updated.identity_metadata["consent"]["granted"] is True
    assert updated.identity_metadata["revoked"] is False

    revoked = repo.revoke_identity_metadata(
        row.id, test_organization.id, "consent withdrawn"
    )
    assert revoked.identity_metadata["active"] is False
    assert revoked.identity_metadata["revoked"] is True
    assert revoked.identity_metadata["revocation_reason"] == "consent withdrawn"
    assert revoked.identity_metadata["revoked_at"]
    assert not any(revoked.identity_metadata["eligibility"].values())

    with pytest.raises(ValueError, match="terminal"):
        repo.update_identity_metadata(
            row.id, test_organization.id, _payload().model_dump(mode="json")
        )

    assert repo.delete_identity_attachment_for_organization(row.id, test_organization.id) is True
    assert repo.get_attachment(row.id) is None


@pytest.mark.asyncio
async def test_identity_metadata_api_serialization_and_org_scope(
    db, test_organization, test_user
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)

    written = await put_attachment_identity_metadata(
        row.id, _payload(), current_user=test_user, db=db
    )
    assert written["attachment_id"] == row.id
    assert written["organization_id"] == str(test_organization.id)
    assert written["identity_metadata"]["quality"]["score"] == 0.94

    fetched = await get_attachment_identity_metadata(
        row.id, current_user=test_user, db=db
    )
    assert fetched == written

    revoked = await revoke_attachment_identity_metadata(
        row.id,
        FileAttachmentIdentityRevoke(reason="no longer approved"),
        current_user=test_user,
        db=db,
    )
    assert revoked["identity_metadata"]["revoked"] is True
    assert revoked["identity_metadata"]["active"] is False

    await_result = await delete_identity_attachment(row.id, current_user=test_user, db=db)
    assert await_result == {"attachment_id": row.id, "deleted": True}

    with pytest.raises(HTTPException) as exc:
        await get_attachment_identity_metadata(row.id, current_user=test_user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_identity_metadata_api_hides_cross_org_attachment(
    db, test_organization, test_user
):
    repo = FileAttachmentRepository(db)
    other_org = Organization(
        id=uuid4(),
        name="Other Organization 2",
        domain="other2.example",
        timezone="UTC",
    )
    db.add(other_org)
    db.commit()
    row = _make_attachment(repo, other_org.id)

    with pytest.raises(HTTPException) as exc:
        await get_attachment_identity_metadata(row.id, current_user=test_user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "forbidden_key",
    ["arbitrary", "token", "access_token", "api_key", "password",
     "secret", "credential", "revoked", "revoked_at", "revocation_reason"],
)
def test_direct_repository_rejects_unbounded_and_credentials_without_writes(
    db, test_organization, test_user, forbidden_key
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    candidate = _payload().model_dump(mode="json")
    candidate[forbidden_key] = "not-for-storage"
    with pytest.raises(ValueError):
        repo.update_identity_metadata(row.id, test_organization.id, candidate)
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == {}


@pytest.mark.parametrize(
    ("namespace", "forbidden_key"),
    [
        ("provider_profile_ref", "access_token"),
        ("provider_profile_ref", "secret"),
        ("provider_profile_ref", "credential"),
        ("consent", "password"),
        ("eligibility", "api_key"),
        ("quality", "token"),
        ("provenance", "arbitrary"),
        ("provenance", "access_token"),
    ],
)
def test_direct_repository_rejects_nested_unbounded_fields(
    db, test_organization, test_user, namespace, forbidden_key
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    candidate = _payload().model_dump(mode="json")
    target = candidate["provenance"][0] if namespace == "provenance" else candidate[namespace]
    target[forbidden_key] = "must-not-persist"
    with pytest.raises(ValueError):
        repo.update_identity_metadata(row.id, test_organization.id, candidate)
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == {}


_CREDENTIAL_LIKE_PROFILE_IDS = [
    # Synthetic examples only; do not store or log live provider credentials.
    "xoxb-111111111111-222222222222-AbCdEf123",
    "xoxp-111111111111-222222222222-AbCdEf123",
    "xoxc-fake-slack-auth-material",
    "sk-fakeOpenAIKey123",
    "sk-proj-fakeProjectKey123",
    "sk_live_fakeStripeKey123",
    "ghp_FakeGithubToken123",
    "gho_FakeGithubOAuth123",
    "github_pat_FakeFineGrained123",
    "glpat-FakeGitLabAuth123",
    "AKIAIOSFODNN7EXAMPLE",
    "ASIAIOSFODNN7EXAMPLE",
    "AIzaSyFakeFakeFakeFakeFakeFakeFakeFake",
    "BearerFakeAuthorization123",
    "eyJabc.eyJdef.signature",
    "my-api-key-123",
    "my_apikey_123",
    "my-access-key-123",
    "my_private_key_123",
    "whsec_FakeWebhookSecret123",
    "shpat_FakeShopifyToken123",
    "shpss_FakeShopifySession123",
    "shppa_FakeShopifyPrivateApp123",
    "shpua_FakeShopifyUserAuth123",
    "ya29.fakeGoogleOAuthToken123",
]


@pytest.mark.parametrize(
    "profile_id",
    _CREDENTIAL_LIKE_PROFILE_IDS + [
        "access_token:123", "https://provider.example/id", "a" * 129, "profile id",
    ],
)
def test_provider_profile_reference_must_be_non_secret_id(profile_id):
    candidate = _payload().model_dump(mode="json")
    candidate["provider_profile_ref"]["profile_id"] = profile_id
    with pytest.raises(ValueError):
        FileAttachmentIdentityMetadataUpdate.model_validate(candidate)


@pytest.mark.parametrize("profile_id", _CREDENTIAL_LIKE_PROFILE_IDS)
def test_repository_rejects_credential_value_without_write(
    db, test_organization, test_user, profile_id
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    candidate = _payload().model_dump(mode="json")
    candidate["provider_profile_ref"]["profile_id"] = profile_id
    with pytest.raises(ValueError):
        repo.update_identity_metadata(row.id, test_organization.id, candidate)
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == {}


def test_rejected_credential_value_does_not_replace_existing_metadata(
    db, test_organization, test_user
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    before = repo.update_identity_metadata(
        row.id, test_organization.id, _payload().model_dump(mode="json")
    ).identity_metadata.copy()
    candidate = _payload().model_dump(mode="json")
    candidate["provider_profile_ref"]["profile_id"] = "sk-proj-anotherFakeCredential123"
    with pytest.raises(ValueError):
        repo.update_identity_metadata(row.id, test_organization.id, candidate)
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == before


@pytest.mark.parametrize("shopify_namespace", ["shpat", "shpss", "shppa", "shpua"])
@pytest.mark.parametrize("suffix", ["SyntheticOpaque123", "a1B2c3", "Some-V1"])
@pytest.mark.parametrize("has_approved_existing", [False, True])
def test_shopify_credential_namespace_rejects_without_commit_or_metadata_mutation(
    db, test_organization, test_user, monkeypatch,
    shopify_namespace, suffix, has_approved_existing,
):
    # Namespace-level adversarial coverage; no real credentials in fixtures.
    from copy import deepcopy

    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    if has_approved_existing:
        repo.update_identity_metadata(
            row.id, test_organization.id, _payload().model_dump(mode="json")
        )
    db.expire_all()
    before = deepcopy(repo.get_attachment(row.id).identity_metadata)
    profile_id = f"{shopify_namespace}_{suffix}"
    candidate = _payload().model_dump(mode="json")
    candidate["provider_profile_ref"]["profile_id"] = profile_id

    # API/schema failure precedes persistence, including an already approved row.
    with pytest.raises(ValueError):
        FileAttachmentIdentityMetadataUpdate.model_validate(candidate)

    def forbidden_commit():
        pytest.fail("invalid credential-like provider profile must never commit")

    monkeypatch.setattr(db, "commit", forbidden_commit)
    with pytest.raises(ValueError):
        repo.update_identity_metadata(row.id, test_organization.id, candidate)
    assert not db.is_modified(repo.get_attachment(row.id), include_collections=True)
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == before


@pytest.mark.parametrize(
    ("provider", "profile_id"),
    [
        ("elevenlabs", "EXAVITQu4vr4xnSDxMaL"),  # opaque voice ID form
        ("heygen", "2c6ae90b-0c73-4f2c-9bc0-9dbd8fa2b771"),
        ("heygen", "avatar-profile-1"),
        ("liveavatar", "avatar_27d8230a-3c44-45fe-ab91-1183d116db41"),
        ("liveavatar", "LiveAvatar.profile-123"),
    ],
)
def test_nonsecret_mature_provider_profile_refs_survive_repository_roundtrip(
    db, test_organization, test_user, provider, profile_id
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    candidate = _payload().model_dump(mode="json")
    candidate["provider_profile_ref"] = {"provider": provider, "profile_id": profile_id}
    validated = FileAttachmentIdentityMetadataUpdate.model_validate(candidate)
    assert validated.provider_profile_ref.profile_id == profile_id
    updated = repo.update_identity_metadata(row.id, test_organization.id, candidate)
    assert updated.identity_metadata["provider_profile_ref"] == candidate["provider_profile_ref"]
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == updated.identity_metadata


def test_direct_repository_persists_only_valid_bounded_json(
    db, test_organization, test_user
):
    from app.schemas.file_attachment_identity import FileAttachmentIdentityMetadataStored

    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    clean = _payload().model_dump(mode="json")
    updated = repo.update_identity_metadata(row.id, test_organization.id, clean)
    expected = FileAttachmentIdentityMetadataStored.model_validate(
        dict(clean, revoked=False, revoked_at=None, revocation_reason=None)
    ).model_dump(mode="json")
    assert updated.identity_metadata == expected
    assert set(updated.identity_metadata["provider_profile_ref"]) == {"provider", "profile_id"}
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == expected


def test_direct_repository_revoke_fails_closed_on_unbounded_existing_metadata(
    db, test_organization, test_user
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    invalid = _payload().model_dump(mode="json")
    invalid["access_token"] = "injected-legacy-secret"
    # Simulate a pre-existing corrupt row; revocation must not propagate it.
    row.identity_metadata = invalid
    db.commit()
    with pytest.raises(ValueError):
        repo.revoke_identity_metadata(row.id, test_organization.id, "user request")
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == invalid
    # Deletion remains possible even when legacy metadata is malformed.
    assert repo.delete_identity_attachment_for_organization(
        row.id, test_organization.id
    ) is True
    assert repo.get_attachment(row.id) is None


def test_direct_repository_revoke_remains_terminal(db, test_organization, test_user):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    repo.update_identity_metadata(
        row.id, test_organization.id, _payload().model_dump(mode="json")
    )
    revoked = repo.revoke_identity_metadata(row.id, test_organization.id, "withdrawn")
    assert revoked.identity_metadata["revoked"] is True
    assert revoked.identity_metadata["active"] is False
    assert not any(revoked.identity_metadata["eligibility"].values())
    with pytest.raises(ValueError, match="terminal"):
        repo.revoke_identity_metadata(row.id, test_organization.id, "again")
    with pytest.raises(ValueError, match="terminal"):
        repo.update_identity_metadata(
            row.id, test_organization.id, _payload().model_dump(mode="json")
        )


@pytest.mark.parametrize("invalid_grant", ["approval", "consent"])
def test_direct_repository_enforces_approval_and_consent(
    db, test_organization, test_user, invalid_grant
):
    repo = FileAttachmentRepository(db)
    row = _make_attachment(repo, test_organization.id, test_user.id)
    candidate = _payload().model_dump(mode="json")
    if invalid_grant == "approval":
        candidate["explicit_approval"] = False
    else:
        candidate["consent"]["granted"] = False
    with pytest.raises(ValueError):
        repo.update_identity_metadata(row.id, test_organization.id, candidate)
    db.expire_all()
    assert repo.get_attachment(row.id).identity_metadata == {}
