from __future__ import annotations

import sys
import types
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if "app" not in sys.modules:
    _app = types.ModuleType("app")
    _app.__path__ = [str(_BACKEND / "app")]
    sys.modules["app"] = _app
if "app.models" not in sys.modules:
    _models = types.ModuleType("app.models")
    _models.__path__ = [str(_BACKEND / "app" / "models")]
    sys.modules["app.models"] = _models

import uuid
from types import SimpleNamespace

import pytest

from app.models.chat_history import ChatHistory
from app.models.channels import ChannelAccount, ChannelConversation
from app.models.customer import Customer
from app.services.browser_profile_enrichment import (
    BrowserProfileBindingError,
    apply_browser_profile_enrichment,
)
from app.services.browser_profile_enrichment_schema import (
    CANONICAL_PROVIDER_MESSAGE,
    DIRECT_PROVIDER_USER,
)


ORG = uuid.uuid4()
ACCOUNT_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
CONVERSATION_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()
PAGE = "1203748086150141"
PSID = "61594960173176"
MID1 = "mid.$cAA.live-1"
MID2 = "mid.$cAA.live-2"


class FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)


class FakeDB:
    def __init__(self, *, accounts, conversations, customers, messages):
        self.rows = {
            ChannelAccount: accounts,
            ChannelConversation: conversations,
            Customer: customers,
            ChatHistory: messages,
        }
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []

    def query(self, model):
        return FakeQuery(self.rows.get(model, []))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, row):
        self.refreshed.append(row)


def account(*, ident=ACCOUNT_ID, org=ORG, page=PAGE, active=True):
    return SimpleNamespace(
        id=ident,
        organization_id=org,
        channel_type="messenger",
        external_account_id=page,
        is_active=active,
    )


def conversation(
    *,
    ident=CONVERSATION_ID,
    account_id=ACCOUNT_ID,
    org=ORG,
    customer_id=CUSTOMER_ID,
    thread=PSID,
    user=PSID,
    session=SESSION_ID,
):
    return SimpleNamespace(
        id=ident,
        channel_account_id=account_id,
        channel_type="messenger",
        external_conversation_id=thread,
        external_user_id=user,
        session_id=session,
        organization_id=org,
        customer_id=customer_id,
    )


def customer(*, ident=CUSTOMER_ID, org=ORG, meta=None, merged=None):
    return SimpleNamespace(
        id=ident,
        organization_id=org,
        meta_data={} if meta is None else meta,
        merged_into_customer_id=merged,
    )


def message(
    *,
    mid=MID1,
    page=PAGE,
    session=SESSION_ID,
    customer_id=CUSTOMER_ID,
    org=ORG,
    channel="messenger",
):
    return SimpleNamespace(
        provider_channel=channel,
        external_account_id=page,
        external_message_id=mid,
        session_id=session,
        customer_id=customer_id,
        organization_id=org,
    )


def direct_payload(**updates):
    value = {
        "schema_version": 1,
        "binding_mode": DIRECT_PROVIDER_USER,
        "page_account_id": PAGE,
        "thread_id": PSID,
        "provider_user_id": PSID,
        "display_name": "Visible Person",
        "avatar_url": "https://scontent.example.net/avatar.jpg",
        "origin": "https://www.facebook.com",
        "page_kind": "facebook_messages",
    }
    value.update(updates)
    return value


def message_payload(ids=None, **updates):
    value = {
        "schema_version": 1,
        "binding_mode": CANONICAL_PROVIDER_MESSAGE,
        "page_account_id": PAGE,
        "provider_message_ids": ids or [MID1],
        "display_name": "Yeonhee Kim",
        "avatar_url": "https://scontent.example.net/avatar.jpg",
        "origin": "https://www.facebook.com",
        "page_kind": "facebook_messages",
    }
    value.update(updates)
    return value


def db_for(*, accounts=None, conversations=None, customers=None, messages=None):
    return FakeDB(
        accounts=[account()] if accounts is None else accounts,
        conversations=[conversation()] if conversations is None else conversations,
        customers=[customer()] if customers is None else customers,
        messages=[] if messages is None else messages,
    )


def assert_reject(code, db, value):
    with pytest.raises(BrowserProfileBindingError) as exc:
        apply_browser_profile_enrichment(db, value)
    assert exc.value.code == code
    assert db.commits == 0


def test_direct_provider_user_regression_writes_only_customer_person_profile():
    target = customer(meta={"unrelated": {"keep": True}})
    db = db_for(customers=[target])
    result = apply_browser_profile_enrichment(db, direct_payload())

    assert result["ok"] is True
    assert result["written"] is True
    assert result["binding_mode"] == DIRECT_PROVIDER_USER
    assert result["customer_id"] == str(CUSTOMER_ID)
    assert db.commits == 1
    assert target.meta_data["unrelated"] == {"keep": True}
    profile = target.meta_data["person_profile"]
    assert profile["display_name"]["value"] == "Visible Person"
    assert profile["avatar"]["provenance"] == "browser_assisted_user_visible"
    assert profile["avatar"]["provider_user_id"] == PSID


def test_page_plus_one_canonical_mid_resolves_exact_conversation_customer_and_writes():
    target = customer()
    db = db_for(customers=[target], messages=[message()])
    result = apply_browser_profile_enrichment(db, message_payload())

    assert result["written"] is True
    assert result["binding_mode"] == CANONICAL_PROVIDER_MESSAGE
    profile = target.meta_data["person_profile"]
    assert profile["display_name"]["value"] == "Yeonhee Kim"
    assert profile["display_name"]["provider_user_id"] == PSID
    assert profile["display_name"]["binding_mode"] == CANONICAL_PROVIDER_MESSAGE
    assert profile["display_name"]["source_ref"].endswith("|mid=" + MID1)


def test_multiple_mids_same_conversation_pass():
    target = customer()
    db = db_for(
        customers=[target],
        messages=[message(mid=MID1), message(mid=MID2)],
    )
    result = apply_browser_profile_enrichment(db, message_payload([MID1, MID2]))
    assert result["written"] is True
    assert db.commits == 1


def test_mids_resolving_to_two_sessions_fail_closed():
    other_session = uuid.uuid4()
    db = db_for(messages=[
        message(mid=MID1),
        message(mid=MID2, session=other_session),
    ])
    assert_reject(
        "CONFLICTING_PROVIDER_IDENTITY",
        db,
        message_payload([MID1, MID2]),
    )


def test_mid_belonging_only_to_another_page_fails_closed():
    db = db_for(messages=[message(page="999")])
    assert_reject("CONFLICTING_PROVIDER_IDENTITY", db, message_payload())


def test_unknown_mid_fails_closed():
    db = db_for(messages=[])
    assert_reject("CONVERSATION_IDENTITY_NOT_UNIQUE", db, message_payload())


def test_page_account_missing_fails_closed():
    db = db_for(accounts=[], messages=[message()])
    assert_reject("ACCOUNT_IDENTITY_NOT_UNIQUE", db, message_payload())


def test_duplicate_page_account_fails_closed():
    db = db_for(accounts=[account(), account(ident=uuid.uuid4())], messages=[message()])
    assert_reject("ACCOUNT_IDENTITY_NOT_UNIQUE", db, message_payload())


def test_chat_history_customer_mismatch_fails_closed():
    other_customer = uuid.uuid4()
    db = db_for(messages=[message(customer_id=other_customer)])
    assert_reject("CONFLICTING_PROVIDER_IDENTITY", db, message_payload())


def test_chat_history_organization_mismatch_fails_closed():
    db = db_for(messages=[message(org=uuid.uuid4())])
    assert_reject("CROSS_ACCOUNT_ORGANIZATION", db, message_payload())


def test_conversation_for_same_session_but_other_page_account_does_not_bind():
    db = db_for(
        conversations=[conversation(account_id=uuid.uuid4())],
        messages=[message()],
    )
    assert_reject("CONVERSATION_IDENTITY_NOT_UNIQUE", db, message_payload())


def test_missing_customer_fails_closed_no_write():
    db = db_for(customers=[], messages=[message()])
    assert_reject("CUSTOMER_IDENTITY_NOT_UNIQUE", db, message_payload())


def test_wrong_customer_organization_fails_closed_no_write():
    db = db_for(
        customers=[customer(org=uuid.uuid4())],
        messages=[message()],
    )
    assert_reject("CROSS_CUSTOMER_ORGANIZATION", db, message_payload())


def test_merged_customer_is_not_a_valid_write_target():
    db = db_for(
        customers=[customer(merged=uuid.uuid4())],
        messages=[message()],
    )
    assert_reject("MERGED_CUSTOMER_REJECTED", db, message_payload())


def test_provider_official_avatar_remains_higher_priority():
    target = customer(meta={
        "person_profile": {
            "avatar": {
                "url": "https://graph.example/provider.jpg",
                "provenance": "provider_official",
            }
        }
    })
    db = db_for(customers=[target], messages=[message()])
    result = apply_browser_profile_enrichment(
        db, message_payload(display_name=None, avatar_url="https://browser.example/a.jpg")
    )
    assert result["written"] is False
    assert db.commits == 0
    assert target.meta_data["person_profile"]["avatar"]["url"] == "https://graph.example/provider.jpg"


def test_browser_owned_fields_can_refresh_using_same_customer_persistence():
    target = customer()
    first_db = db_for(customers=[target], messages=[message()])
    first = apply_browser_profile_enrichment(first_db, message_payload())
    assert first["written"] is True

    second_db = db_for(customers=[target], messages=[message()])
    second = apply_browser_profile_enrichment(
        second_db,
        message_payload(
            display_name="Updated Visible Person",
            avatar_url="https://scontent.example.net/avatar2.jpg",
        ),
    )
    assert second["written"] is True
    assert list(target.meta_data).count("person_profile") == 1
    profile = target.meta_data["person_profile"]
    assert profile["display_name"]["value"] == "Updated Visible Person"
    assert profile["avatar"]["url"].endswith("avatar2.jpg")


def test_non_object_person_profile_fails_closed():
    db = db_for(
        customers=[customer(meta={"person_profile": "not-an-object"})],
        messages=[message()],
    )
    assert_reject("INVALID_PERSON_PROFILE", db, message_payload())


def test_direct_conflicting_provider_identity_still_fails_closed():
    db = db_for(conversations=[conversation(thread=PSID, user="999")])
    assert_reject("CONFLICTING_PROVIDER_IDENTITY", db, direct_payload())


def test_direct_ambiguous_conversation_still_fails_closed():
    db = db_for(conversations=[conversation(), conversation(ident=uuid.uuid4())])
    assert_reject("CONVERSATION_IDENTITY_NOT_UNIQUE", db, direct_payload())
