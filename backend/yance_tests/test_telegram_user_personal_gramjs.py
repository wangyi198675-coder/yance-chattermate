"""W397 isolated Windows/contract regression; NO live personal account access."""
import asyncio
import base64
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

root = Path(__file__).resolve().parents[1] / "app"
for name, folder in {
    "app": root, "app.channels": root / "channels",
    "app.channels.personal_social": root / "channels" / "personal_social",
}.items():
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(folder)]
        sys.modules[name] = module
mod = importlib.import_module("app.channels.personal_social.telegram_user.adapter")
TelegramUserAdapter = mod.TelegramUserAdapter
TelegramPersonalError = mod.TelegramPersonalError
TransportSessionStatus = mod.TransportSessionStatus
APP_HASH = "a" * 32


class FakeCustody:
    def __init__(self, session=""):
        self.sessions = {}
        self.initial = session
        self.saved = []
    async def load_session(self, organization_id, account_id):
        return self.sessions.get((organization_id, account_id), self.initial)
    async def save_session(self, organization_id, account_id, session):
        self.saved.append((organization_id, account_id))
        self.sessions[(organization_id, account_id)] = session
    async def clear_session(self, organization_id, account_id):
        self.sessions.pop((organization_id, account_id), None)


class FakeGramJS:
    def __init__(self, auto_auth=True):
        self.calls = []
        self.events_queue = asyncio.Queue()
        self.auto_auth = auto_auth
        self.started = False
        self.closed = False
        self.raise_send = False
    async def start(self):
        self.started = True
    async def call(self, method, params):
        self.calls.append((method, dict(params)))
        if method == "connect":
            if self.auto_auth:
                await self.events_queue.put({"event":"authenticated","session":"test-session",
                                              "user":{"id":"100","name":"Tester"}})
            return {"authorized":self.auto_auth}
        if method == "status":
            return {"connected":self.auto_auth,"authorized":self.auto_auth}
        if method == "send_text" or method == "send_media":
            if self.raise_send:
                raise TelegramPersonalError("WORKER_TERMINATED_UNCERTAIN")
            return {"id":"567"}
        if method == "backfill":
            return {"messages":[{"external_message_id":"500:300","remote_message_id":"300",
                                 "text":"old","external_conversation_id":params["peer"]}]}
        if method == "dialogs":
            return {"dialogs":[{"external_conversation_id":"500","title":"Example",
                                "unread_count":2,"conversation_kind":"private"}]}
        if method == "download_media":
            return {"base64":base64.b64encode(b"media").decode()}
        if method == "disconnect":
            return {"disconnected":True}
        return {"started":True}
    async def events(self):
        while True:
            event = await self.events_queue.get()
            yield event
            if event.get("event") == "disconnected":
                return
    async def close(self):
        self.closed = True
        await self.events_queue.put({"event":"disconnected"})


def make(*, scope="org-a", account="tg-a", custody=None, worker=None):
    custody = custody or FakeCustody()
    worker = worker or FakeGramJS()
    adapter = TelegramUserAdapter(organization_id=scope, channel_account_id=account,
                                  api_id=1234, api_hash=APP_HASH, custody=custody,
                                  worker_factory=lambda: worker)
    return adapter, custody, worker


@pytest.mark.asyncio
async def test_inherits_canonical_interface_and_verifies_real_user_identity_before_connected():
    adapter, custody, worker = make()
    assert isinstance(adapter, mod.PersonalSocialTransportAdapter)
    assert await adapter.session_status() == TransportSessionStatus.DISCONNECTED
    await adapter.connect()
    await asyncio.sleep(0.01)
    assert await adapter.session_status() == TransportSessionStatus.CONNECTED
    assert (await adapter.account_identity()).account_id == "100"
    assert custody.saved == [("org-a", "tg-a")]
    assert worker.calls[0][0] == "connect"
    await adapter.disconnect()
    assert worker.closed


@pytest.mark.asyncio
async def test_inbound_retains_native_scope_and_remote_identity():
    adapter, custody, worker = make()
    await adapter.connect()
    await worker.events_queue.put({"event":"message","message":{
        "external_conversation_id":"500","external_message_id":"9",
        "text":"hello", "has_media":True, "media_ref":"500:9",
        "organization_id":"malicious", "channel_account_id":"other",
    }})
    async def take():
        async for item in adapter.receive_inbound():
            return item
    event = await asyncio.wait_for(take(), 1)
    assert event["organization_id"] == "org-a"
    assert event["channel_account_id"] == "tg-a"
    assert event["external_message_id"] == "9"
    assert event["media_ref"] == "500:9"
    assert event["is_customer_turn"] is True
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_native_scope_fails_closed_and_bot_names_cannot_be_personal_targets():
    adapter, _, worker = make()
    await adapter.connect()
    await asyncio.sleep(.01)
    with pytest.raises(TelegramPersonalError, match="ACCOUNT_SCOPE_MISMATCH"):
        await adapter.send_outbound({
            "organization_id":"org-b", "channel_account_id":"tg-a",
            "external_conversation_id":"500", "text":"no",
        })
    with pytest.raises(TelegramPersonalError, match="PERSONAL_TARGET_REQUIRED"):
        await adapter.route({
            "organization_id":"org-a", "channel_account_id":"tg-a",
            "external_conversation_id":"bot:777000",
        })
    assert not any(method.startswith("send_") for method, _ in worker.calls)
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_send_acks_only_remote_acceptance_uncertain_send_never_retried():
    adapter, _, worker = make()
    await adapter.connect()
    await asyncio.sleep(.01)
    payload = {"organization_id":"org-a", "channel_account_id":"tg-a",
               "external_conversation_id":"500", "text":"hello",
               "client_send_intent_id":"intent-1"}
    receipt = await adapter.send_outbound(payload)
    assert receipt.provider_message_id == "500:567"
    assert receipt.status == "accepted"
    assert receipt.message_id == "intent-1"
    assert (await adapter.receipt("500:567")).status == "unknown"
    worker.raise_send = True
    with pytest.raises(TelegramPersonalError, match="WORKER_TERMINATED_UNCERTAIN"):
        await adapter.send_outbound(payload)
    assert (await adapter.health()).status == TransportSessionStatus.DEGRADED
    assert len([x for x in worker.calls if x[0] == "send_text"]) == 2
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_qr_phone_code_password_logout_are_user_authorization_gated():
    adapter, custody, worker = make(worker=FakeGramJS(auto_auth=False))
    with pytest.raises(TelegramPersonalError, match="INTERACTIVE_AUTHORIZATION_REQUIRED"):
        await adapter.begin_qr_login()
    await adapter.begin_qr_login(interactive_authorized=True)
    assert worker.calls[-1][0] == "start_qr"
    await adapter.begin_phone_login("+491234567890", interactive_authorized=True)
    assert worker.calls[-1][0] == "start_phone"
    with pytest.raises(TelegramPersonalError, match="INTERACTIVE_CODE_REQUIRED"):
        await adapter.submit_code("12345")
    await adapter.submit_code("12345", interactive_authorized=True)
    await adapter.submit_password("test-2fa", interactive_authorized=True)
    assert worker.calls[-1][0] == "submit_password"
    with pytest.raises(TelegramPersonalError, match="INTERACTIVE_AUTHORIZATION_REQUIRED"):
        await adapter.logout()
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_media_and_backfill_do_not_create_second_history_or_asset_owner():
    adapter, _, worker = make()
    await adapter.connect()
    await asyncio.sleep(.01)
    payload = {"organization_id":"org-a", "channel_account_id":"tg-a",
               "external_conversation_id":"500", "media_bytes":b"data",
               "filename":"proof.bin"}
    receipt = await adapter.send_outbound(payload)
    assert receipt.status == "accepted"
    assert worker.calls[-1][0] == "send_media"
    assert base64.b64decode(worker.calls[-1][1]["media_base64"]) == b"data"
    assert await adapter.media("500:300") == b"media"
    cursor = json.dumps({"organization_id":"org-a", "channel_account_id":"tg-a",
                         "external_conversation_id":"500", "offset_id":320})
    values = [event async for event in adapter.backfill(cursor)]
    assert values[0]["external_message_id"] == "500:300"
    assert json.loads(values[0]["next_cursor"])["offset_id"] == 300
    assert values[0]["organization_id"] == "org-a"
    assert worker.calls[-1] == ("backfill", {"peer":"500","offset_id":320,"limit":100})
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_two_account_sessions_are_isolated_across_restart():
    vault = FakeCustody()
    a, _, wa = make(scope="org-1", account="A", custody=vault)
    b, _, wb = make(scope="org-1", account="B", custody=vault)
    await a.connect(); await b.connect()
    await asyncio.sleep(.01)
    assert len(vault.sessions) == 2
    assert ("org-1", "A") in vault.sessions and ("org-1", "B") in vault.sessions
    assert wa is not wb
    await a.disconnect(); await b.disconnect()
    restarted, _, wr = make(scope="org-1", account="A", custody=vault)
    await restarted.connect()
    assert wr.calls[0][1]["session"] == "test-session"
    await restarted.disconnect()


@pytest.mark.parametrize("api_id,hash_value", [(0,APP_HASH),(1,""),(1,"abc"),(True,APP_HASH)])
def test_invalid_api_config_fails_closed(api_id, hash_value):
    with pytest.raises(TelegramPersonalError, match="TELEGRAM_APP_CREDENTIALS_REQUIRED"):
        TelegramUserAdapter(organization_id="o", channel_account_id="a",
            api_id=api_id, api_hash=hash_value, custody=FakeCustody(),
            worker_factory=FakeGramJS)


def test_runtime_must_be_private_and_explicit():
    with pytest.raises(TelegramPersonalError, match="PRIVATE_NODE_RUNTIME_MISSING"):
        TelegramUserAdapter(organization_id="o", channel_account_id="a",
            api_id=123, api_hash=APP_HASH, custody=FakeCustody())


@pytest.mark.asyncio
async def test_windows_real_private_node_gramjs_worker_rejects_unconfigured_credentials():
    """Actual subprocess + GramJS dependency, no Telegram network or login."""
    import os
    exe = os.environ.get("YANCE_W397_PRIVATE_NODE")
    if not exe or not Path(exe).is_file():
        pytest.skip("Private Windows Node executable not provisioned")
    worker = mod.GramJSWorker(exe)
    await worker.start()
    try:
        with pytest.raises(TelegramPersonalError, match="INVALID_API_CREDENTIALS"):
            await worker.call("connect", {"api_id":0,"api_hash":"bad","session":""})
        result = await worker.call("disconnect", {})
        assert result["disconnected"]
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_dialog_discovery_and_highwater_are_transport_only():
    adapter, _, _ = make()
    await adapter.connect()
    result = await adapter.discover_dialogs(limit=25)
    assert result == [{
        "external_conversation_id":"500", "title":"Example",
        "unread_count":2, "conversation_kind":"private",
        "organization_id":"org-a", "channel_account_id":"tg-a",
        "provider":"telegram", "account_kind":"personal",
    }]
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_incorrect_persisted_personal_account_identity_fails_closed():
    vault = FakeCustody()
    adapter = TelegramUserAdapter(organization_id="org-a", channel_account_id="tg-a",
         api_id=1234, api_hash=APP_HASH, custody=vault,
         expected_user_id="999", worker_factory=FakeGramJS)
    await adapter.connect()
    await asyncio.sleep(.03)
    assert (await adapter.health()).status == TransportSessionStatus.ERROR
    assert vault.saved == []
    with pytest.raises(TelegramPersonalError, match="IDENTITY_NOT_VERIFIED"):
        await adapter.account_identity()
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_real_qr_event_must_originate_in_worker_not_fabricated_locally():
    adapter, _, worker = make(worker=FakeGramJS(auto_auth=False))
    await adapter.begin_qr_login(interactive_authorized=True)
    assert await adapter.session_status() != TransportSessionStatus.CONNECTED
    await worker.events_queue.put({
        "event":"challenge","step":"qr","qr_uri":"tg://login?token=TEST_PROOF_ONLY"})
    challenge = await asyncio.wait_for(adapter.next_login_challenge(), 1)
    assert challenge == {"step":"qr","qr_uri":"tg://login?token=TEST_PROOF_ONLY","hint":None}
    assert await adapter.session_status() != TransportSessionStatus.CONNECTED
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_live_provider_health_downgrades_without_fabricating_connected():
    adapter, _, worker = make()
    await adapter.connect()
    await asyncio.sleep(.01)
    assert (await adapter.health()).status == TransportSessionStatus.CONNECTED
    worker.auto_auth = False
    assert await adapter.session_status() == TransportSessionStatus.DEGRADED
    assert (await adapter.error())["code"] == "PROVIDER_AUTHORIZATION_LOST"
    with pytest.raises(TelegramPersonalError, match="TELEGRAM_NOT_AUTHORIZED"):
        await adapter.send_outbound({
            "organization_id":"org-a", "channel_account_id":"tg-a",
            "external_conversation_id":"500", "text":"never send"})
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_failed_canonical_custody_blocks_connected_state():
    class RejectingCustody(FakeCustody):
        async def save_session(self, organization_id, account_id, session):
            raise PermissionError("vault-failed")
    vault = RejectingCustody()
    adapter, _, worker = make(custody=vault)
    await adapter.connect()
    await asyncio.sleep(.03)
    assert (await adapter.health()).status == TransportSessionStatus.ERROR
    assert worker.closed is True
    assert vault.sessions == {}
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_disconnected_session_identity_cannot_stay_authorized():
    adapter, _, worker = make()
    await adapter.connect()
    await asyncio.sleep(.01)
    await adapter.disconnect()
    with pytest.raises(TelegramPersonalError, match="IDENTITY_NOT_VERIFIED"):
        await adapter.account_identity()
    assert await adapter.session_status() == TransportSessionStatus.DISCONNECTED
    # Legacy V21 stale generation fence: late callback cannot be ingested.
    await worker.events_queue.put({"event":"message",
        "message":{"external_conversation_id":"500","external_message_id":"999"}})
    assert adapter._inbound.get_nowait() is mod._STOP
