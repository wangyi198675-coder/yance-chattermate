"""W444 offline negative regression for the existing official DeepL owner.

No external calls, real credentials, second translation registry or paid host.
"""
from types import SimpleNamespace

import pytest

from app.services import translation
from app.services.translation import DeepLTranslationOwner, TranslationProviderError


class FakeClient:
    def __init__(self, payload=None, status=200, *, fail_if_called=False):
        self.payload = payload
        self.status = status
        self.calls = []
        self.fail_if_called = fail_if_called

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, url, *, headers):
        if self.fail_if_called:
            raise AssertionError("UNAUTHORIZED_PROVIDER_NETWORK_CALL")
        assert url == "https://api-free.deepl.com/v2/usage"
        assert "Authorization" in headers
        self.calls.append(url)
        return SimpleNamespace(status_code=self.status, json=lambda: self.payload)

    async def post(self, *args, **kwargs):
        raise AssertionError("UNAUTHORIZED_PAID_OR_TEST_TRANSLATION_CALL")


def _mock_client(monkeypatch, payload=None, status=200):
    client = FakeClient(payload, status)
    monkeypatch.setattr(translation.httpx, "AsyncClient", lambda **_: client)
    return client


@pytest.mark.asyncio
async def test_absent_free_credential_is_not_configured_no_network(monkeypatch):
    owner = DeepLTranslationOwner(api_key="")
    _mock_client(monkeypatch)
    assert (await owner.health())["state"] == "not_configured"
    assert owner.base_url == "https://api-free.deepl.com"
    with pytest.raises(TranslationProviderError, match="translation_owner_not_configured"):
        await owner.translate("Hallo", target_language="ZH-HANS")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["paidkey", "invalid", "paid-but-not-free:abc"])
async def test_nonfree_key_never_calls_paid_or_free_endpoint(monkeypatch, bad):
    owner = DeepLTranslationOwner(api_key=bad)
    assert owner.base_url == "https://api-free.deepl.com"
    client = _mock_client(monkeypatch)
    result = await owner.health()
    assert result["state"] == "needs_attention"
    assert result["errorCode"] == "FREE_PLAN_KEY_REQUIRED"
    assert not client.calls
    with pytest.raises(TranslationProviderError, match="translation_free_plan_key_required"):
        await owner.translate("Hallo", target_language="ZH-HANS")
    assert not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("used,limit", [(0,500000), (42,500000), (499999,500000)])
async def test_free_quota_with_remaining_capacity_is_connected(monkeypatch, used, limit):
    client = _mock_client(monkeypatch, {"character_count": used, "character_limit": limit})
    owner = DeepLTranslationOwner(api_key="test-key:fx")
    result = await owner.health()
    assert result["state"] == "connected"
    assert client.calls == ["https://api-free.deepl.com/v2/usage"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"character_count": 500000, "character_limit": 500000},
    {"character_count": 500001, "character_limit": 500000},
    {"character_count": -1, "character_limit": 500000},
    {"character_count": 0, "character_limit": 0},
    {"character_count": "50", "character_limit": 500000},
    {"character_count": 1, "character_limit": None},
    {"character_count": True, "character_limit": 500000},
    {}, None, [],
])
async def test_exhausted_or_ambiguous_quota_fails_closed(monkeypatch, payload):
    _mock_client(monkeypatch, payload)
    result = await DeepLTranslationOwner(api_key="test:fx").health()
    assert result["state"] == "needs_attention"
    assert result["errorCode"] == "FREE_QUOTA_EXHAUSTED_OR_UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 403, 429, 456, 500])
async def test_provider_rejection_never_reports_connected(monkeypatch, status):
    _mock_client(monkeypatch, None, status)
    result = await DeepLTranslationOwner(api_key="test:fx").health()
    assert result["state"] == "needs_attention"
    assert result["errorCode"] == f"PROVIDER_HTTP_{status}"
