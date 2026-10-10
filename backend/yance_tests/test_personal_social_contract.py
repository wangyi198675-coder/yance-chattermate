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
import inspect


def test_personal_social_transport_contract_has_transport_operations_only():
    module = importlib.import_module("app.channels.personal_social.base")
    cls = module.PersonalSocialTransportAdapter
    required = {
        "connect", "disconnect", "reconnect", "session_status", "receive_inbound",
        "send_outbound", "receipt", "media", "backfill", "account_identity",
        "route", "error", "health",
    }
    assert required.issubset(set(cls.__abstractmethods__))
    forbidden = {"save_person", "save_relationship", "save_persona", "save_memory", "decide_reply"}
    assert forbidden.isdisjoint(set(dir(cls)))
    assert inspect.isabstract(cls)


def test_personal_social_contract_exposes_neutral_status_and_receipt_types():
    module = importlib.import_module("app.channels.personal_social.base")
    assert {x.value for x in module.TransportSessionStatus} >= {
        "disconnected", "connecting", "connected", "degraded", "error"
    }
    receipt = module.TransportReceipt(message_id="m1", status="accepted")
    assert receipt.message_id == "m1"
    assert receipt.status == "accepted"

