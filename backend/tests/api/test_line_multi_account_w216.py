"""Window216: deterministic LINE multi-channel account isolation regression.

Provider API calls and signed payloads here are MOCKED. These tests do not
constitute a real dual-LINE-channel live UAT.
"""
import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.main  # noqa: F401
from app.core.application import app
from app.core.auth import get_current_organization, get_current_user
from app.database import get_db
from app.repositories.channels import ChannelAccountRepository
from app.channels.line import LineAdapter


BASE = "/api/v1/channels"


@pytest.fixture
def client(db, test_user, test_organization):
    async def user():
        return test_user

    async def org():
        return test_organization

    def database():
        yield db

    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_current_organization] = org
    app.dependency_overrides[get_db] = database
    yield TestClient(app)
    app.dependency_overrides.clear()


async def bot_info(token):
    return {
        "token-a": {"userId": "UbotA", "displayName": "LINE A"},
        "token-a-new": {"userId": "UbotA", "displayName": "LINE A"},
        "token-b": {"userId": "UbotB", "displayName": "LINE B"},
        "token-b-new": {"userId": "UbotB", "displayName": "LINE B"},
    }.get(token)


def connect(client, token, secret):
    return client.post(f"{BASE}/line", json={
        "channel_access_token": token, "channel_secret": secret})


def sign(body, secret):
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()


def message(bot, message_id="same-provider-id", text="hello"):
    return {"destination": bot, "events": [{
        "type": "message",
        "source": {"type": "user", "userId": "Ucustomer"},
        "message": {"type": "text", "id": message_id, "text": text},
    }]}


def signed_post(client, account_id, payload, secret):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return client.post(
        f"/api/v1/webhooks/line/{account_id}", content=raw,
        headers={"x-line-signature": sign(raw, secret),
                 "content-type": "application/json"})


def test_connect_two_channels_settings_and_restart_identity(client, db):
    with patch("app.api.channels.line.line_api.get_bot_info", side_effect=bot_info), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=True) as set_hook:
        a = connect(client, "token-a", "secret-a")
        b = connect(client, "token-b", "secret-b")
    assert a.status_code == b.status_code == 200
    aid, bid = a.json()["id"], b.json()["id"]
    assert aid != bid
    assert a.json()["external_account_id"] == "UbotA"
    assert b.json()["external_account_id"] == "UbotB"
    assert a.json()["webhook_url"].endswith(f"/webhooks/line/{aid}")
    assert b.json()["webhook_url"].endswith(f"/webhooks/line/{bid}")
    assert {call.args[0] for call in set_hook.await_args_list} == {"token-a", "token-b"}

    repo = ChannelAccountRepository(db)
    account_a = repo.get_by_id(aid)
    account_b = repo.get_by_id(bid)
    assert "token-a" not in account_a.encrypted_credentials
    assert "token-b" not in account_b.encrypted_credentials
    assert repo.get_credentials(account_a) == {
        "channel_access_token": "token-a", "channel_secret": "secret-a"}
    assert repo.get_credentials(account_b) == {
        "channel_access_token": "token-b", "channel_secret": "secret-b"}

    db.expire_all()  # fresh DB reads: does NOT pretend to be a process restart
    listing = client.get(f"{BASE}/accounts")
    assert listing.status_code == 200
    data = {x["external_account_id"]: x for x in listing.json()}
    assert set(data) == {"UbotA", "UbotB"}
    assert data["UbotA"]["id"] == aid
    assert data["UbotB"]["id"] == bid
    assert data["UbotA"]["webhook_url"].endswith(f"/line/{aid}")
    assert data["UbotB"]["webhook_url"].endswith(f"/line/{bid}")


def test_webhook_signed_account_and_destination_isolation(client, db, test_organization):
    repo = ChannelAccountRepository(db)
    a = repo.create_account(test_organization.id, "line", "UbotA",
                            {"channel_secret": "secret-a", "channel_access_token": "token-a"})
    b = repo.create_account(test_organization.id, "line", "UbotB",
                            {"channel_secret": "secret-b", "channel_access_token": "token-b"})
    with patch("app.api.webhooks.line.process_channel_message",
               new_callable=AsyncMock) as process:
        ra = signed_post(client, a.id, message("UbotA", "same-id"), "secret-a")
        rb = signed_post(client, b.id, message("UbotB", "same-id"), "secret-b")
        assert ra.status_code == rb.status_code == 200
        assert process.await_count == 2
        assert process.await_args_list[0].args[0] == a.id
        assert process.await_args_list[1].args[0] == b.id
        assert process.await_args_list[0].args[1].external_account_id == "UbotA"
        assert process.await_args_list[1].args[1].external_account_id == "UbotB"

        assert signed_post(client, b.id, message("UbotA"), "secret-a").status_code == 403
        assert signed_post(client, b.id, message("UbotA"), "secret-b").status_code == 403
        repo.set_active(a, False)
        assert signed_post(client, a.id, message("UbotA"), "secret-a").status_code == 404
        assert process.await_count == 2


@pytest.mark.asyncio
async def test_outbound_uses_each_exact_account_token_and_recipient(db, test_organization):
    repo = ChannelAccountRepository(db)
    a = repo.create_account(test_organization.id, "line", "UbotA",
                            {"channel_secret": "secret-a", "channel_access_token": "token-a"})
    b = repo.create_account(test_organization.id, "line", "UbotB",
                            {"channel_secret": "secret-b", "channel_access_token": "token-b"})
    from app.models.channels import ChannelConversation
    convo_a = ChannelConversation(channel_account_id=a.id, external_conversation_id="UuserA")
    convo_b = ChannelConversation(channel_account_id=b.id, external_conversation_id="UuserB")
    reply = AsyncMock()
    reply.return_value.status_code = 200
    with patch("app.channels.line._get_http_client", return_value=type("Http", (), {"post": reply})()):
        adapter = LineAdapter()
        assert (await adapter.send_text(a, convo_a, "A")).ok
        assert (await adapter.send_text(b, convo_b, "B")).ok
    assert reply.await_count == 2
    assert reply.await_args_list[0].kwargs["headers"]["Authorization"] == "Bearer token-a"
    assert reply.await_args_list[1].kwargs["headers"]["Authorization"] == "Bearer token-b"
    assert reply.await_args_list[0].kwargs["json"]["to"] == "UuserA"
    assert reply.await_args_list[1].kwargs["json"]["to"] == "UuserB"


def test_rotate_only_a_and_remove_only_a(client, db):
    with patch("app.api.channels.line.line_api.get_bot_info", side_effect=bot_info), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=True):
        a = connect(client, "token-a", "secret-a").json()
        b = connect(client, "token-b", "secret-b").json()
        a2 = connect(client, "token-a-new", "secret-a-new").json()
    repo = ChannelAccountRepository(db)
    assert a2["id"] == a["id"]
    assert b["id"] != a["id"]
    assert repo.get_credentials(repo.get_by_id(b["id"]))["channel_access_token"] == "token-b"
    assert repo.get_credentials(repo.get_by_id(a["id"]))["channel_access_token"] == "token-a-new"
    assert client.delete(f"{BASE}/line/{a['id']}").status_code == 200
    assert repo.get_by_id(a["id"]) is None
    survivor = repo.get_by_id(b["id"])
    assert survivor is not None and survivor.is_active
    assert repo.get_credentials(survivor)["channel_secret"] == "secret-b"


def test_failure_does_not_mark_connected_or_damage_sibling(client, db):
    with patch("app.api.channels.line.line_api.get_bot_info", side_effect=bot_info), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=True):
        a = connect(client, "token-a", "secret-a").json()
        b = connect(client, "token-b", "secret-b").json()

    with patch("app.api.channels.line.line_api.get_bot_info", side_effect=bot_info), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=False):
        assert connect(client, "token-a-new", "secret-a-new").status_code == 502
        assert connect(client, "token-b-new", "secret-b-new").status_code == 502
    repo = ChannelAccountRepository(db)
    assert repo.get_credentials(repo.get_by_id(a["id"]))["channel_access_token"] == "token-a"
    assert repo.get_credentials(repo.get_by_id(b["id"]))["channel_access_token"] == "token-b"

    with patch("app.api.channels.line.line_api.get_bot_info", return_value={"userId": "UbotC"}), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=False):
        assert connect(client, "token-c", "secret-c").status_code == 502
    assert repo.get_by_external_id("line", "UbotC") is None

    with patch("app.api.channels.line.line_api.get_bot_info", return_value={}):
        assert connect(client, "token-unknown", "secret-unknown").status_code == 502


def test_line_same_user_id_different_bot_has_account_scoped_customer_identity(db):
    """LINE user ids are not a safe cross-channel customer merge authority."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.services.channel_chat import _get_or_create_customer
    inbound = SimpleNamespace(profile={}, external_user_id="Ushared")
    repository = MagicMock()
    repository.get_or_create_customer.return_value = SimpleNamespace(
        id=uuid4(), full_name="LINE user Ushared")
    account_a = SimpleNamespace(channel_type="line", external_account_id="UbotA")
    account_b = SimpleNamespace(channel_type="line", external_account_id="UbotB")
    with patch("app.services.channel_chat.CustomerRepository", return_value=repository):
        _get_or_create_customer(db, account_a, inbound, str(uuid4()))
        _get_or_create_customer(db, account_b, inbound, str(uuid4()))
    assert repository.get_or_create_customer.call_args_list[0].kwargs["email"] == (
        "ubota.ushared@line.channel")
    assert repository.get_or_create_customer.call_args_list[1].kwargs["email"] == (
        "ubotb.ushared@line.channel")


def test_w239_new_account_is_inactive_during_registration_and_active_after(client, db, test_organization):
    repo = ChannelAccountRepository(db)
    observed = []

    async def register(token, url):
        staged = repo.get_by_external_id("line", "UbotC")
        assert staged is not None
        assert staged.organization_id == test_organization.id
        assert staged.is_active is False
        assert url.endswith(f"/webhooks/line/{staged.id}")
        observed.append(staged.id)
        return True

    with patch("app.api.channels.line.line_api.get_bot_info",
               return_value={"userId": "UbotC", "displayName": "LINE C"}), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               side_effect=register):
        response = connect(client, "token-c", "secret-c")

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert str(observed[0]) == response.json()["id"]
    db.expire_all()
    assert repo.get_by_external_id("line", "UbotC").is_active is True


@pytest.mark.parametrize("cleanup_mode", ["returns_false", "raises"])
def test_w239_registration_false_cleanup_failure_keeps_row_inactive(
    client, db, test_organization, cleanup_mode,
):
    repo = ChannelAccountRepository(db)
    with patch("app.api.channels.line.line_api.get_bot_info", side_effect=bot_info), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=True):
        sibling = connect(client, "token-a", "secret-a").json()
    sibling_credentials = repo.get_by_id(sibling["id"]).encrypted_credentials

    cleanup = (
        {"return_value": False} if cleanup_mode == "returns_false"
        else {"side_effect": RuntimeError("synthetic cleanup failure")}
    )
    with patch("app.api.channels.line.line_api.get_bot_info",
               return_value={"userId": "UbotC", "displayName": "LINE C"}), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=False), \
         patch.object(ChannelAccountRepository, "delete", **cleanup) as delete:
        response = connect(client, "token-c", "secret-c")
        assert delete.call_count == 1

    assert response.status_code == 502
    db.expire_all()
    failed = repo.get_by_external_id("line", "UbotC")
    assert failed is not None and failed.is_active is False
    accounts = repo.list_by_org(test_organization.id, "line")
    assert sum(a.is_active for a in accounts if a.external_account_id == "UbotC") == 0
    survivor = repo.get_by_id(sibling["id"])
    assert survivor is not None and survivor.is_active
    assert survivor.encrypted_credentials == sibling_credentials
    listing = client.get(f"{BASE}/accounts")
    assert listing.status_code == 200
    assert any(a["id"] == str(failed.id) and a["is_active"] is False
               for a in listing.json())
    assert signed_post(client, failed.id, message("UbotC"), "secret-c").status_code == 404

    with patch("app.api.channels.line.line_api.get_bot_info",
               return_value={"userId": "UbotC", "displayName": "LINE C"}), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=True):
        recovered = connect(client, "token-c-new", "secret-c-new")
    assert recovered.status_code == 200
    assert recovered.json()["id"] == str(failed.id)
    assert repo.get_by_external_id("line", "UbotC").is_active


def test_w239_cleanup_database_commit_failure_leaves_no_active_row(client, db, test_organization):
    from sqlalchemy.exc import SQLAlchemyError
    repo = ChannelAccountRepository(db)

    with patch.object(db, "commit", wraps=db.commit) as commit:
        async def failed_registration(token, url):
            staged = repo.get_by_external_id("line", "UbotC")
            assert staged is not None and not staged.is_active
            # Only fail the DELETE commit, after the inactive stage committed.
            commit.side_effect = SQLAlchemyError("simulated cleanup database failure")
            return False

        with patch("app.api.channels.line.line_api.get_bot_info",
                   return_value={"userId": "UbotC"}), \
             patch("app.api.channels.line.line_api.set_webhook_endpoint",
                   side_effect=failed_registration):
            response = connect(client, "token-c", "secret-c")
    assert response.status_code == 502
    db.expire_all()
    staged = repo.get_by_external_id("line", "UbotC")
    assert staged is not None and staged.is_active is False
    assert not any(a.is_active for a in repo.list_by_org(test_organization.id, "line"))
    assert signed_post(client, staged.id, message("UbotC"), "secret-c").status_code == 404


def test_w239_registration_exception_preserves_inactive_staging(client, db):
    repo = ChannelAccountRepository(db)
    with patch("app.api.channels.line.line_api.get_bot_info",
               return_value={"userId": "UbotC"}), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, side_effect=RuntimeError("provider timeout")), \
         patch.object(ChannelAccountRepository, "delete", return_value=False):
        response = connect(client, "token-c", "secret-c")
    assert response.status_code == 502
    db.expire_all()
    assert repo.get_by_external_id("line", "UbotC").is_active is False


def test_w239_sibling_and_existing_credentials_unchanged_during_failed_rotation(client, db):
    with patch("app.api.channels.line.line_api.get_bot_info", side_effect=bot_info), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               new_callable=AsyncMock, return_value=True):
        a = connect(client, "token-a", "secret-a").json()
        b = connect(client, "token-b", "secret-b").json()

    repo = ChannelAccountRepository(db)
    original_a = repo.get_by_id(a["id"]).encrypted_credentials
    original_b = repo.get_by_id(b["id"]).encrypted_credentials

    async def reject_rotation(token, url):
        row_a, row_b = repo.get_by_id(a["id"]), repo.get_by_id(b["id"])
        assert token == "token-a-new"
        assert url.endswith(f"/line/{a['id']}")
        assert row_a.is_active and row_b.is_active
        assert row_a.encrypted_credentials == original_a
        assert row_b.encrypted_credentials == original_b
        return False

    with patch("app.api.channels.line.line_api.get_bot_info", side_effect=bot_info), \
         patch("app.api.channels.line.line_api.set_webhook_endpoint",
               side_effect=reject_rotation):
        response = connect(client, "token-a-new", "secret-a-new")
    assert response.status_code == 502
    db.expire_all()
    assert repo.get_by_id(a["id"]).is_active
    assert repo.get_by_id(b["id"]).is_active
    assert repo.get_by_id(a["id"]).encrypted_credentials == original_a
    assert repo.get_by_id(b["id"]).encrypted_credentials == original_b
    assert signed_post(client, b["id"], message("UbotA"), "secret-b").status_code == 403
