"""Isolated LINE adapter smoke with local test doubles; not a live UAT."""
import asyncio, base64, hashlib, hmac, importlib.util, json, logging, sys, types
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as NS

root = Path(__file__).resolve().parents[1] / "app"

def module(name, **props):
    m = types.ModuleType(name)
    m.__dict__.update(props)
    sys.modules[name] = m
    return m

module("app", __path__=[str(root)])
module("app.channels", __path__=[str(root / "channels")])
module("app.core", __path__=[str(root / "core")])
module("app.models", __path__=[str(root / "models")])

@dataclass
class InboundMessage:
    external_account_id: str
    external_conversation_id: str
    external_user_id: str
    external_message_id: str
    text: str
    timestamp: object = None

@dataclass
class SendResult:
    ok: bool
    error: str = ""

module("app.channels.base", ChannelAdapter=type("ChannelAdapter", (), {}), InboundMessage=InboundMessage, SendResult=SendResult)
module("app.channels.registry", register_adapter=lambda x: None)
module("app.core.security", decrypt_api_key=lambda x: x)
module("app.core.logger", get_logger=logging.getLogger)
module("app.models.channels",
       ChannelAccount=type("ChannelAccount", (), {}),
       ChannelConversation=type("ChannelConversation", (), {}),
       ChannelType=NS(LINE=NS(value="line")))

spec = importlib.util.spec_from_file_location("app.channels.line", root / "channels" / "line.py")
line = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = line
spec.loader.exec_module(line)

def account(id, token, secret):
    return NS(id=id, encrypted_credentials=json.dumps({
        "channel_access_token": token, "channel_secret": secret}))

class Provider:
    def __init__(self):
        self.sends = []
        self.endpoint_sets = []
    async def post(self, url, headers=None, json=None):
        self.sends.append((url, headers["Authorization"], json))
        return NS(status_code=200)
    async def put(self, url, headers=None, json=None):
        self.endpoint_sets.append((url, headers["Authorization"], json))
        return NS(status_code=200)
    async def get(self, url, headers=None):
        return NS(status_code=200, json=lambda: {"userId": "UbotA"})

async def smoke():
    a, b = account("A", "tokenA", "secretA"), account("B", "tokenB", "secretB")
    payload = {"destination": "UbotA", "events": [{
        "type": "message", "source": {"userId": "Ucontact"},
        "message": {"type": "text", "id": "mA", "text": "hello"}
    }]}
    body = json.dumps(payload).encode()
    signature = lambda s: base64.b64encode(hmac.new(s.encode(), body, hashlib.sha256).digest()).decode()
    adapter = line.LineAdapter()
    assert await adapter.verify_webhook({"x-line-signature": signature("secretA")}, body, a)
    assert not await adapter.verify_webhook({"x-line-signature": signature("secretA")}, body, b)
    assert not await adapter.verify_webhook({"x-line-signature": "bad"}, body, a)
    assert adapter.parse_inbound(payload)[0].external_account_id == "UbotA"
    provider = Provider()
    line._get_http_client = lambda: provider
    assert (await adapter.send_text(a, NS(external_conversation_id="UcustomerA"), "hello A")).ok
    assert (await adapter.send_text(b, NS(external_conversation_id="UcustomerB"), "hello B")).ok
    assert provider.sends[0][1] == "Bearer tokenA"
    assert provider.sends[1][1] == "Bearer tokenB"
    assert provider.sends[0][2]["to"] == "UcustomerA"
    assert provider.sends[1][2]["to"] == "UcustomerB"
    assert await line.set_webhook_endpoint("tokenA", "https://sample.invalid/a")
    assert await line.set_webhook_endpoint("tokenB", "https://sample.invalid/b")
    assert provider.endpoint_sets[0][1] == "Bearer tokenA"
    assert provider.endpoint_sets[1][1] == "Bearer tokenB"
    assert await line.get_bot_info("tokenA") == {"userId": "UbotA"}
    print("PASS isolated LINE adapter HMAC, route parse, per-account outbound, endpoint, bot info (MOCKS ONLY)")

if __name__ == "__main__":
    asyncio.run(smoke())
