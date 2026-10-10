"""Regression for Meta webhook application-principal HMAC scope (W344)."""

import hashlib
import hmac

import pytest

from app.channels.meta_base import authenticated_meta_app_ids
from app.core.config import settings


def signed(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def distinct_apps(monkeypatch):
    monkeypatch.setattr(settings, "META_APP_ID", "FICTIONAL_META_APP_A")
    monkeypatch.setattr(settings, "META_APP_SECRET", "FICTIONAL_META_SECRET_A")
    monkeypatch.setattr(settings, "INSTAGRAM_APP_ID", "FICTIONAL_IG_APP_B")
    monkeypatch.setattr(settings, "INSTAGRAM_APP_SECRET", "FICTIONAL_IG_SECRET_B")


def test_distinct_secrets_identify_only_the_matching_app(distinct_apps):
    body = b'{"object":"page"}'
    assert authenticated_meta_app_ids(body, signed(body, "FICTIONAL_META_SECRET_A")) == frozenset(
        {"FICTIONAL_META_APP_A"})
    assert authenticated_meta_app_ids(body, signed(body, "FICTIONAL_IG_SECRET_B")) == frozenset(
        {"FICTIONAL_IG_APP_B"})


def test_unsigned_tampered_and_unconfigured_fail_closed(distinct_apps, monkeypatch):
    body = b'{"object":"instagram"}'
    assert not authenticated_meta_app_ids(body, "")
    assert not authenticated_meta_app_ids(body, signed(body + b"x", "FICTIONAL_IG_SECRET_B"))
    assert not authenticated_meta_app_ids(body, "sha256=not-a-hex-hmac")
    monkeypatch.setattr(settings, "INSTAGRAM_APP_ID", "")
    assert not authenticated_meta_app_ids(body, signed(body, "FICTIONAL_IG_SECRET_B"))


def test_same_registered_app_may_share_one_key(distinct_apps, monkeypatch):
    body = b'{"object":"instagram"}'
    monkeypatch.setattr(settings, "INSTAGRAM_APP_ID", settings.META_APP_ID)
    monkeypatch.setattr(settings, "INSTAGRAM_APP_SECRET", settings.META_APP_SECRET)
    assert authenticated_meta_app_ids(body, signed(body, settings.META_APP_SECRET)) == frozenset(
        {settings.META_APP_ID})


def test_distinct_app_ids_with_indistinguishable_secrets_fail_closed(distinct_apps, monkeypatch):
    body = b'{"object":"page"}'
    monkeypatch.setattr(settings, "INSTAGRAM_APP_SECRET", settings.META_APP_SECRET)
    assert not authenticated_meta_app_ids(body, signed(body, settings.META_APP_SECRET))


def test_same_app_id_allows_verified_alternate_configured_key(distinct_apps, monkeypatch):
    body = b'{"object":"instagram"}'
    monkeypatch.setattr(settings, "INSTAGRAM_APP_ID", settings.META_APP_ID)
    assert authenticated_meta_app_ids(body, signed(body, settings.INSTAGRAM_APP_SECRET)) == frozenset(
        {settings.META_APP_ID})

@pytest.mark.asyncio
async def test_native_adapters_respect_their_product_app_principal(distinct_apps):
    from app.channels import get_adapter

    body = b'{"object":"page"}'
    meta_header = {"x-hub-signature-256": signed(body, settings.META_APP_SECRET)}
    ig_header = {"x-hub-signature-256": signed(body, settings.INSTAGRAM_APP_SECRET)}
    assert await get_adapter("messenger").verify_webhook(meta_header, body, None)
    assert not await get_adapter("messenger").verify_webhook(ig_header, body, None)
    assert await get_adapter("whatsapp").verify_webhook(meta_header, body, None)
    assert not await get_adapter("whatsapp").verify_webhook(ig_header, body, None)
    assert await get_adapter("instagram").verify_webhook(ig_header, body, None)
    assert not await get_adapter("instagram").verify_webhook(meta_header, body, None)
