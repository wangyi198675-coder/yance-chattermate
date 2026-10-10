"""W319-F01: real signed JWT + real canonical Widget/Customer SQL owner.

No mocked authenticate_socket_conversation_token or token decoder. Only the
unrelated Redis storage transport and app database session factory are
redirected to the ephemeral fixture.
"""
import uuid
from contextlib import nullcontext

import pytest

from app.core import auth_utils, security
from app.models.customer import Customer
from app.models.organization import Organization


@pytest.fixture
def widget_auth(db, test_widget, test_customer, monkeypatch):
    monkeypatch.setattr(auth_utils, "SessionLocal", lambda: nullcontext(db))
    # JWT is still signed/validated with production jose/security. No live Redis.
    monkeypatch.setattr(security, "_store_token_in_redis", lambda *a, **kw: None)
    monkeypatch.setattr(security, "_is_token_in_redis", lambda *a, **kw: True)

    async def call(customer_id, *, widget_id=None, tamper=False):
        token = security.create_conversation_token(
            widget_id or test_widget.id, str(customer_id)
        )
        if tamper:
            token = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
        return await auth_utils.authenticate_socket_conversation_token(
            "w319-signed-production", {"conversation_token": token},
        )
    return call, test_widget, test_customer


@pytest.mark.asyncio
async def test_w319_valid_signed_token_and_stable_repeat(widget_auth):
    call, widget, customer = widget_auth
    first = await call(customer.id)
    second = await call(customer.id)
    assert first[:3] == (widget.id, widget.organization_id, str(customer.id))
    assert second[:3] == first[:3]
    assert first[3] != second[3]  # separately signed JTI credentials


@pytest.mark.asyncio
async def test_w319_foreign_tenant_and_missing_customer_rejected(db, widget_auth):
    call, widget, customer = widget_auth
    foreign_org = Organization(name="W319 Foreign Org", domain=f"foreign-{uuid.uuid4().hex}.invalid", timezone="UTC")
    db.add(foreign_org)
    db.commit()
    foreign = Customer(email=f"w319-{uuid.uuid4().hex}@example.invalid",
                       organization_id=foreign_org.id)
    db.add(foreign)
    db.commit()
    assert await call(foreign.id) == (None, None, None, None)
    assert await call(uuid.uuid4()) == (None, None, None, None)
    assert await call(customer.id, widget_id=str(uuid.uuid4())) == (None, None, None, None)


@pytest.mark.asyncio
async def test_w319_all_same_tenant_merge_hops_are_valid(db, widget_auth):
    call, widget, origin = widget_auth
    middle = Customer(email=f"mid-{uuid.uuid4().hex}@example.invalid", organization_id=widget.organization_id)
    survivor = Customer(email=f"final-{uuid.uuid4().hex}@example.invalid", organization_id=widget.organization_id)
    db.add_all([middle, survivor])
    db.commit()
    origin.merged_into_customer_id = middle.id
    middle.merged_into_customer_id = survivor.id
    db.commit()
    accepted = await call(origin.id)
    assert accepted[:3] == (widget.id, widget.organization_id, str(survivor.id))


@pytest.mark.asyncio
async def test_w319_merge_foreign_target_and_cycles_fail_closed(db, widget_auth):
    call, widget, origin = widget_auth
    foreign_org = Organization(name="W319 Forbidden Merge",domain=f"x-{uuid.uuid4().hex}.invalid",timezone="UTC")
    db.add(foreign_org); db.commit()
    foreign = Customer(email=f"foreign-{uuid.uuid4().hex}@example.invalid",
                       organization_id=foreign_org.id)
    middle = Customer(email=f"local-{uuid.uuid4().hex}@example.invalid",
                      organization_id=widget.organization_id)
    db.add_all([foreign,middle]); db.commit()
    origin.merged_into_customer_id = middle.id
    middle.merged_into_customer_id = foreign.id
    db.commit()
    assert await call(origin.id) == (None,None,None,None)
    middle.merged_into_customer_id = origin.id
    db.commit()
    assert await call(origin.id) == (None,None,None,None)
    middle.merged_into_customer_id = None
    db.commit()
    assert (await call(origin.id))[2] == str(middle.id)


@pytest.mark.asyncio
async def test_w319_missing_tampered_and_invalid_claims_fail_closed(widget_auth):
    call, widget, customer = widget_auth
    assert await call(customer.id, tamper=True) == (None,None,None,None)
    assert await auth_utils.authenticate_socket_conversation_token("missing", {}) == (None,None,None,None)
    assert await call("not-a-uuid") == (None,None,None,None)
