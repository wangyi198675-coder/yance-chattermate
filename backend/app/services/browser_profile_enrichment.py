"""Thin deterministic bridge from browser-visible profile facts to Customer.

No browser state, queue, retry, contact store, or profile database is owned
here. Existing ChatterMate canonical owners remain the only binding authority.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.chat_history import ChatHistory
from app.models.channels import ChannelAccount, ChannelConversation, ChannelType
from app.models.customer import Customer
from app.services.browser_profile_enrichment_schema import (
    CANONICAL_PROVIDER_MESSAGE,
    DIRECT_PROVIDER_USER,
    PROVENANCE,
    validate_browser_profile_payload,
)


class BrowserProfileBindingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _one(rows, code: str, label: str):
    if len(rows) != 1:
        raise BrowserProfileBindingError(code, f"{label} resolved to {len(rows)} rows")
    return rows[0]


def _browser_owned(value) -> bool:
    return isinstance(value, dict) and value.get("provenance") == PROVENANCE


def _source_metadata(payload: dict, observed_at: str, provider_user_id: str) -> dict:
    if payload["binding_mode"] == CANONICAL_PROVIDER_MESSAGE:
        identity_ref = f'|mid={payload["provider_message_ids"][0]}'
    else:
        identity_ref = f'|user={provider_user_id}'
    return {
        "source_channel": ChannelType.MESSENGER.value,
        "provider_user_id": provider_user_id,
        "binding_mode": payload["binding_mode"],
        "observed_at": observed_at,
        "source_ref": (
            f'{payload["origin"]}|page={payload["page_account_id"]}{identity_ref}'
        ),
        "provenance": PROVENANCE,
    }


def _resolve_direct_conversation(db: Session, account, payload: dict):
    conflicts = (
        db.query(ChannelConversation)
        .filter(
            ChannelConversation.channel_account_id == account.id,
            ChannelConversation.channel_type == ChannelType.MESSENGER.value,
            or_(
                ChannelConversation.external_conversation_id == payload["thread_id"],
                ChannelConversation.external_user_id == payload["provider_user_id"],
            ),
        )
        .all()
    )
    exact = [
        row
        for row in conflicts
        if row.channel_account_id == account.id
        and row.channel_type == ChannelType.MESSENGER.value
        and row.external_conversation_id == payload["thread_id"]
        and row.external_user_id == payload["provider_user_id"]
    ]
    relevant_conflicts = [
        row
        for row in conflicts
        if row.channel_account_id == account.id
        and row.channel_type == ChannelType.MESSENGER.value
        and (
            row.external_conversation_id == payload["thread_id"]
            or row.external_user_id == payload["provider_user_id"]
        )
    ]
    if len(relevant_conflicts) != len(exact):
        raise BrowserProfileBindingError(
            "CONFLICTING_PROVIDER_IDENTITY",
            "thread/provider identity conflicts with another canonical conversation",
        )
    return _one(
        exact,
        "CONVERSATION_IDENTITY_NOT_UNIQUE",
        "Messenger ChannelConversation",
    )


def _resolve_message_conversation(db: Session, account, payload: dict):
    requested = payload["provider_message_ids"]
    rows = (
        db.query(ChatHistory)
        .filter(
            ChatHistory.provider_channel == ChannelType.MESSENGER.value,
            ChatHistory.external_message_id.in_(requested),
        )
        .all()
    )

    page_rows = []
    for message_id in requested:
        all_mid_rows = [
            row
            for row in rows
            if row.provider_channel == ChannelType.MESSENGER.value
            and row.external_message_id == message_id
        ]
        exact_page = [
            row for row in all_mid_rows
            if row.external_account_id == payload["page_account_id"]
        ]
        if not exact_page:
            if all_mid_rows:
                raise BrowserProfileBindingError(
                    "CONFLICTING_PROVIDER_IDENTITY",
                    "provider message exists only under another Messenger Page account",
                )
            raise BrowserProfileBindingError(
                "CONVERSATION_IDENTITY_NOT_UNIQUE",
                "provider message id does not resolve to canonical ChatHistory",
            )
        if len(exact_page) != 1:
            raise BrowserProfileBindingError(
                "CONFLICTING_PROVIDER_IDENTITY",
                "provider message id resolves to multiple canonical ChatHistory rows",
            )
        page_rows.append(exact_page[0])

    session_ids = {row.session_id for row in page_rows if row.session_id is not None}
    if len(session_ids) != 1 or any(row.session_id is None for row in page_rows):
        raise BrowserProfileBindingError(
            "CONFLICTING_PROVIDER_IDENTITY",
            "provider message ids do not converge to exactly one session",
        )
    customer_ids = {row.customer_id for row in page_rows if row.customer_id is not None}
    if len(customer_ids) != 1 or any(row.customer_id is None for row in page_rows):
        raise BrowserProfileBindingError(
            "MISSING_CUSTOMER",
            "provider message ids do not converge to exactly one customer",
        )
    organization_ids = {
        row.organization_id for row in page_rows if row.organization_id is not None
    }
    if len(organization_ids) != 1 or any(
        row.organization_id is None for row in page_rows
    ):
        raise BrowserProfileBindingError(
            "CROSS_ACCOUNT_ORGANIZATION",
            "provider message ids do not converge to one organization",
        )
    if next(iter(organization_ids)) != account.organization_id:
        raise BrowserProfileBindingError(
            "CROSS_ACCOUNT_ORGANIZATION",
            "provider message/account organization mismatch",
        )

    session_id = next(iter(session_ids))
    canonical_customer_id = next(iter(customer_ids))
    candidates = (
        db.query(ChannelConversation)
        .filter(
            ChannelConversation.channel_account_id == account.id,
            ChannelConversation.channel_type == ChannelType.MESSENGER.value,
            ChannelConversation.session_id == session_id,
        )
        .all()
    )
    exact = [
        row
        for row in candidates
        if row.channel_account_id == account.id
        and row.channel_type == ChannelType.MESSENGER.value
        and row.session_id == session_id
    ]
    conversation = _one(
        exact,
        "CONVERSATION_IDENTITY_NOT_UNIQUE",
        "Messenger ChannelConversation",
    )
    if conversation.customer_id != canonical_customer_id:
        raise BrowserProfileBindingError(
            "CONFLICTING_PROVIDER_IDENTITY",
            "ChatHistory customer does not match ChannelConversation customer",
        )
    if conversation.organization_id != account.organization_id:
        raise BrowserProfileBindingError(
            "CROSS_ACCOUNT_ORGANIZATION",
            "conversation/account organization mismatch",
        )
    if not conversation.external_user_id:
        raise BrowserProfileBindingError(
            "CONFLICTING_PROVIDER_IDENTITY",
            "canonical conversation has no provider user identity",
        )
    return conversation


def apply_browser_profile_enrichment(db: Session, raw_payload: dict) -> dict:
    payload = validate_browser_profile_payload(raw_payload)

    accounts = (
        db.query(ChannelAccount)
        .filter(
            ChannelAccount.channel_type == ChannelType.MESSENGER.value,
            ChannelAccount.external_account_id == payload["page_account_id"],
            ChannelAccount.is_active.is_(True),
        )
        .all()
    )
    exact_accounts = [
        row
        for row in accounts
        if row.channel_type == ChannelType.MESSENGER.value
        and row.external_account_id == payload["page_account_id"]
        and row.is_active is True
    ]
    account = _one(
        exact_accounts,
        "ACCOUNT_IDENTITY_NOT_UNIQUE",
        "Messenger ChannelAccount",
    )

    if payload["binding_mode"] == DIRECT_PROVIDER_USER:
        conversation = _resolve_direct_conversation(db, account, payload)
    elif payload["binding_mode"] == CANONICAL_PROVIDER_MESSAGE:
        conversation = _resolve_message_conversation(db, account, payload)
    else:  # validated schema makes this unreachable; fail closed defensively.
        raise BrowserProfileBindingError(
            "CONFLICTING_PROVIDER_IDENTITY", "unsupported binding mode"
        )

    if conversation.customer_id is None:
        raise BrowserProfileBindingError(
            "MISSING_CUSTOMER", "conversation has no canonical customer"
        )
    if conversation.channel_account_id != account.id:
        raise BrowserProfileBindingError(
            "CONFLICTING_PROVIDER_IDENTITY",
            "conversation does not belong to the exact Page ChannelAccount",
        )
    if conversation.organization_id != account.organization_id:
        raise BrowserProfileBindingError(
            "CROSS_ACCOUNT_ORGANIZATION",
            "conversation/account organization mismatch",
        )

    customers = db.query(Customer).filter(Customer.id == conversation.customer_id).all()
    exact_customers = [row for row in customers if row.id == conversation.customer_id]
    customer = _one(
        exact_customers,
        "CUSTOMER_IDENTITY_NOT_UNIQUE",
        "Customer",
    )
    if customer.organization_id != account.organization_id:
        raise BrowserProfileBindingError(
            "CROSS_CUSTOMER_ORGANIZATION",
            "customer/account organization mismatch",
        )
    if customer.merged_into_customer_id is not None:
        raise BrowserProfileBindingError(
            "MERGED_CUSTOMER_REJECTED", "conversation targets a merged customer"
        )

    meta = dict(customer.meta_data or {})
    existing_profile = meta.get("person_profile")
    if existing_profile is None:
        profile = {}
    elif isinstance(existing_profile, dict):
        profile = dict(existing_profile)
    else:
        raise BrowserProfileBindingError(
            "INVALID_PERSON_PROFILE", "person_profile is not an object"
        )

    observed_at = datetime.now(timezone.utc).isoformat()
    provider_user_id = str(conversation.external_user_id)
    source = _source_metadata(payload, observed_at, provider_user_id)
    wrote_name = False
    wrote_avatar = False

    if payload["display_name"] is not None:
        current_name = profile.get("display_name")
        if current_name is None or _browser_owned(current_name):
            profile["display_name"] = {
                "value": payload["display_name"],
                **source,
            }
            wrote_name = True

    if payload["avatar_url"] is not None:
        current_avatar = profile.get("avatar")
        if current_avatar is None or _browser_owned(current_avatar):
            profile["avatar"] = {
                "url": payload["avatar_url"],
                **source,
            }
            wrote_avatar = True

    if not wrote_name and not wrote_avatar:
        return {
            "ok": True,
            "written": False,
            "customer_id": str(customer.id),
            "reason": "HIGHER_PRIORITY_PROFILE_PRESENT",
        }

    meta["person_profile"] = profile
    customer.meta_data = meta
    try:
        db.commit()
        db.refresh(customer)
    except Exception:
        db.rollback()
        raise

    return {
        "ok": True,
        "written": True,
        "customer_id": str(customer.id),
        "display_name_written": wrote_name,
        "avatar_written": wrote_avatar,
        "provenance": PROVENANCE,
        "binding_mode": payload["binding_mode"],
    }
