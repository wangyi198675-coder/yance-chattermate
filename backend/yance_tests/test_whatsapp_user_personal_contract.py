"""Security-negative and canonical-owner contract tests; no live account actions."""
import asyncio
from pathlib import Path
import sys
import types
import pytest

APP = Path(__file__).resolve().parents[1] / "app"
for name, path in {
    "app": APP,
    "app.channels": APP / "channels",
    "app.channels.personal_social": APP / "channels" / "personal_social",
}.items():
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod

from app.channels.personal_social.whatsapp_user import WhatsAppUserTransport
from app.channels.personal_social.base import PersonalSocialTransportAdapter, TransportSessionStatus


def test_personal_whatsapp_is_narrow_and_never_overrides_cloud():
    assert issubclass(WhatsAppUserTransport, PersonalSocialTransportAdapter)
    assert not hasattr(WhatsAppUserTransport, "persist_message")
    assert not hasattr(WhatsAppUserTransport, "save_customer")
    assert not hasattr(WhatsAppUserTransport, "deliver_retry")
    assert not hasattr(WhatsAppUserTransport, "register_adapter")


@pytest.mark.parametrize("invalid", ["", "../x", "a/b", "a\\b", "a.b", "a" * 129])
def test_account_rejects_path_traversal_and_cross_tenant_alias(invalid, tmp_path):
    with pytest.raises(ValueError, match="INVALID_ACCOUNT_ID"):
        WhatsAppUserTransport(invalid, private_root=tmp_path)


def test_construct_does_not_spawn_connect_scan_or_create_session(tmp_path):
    a = WhatsAppUserTransport("account_one", private_root=tmp_path)
    b = WhatsAppUserTransport("account_two", private_root=tmp_path)
    assert a.account_id != b.account_id
    assert a._proc is None and b._proc is None
    assert not list(tmp_path.iterdir())
    assert asyncio.run(a.session_status()) is TransportSessionStatus.DISCONNECTED
    assert asyncio.run(a.health()).metadata["verified"] is False
    with pytest.raises(RuntimeError, match="NOT_VERIFIED"):
        asyncio.run(a.account_identity())


def test_canonical_jid_requires_explicit_remote_identity(tmp_path):
    a = WhatsAppUserTransport("account", private_root=tmp_path)
    for unsafe in ["", "https://example.com", "@s.whatsapp.net", "evil@g.us", "../../a",
                   "123456789@c.us"]:
        with pytest.raises(ValueError, match="INVALID_CANONICAL_JID"):
            asyncio.run(a.route({"external_conversation_id": unsafe}))
    assert asyncio.run(a.route({"external_conversation_id": "123456789@s.whatsapp.net"})) == {
        "provider_channel": "whatsapp-personal",
        "external_account_id": "account",
        "external_conversation_id": "123456789@s.whatsapp.net",
    }


def test_backfill_fails_closed_until_canonical_bridge(tmp_path):
    a = WhatsAppUserTransport("account", private_root=tmp_path)

    async def run():
        async for _ in a.backfill():
            raise AssertionError("must not silently mark provider history imported")
    with pytest.raises(NotImplementedError, match="CANONICAL_BACKFILL"):
        asyncio.run(run())


def test_receive_inbound_is_not_fake_prepopulated(tmp_path):
    a = WhatsAppUserTransport("account", private_root=tmp_path)
    assert a._inbound.empty()
    assert a._events.empty()
    assert a._user is None


@pytest.mark.asyncio
async def test_real_windows_private_node_pipe_boot_without_scan_or_login(tmp_path):
    """This executes the actual installed pinned Node driver, without calling connect."""
    a = WhatsAppUserTransport("account_one", private_root=tmp_path)
    b = WhatsAppUserTransport("account_two", private_root=tmp_path)
    try:
        assert (await a._call("status"))["status"] == "disconnected"
        assert (await b._call("status"))["status"] == "disconnected"
        assert (await a.health()).metadata["verified"] is False
        assert (await b.health()).metadata["verified"] is False
        with pytest.raises(RuntimeError, match="PERSONAL_WHATSAPP_NOT_CONNECTED"):
            await a.send_outbound({"kind":"text", "to":"123456789@s.whatsapp.net",
                                   "text":"offline test not sent",
                                   "idempotencyKey":"canonical-offline-1"})
        # Exclusive Signal session lease blocks two local processes for one account.
        second = WhatsAppUserTransport("account_one", private_root=tmp_path)
        try:
            with pytest.raises(RuntimeError, match="AUTH_ACCOUNT_ALREADY_OWNED"):
                await second._call("status")
        finally:
            await second.close()
    finally:
        await a.close()
        await b.close()
