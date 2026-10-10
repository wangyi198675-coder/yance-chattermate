"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import re
import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.channels.constants import DEFAULT_TEMPLATE_LANGUAGE
from app.services.channel_chat import placeholder_name
from app.services.chat_notifications import notify_new_chat
from app.services.message_delivery import deliver_whatsapp_template
from app.channels.meta_base import fetch_message_templates
from app.core.logger import get_logger
from app.models.channels import ChannelAccount
from app.repositories.channels import (
    AgentChannelConfigRepository,
    ChannelAccountRepository,
    ChannelConversationRepository,
)
from app.repositories.customer import CustomerRepository
from app.repositories.session_to_agent import SessionToAgentRepository
from app.utils.phone import normalize_phone, to_wa_id

logger = get_logger(__name__)

# Business-initiated conversations are Utility/Authentication only. Marketing
# is deliberately unsupported outbound: it carries opt-in obligations and
# per-user caps (Graph error 131049) that a support product should not walk
# its customers into. The reopen flow (an existing conversation) is unaffected.
OUTBOUND_CATEGORIES = {"UTILITY", "AUTHENTICATION"}

_PLACEHOLDER = re.compile(r"\{\{(\d+)\}\}")


class OutboundError(Exception):
    """A refused or failed outbound send. Carries the HTTP status the API
    route should answer with, so the Phase-2 scheduler can reuse the service
    without importing anything web-shaped."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def render_template_body(template: dict, components: Optional[list]) -> str:
    """The message text as the customer will read it.

    Graph matches body parameters to {{n}} placeholders positionally in
    ascending order (the same rule the frontend's previewTemplate applies —
    keep the two honest with each other). Falls back to the raw body when a
    parameter is missing rather than failing the send: Meta is the authority
    on completeness and will reject a genuinely short send itself.
    """
    body = next((c.get("text", "") for c in template.get("components") or []
                 if str(c.get("type", "")).upper() == "BODY"), "")
    values = [
        str(parameter.get("text", ""))
        for component in components or []
        if str(component.get("type", "")).lower() == "body"
        for parameter in component.get("parameters") or []
    ]
    return _PLACEHOLDER.sub(
        lambda match: values[int(match.group(1)) - 1]
        if 0 < int(match.group(1)) <= len(values) else match.group(0),
        body,
    )


async def _approved_outbound_template(db: Session, account: ChannelAccount,
                                      name: str, language: str,
                                      *, starts_conversation: bool) -> dict:
    """The template this send is allowed to use, or the reason it isn't.

    `starts_conversation` decides whether the Utility/Authentication rule
    applies. It is a rule about business-INITIATED contact, so it belongs only
    to a send that opens a thread with someone who never wrote to us. Reaching
    an existing conversation is the reopen case: the customer did message us,
    which is why Meta accepts Marketing there — and why the inbox picker has
    never been category-gated.
    """
    credentials = ChannelAccountRepository(db).get_credentials(account)
    waba_id = credentials.get("waba_id")
    if not waba_id:
        raise OutboundError(400, "Reconnect this number with its WhatsApp "
                                 "Business Account ID to send templates")

    ok, data = await fetch_message_templates(waba_id, credentials["access_token"])
    if not ok:
        raise OutboundError(502, "Could not read the account's templates from Meta")

    template = next(
        (t for t in data if t.get("name") == name and t.get("language") == language),
        None,
    )
    if template is None:
        raise OutboundError(404, f"No template named {name} in {language} on this account")
    if str(template.get("status", "")).upper() != "APPROVED":
        raise OutboundError(400, f"Template {name} is not approved yet")
    if starts_conversation and \
            str(template.get("category", "")).upper() not in OUTBOUND_CATEGORIES:
        raise OutboundError(
            400,
            "Only Utility and Authentication templates can start a conversation. "
            "Marketing templates need the customer to have messaged you first.",
        )
    return template


def _placeholder_positions(text: str) -> list[int]:
    return sorted({int(match.group(1)) for match in _PLACEHOLDER.finditer(text or "")})


def _request_component(components: Optional[list], component_type: str) -> Optional[dict]:
    matches = [
        component for component in components or []
        if isinstance(component, dict)
        and str(component.get("type", "")).lower() == component_type.lower()
    ]
    if len(matches) > 1:
        raise OutboundError(400, f"Template contains more than one {component_type} parameter block")
    return matches[0] if matches else None


def _require_text_parameters(component: Optional[dict], expected: int, label: str) -> list[str]:
    parameters = (component or {}).get("parameters") or []
    if len(parameters) != expected:
        raise OutboundError(
            400, f"{label} requires exactly {expected} text parameter"
                 f"{'s' if expected != 1 else ''}",
        )
    values: list[str] = []
    for parameter in parameters:
        if not isinstance(parameter, dict) or str(parameter.get("type", "")).lower() != "text":
            raise OutboundError(400, f"{label} only supports text parameters")
        value = str(parameter.get("text") or "").strip()
        if not value:
            raise OutboundError(400, f"{label} text parameters cannot be blank")
        values.append(value)
    return values


def _validate_template_components(template: dict, components: Optional[list]) -> None:
    """Validate every non-media send-time parameter against Meta's inventory row."""
    supplied = components or []
    if not isinstance(supplied, list) or any(not isinstance(c, dict) for c in supplied):
        raise OutboundError(400, "Template components must be a list of parameter objects")

    allowed = {"header", "body", "button"}
    unknown = {
        str(component.get("type", "")).lower()
        for component in supplied
        if str(component.get("type", "")).lower() not in allowed
    }
    if unknown:
        raise OutboundError(400, f"Unsupported template component type: {sorted(unknown)[0]}")

    category = str(template.get("category", "")).upper()
    if category == "AUTHENTICATION":
        body = _request_component(supplied, "body")
        code = _require_text_parameters(body, 1, "Authentication template body")[0]
        buttons = [
            c for c in supplied
            if str(c.get("type", "")).lower() == "button"
        ]
        if len(buttons) != 1:
            raise OutboundError(400, "Authentication templates require one copy-code button parameter")
        button = buttons[0]
        if str(button.get("sub_type", "")).lower() != "url" or str(button.get("index")) != "0":
            raise OutboundError(400, "Authentication copy-code button must be url index 0")
        button_code = _require_text_parameters(button, 1, "Authentication copy-code button")[0]
        if button_code != code:
            raise OutboundError(400, "Authentication body and copy-code button must use the same code")
        if _request_component(supplied, "header") is not None:
            raise OutboundError(400, "Authentication templates do not accept header parameters")
        return

    inventory = template.get("components") or []
    header = next(
        (c for c in inventory if str(c.get("type", "")).upper() == "HEADER"), None)
    requested_header = _request_component(supplied, "header")
    if header:
        header_format = str(header.get("format", "TEXT")).upper()
        if header_format != "TEXT":
            # IMAGE/VIDEO/DOCUMENT send-time parameters belong to Window 36.
            raise OutboundError(
                400, "Media-header template parameters must use the canonical media path")
        header_vars = _placeholder_positions(str(header.get("text") or ""))
        if header_vars:
            _require_text_parameters(
                requested_header, len(header_vars), "Template header")
        elif requested_header is not None:
            raise OutboundError(400, "This template header has no send-time parameters")
    elif requested_header is not None:
        raise OutboundError(400, "This template has no header parameters")

    body = next(
        (c for c in inventory if str(c.get("type", "")).upper() == "BODY"), None)
    body_vars = _placeholder_positions(str((body or {}).get("text") or ""))
    requested_body = _request_component(supplied, "body")
    if body_vars:
        _require_text_parameters(requested_body, len(body_vars), "Template body")
    elif requested_body is not None:
        raise OutboundError(400, "This template body has no send-time parameters")

    buttons_component = next(
        (c for c in inventory if str(c.get("type", "")).upper() == "BUTTONS"), None)
    inventory_buttons = (buttons_component or {}).get("buttons") or []
    requested_buttons = [
        c for c in supplied if str(c.get("type", "")).lower() == "button"
    ]
    expected_button_keys: set[tuple[str, str]] = set()

    for index, button in enumerate(inventory_buttons):
        button_type = str(button.get("type", "")).upper()
        request_subtype = button_type.lower()
        expected_count = 0
        parameter_type = "text"
        if button_type == "URL":
            expected_count = len(_placeholder_positions(str(button.get("url") or "")))
            request_subtype = "url"
        elif button_type == "QUICK_REPLY":
            # Quick-reply payload is application-owned and must be explicit.
            expected_count = 1
            parameter_type = "payload"
            request_subtype = "quick_reply"
        else:
            # Fixed phone/call/etc. buttons need no send-time parameter.
            continue

        if expected_count == 0:
            continue
        key = (request_subtype, str(index))
        expected_button_keys.add(key)
        matches = [
            c for c in requested_buttons
            if str(c.get("sub_type", "")).lower() == request_subtype
            and str(c.get("index")) == str(index)
        ]
        if len(matches) != 1:
            raise OutboundError(
                400, f"Template button {index} requires one {request_subtype} parameter block")
        params = matches[0].get("parameters") or []
        if len(params) != expected_count:
            raise OutboundError(
                400, f"Template button {index} requires exactly {expected_count} parameter"
                     f"{'s' if expected_count != 1 else ''}")
        for parameter in params:
            if not isinstance(parameter, dict) or str(parameter.get("type", "")).lower() != parameter_type:
                raise OutboundError(
                    400, f"Template button {index} requires {parameter_type} parameters")
            value = parameter.get("text") if parameter_type == "text" else parameter.get("payload")
            if not str(value or "").strip():
                raise OutboundError(400, f"Template button {index} parameters cannot be blank")

    for button in requested_buttons:
        key = (str(button.get("sub_type", "")).lower(), str(button.get("index")))
        if key not in expected_button_keys:
            raise OutboundError(400, "Unexpected template button parameter block")


async def approved_template_for_send(
    db: Session,
    account: ChannelAccount,
    name: str,
    language: str,
    components: Optional[list],
    *,
    starts_conversation: bool,
) -> dict:
    """Meta inventory remains authoritative; this only validates send-time values."""
    template = await _approved_outbound_template(
        db, account, name, language, starts_conversation=starts_conversation)
    _validate_template_components(template, components)
    return template


def _resolve_customer(db: Session, account: ChannelAccount, phone: str,
                      customer_id: Optional[UUID], customer_name: Optional[str]):
    """The person this conversation belongs to.

    A picked person must actually OWN the number being messaged — the two
    arrive as independent fields, and binding a conversation to one person at
    another person's number is unrecoverable: the reply resolves by phone to
    somebody else, so history splits across two customers and the thread never
    appears on the profile of the person actually in it.

    set_phone_if_absent's skip-and-log is right for the automatic inbound
    paths, where there is nobody to tell. Here there is a human waiting on a
    response, so a conflict is refused instead of silently ignored.
    """
    repo = CustomerRepository(db)
    if customer_id is not None:
        customer = repo.get_by_id(customer_id)
        if customer is None or customer.organization_id != account.organization_id:
            raise OutboundError(404, "Customer not found")
        if customer.phone and customer.phone != phone:
            raise OutboundError(
                400,
                f"{customer.full_name or 'That person'} has a different number on "
                f"file. Send to their number, or update it on their profile first.",
            )
        owner = repo.get_customer_by_phone(phone, account.organization_id)
        if owner is not None and owner.id != customer.id:
            raise OutboundError(
                400,
                f"{phone} already belongs to {owner.full_name or 'another person'}. "
                f"Pick them instead, or clear the number from their profile.",
            )
        repo.set_phone_if_absent(customer, phone)
        return customer

    wa_id = to_wa_id(phone)
    customer = repo.get_or_create_customer(
        email=f"{wa_id}@whatsapp.channel",
        organization_id=account.organization_id,
        full_name=customer_name or placeholder_name(account.channel_type, wa_id),
        phone=phone,
    )
    # First-touch source for People's Source column; setdefault semantics so a
    # person who arrived some other way keeps their original story.
    if customer.lead_source is None:
        customer.lead_source = {"channel": "whatsapp", "via": "outbound"}
    return customer


async def start_outbound_conversation(
    db: Session,
    account: ChannelAccount,
    *,
    to: str,
    template_name: str,
    language: str = DEFAULT_TEMPLATE_LANGUAGE,
    components: Optional[list] = None,
    customer_id: Optional[UUID] = None,
    customer_name: Optional[str] = None,
) -> UUID:
    """Start (or rejoin) a WhatsApp conversation by phone number.

    Returns the session_id; everything downstream — the inbox thread, template
    resends, the AI answering the reply — already keys off a session, which is
    why this returns one instead of growing a parallel outbound code path.

    The conversation is created with last_inbound_at=None: no customer message
    means no 24-hour window, and pretending otherwise would let the AI send
    free-form text that Meta rejects.
    """
    phone = normalize_phone(to)
    if phone is None:
        raise OutboundError(400, "Enter the number in international format, e.g. +91 12345 67890")
    wa_id = to_wa_id(phone)

    agent_id = AgentChannelConfigRepository(db).get_active_agent_id(account.id)
    if agent_id is None:
        raise OutboundError(400, "Route an agent to this number first — "
                                 "otherwise nobody would answer the reply")

    # Resolved BEFORE the template is validated: whether this opens a thread or
    # rejoins one decides which rules the template must satisfy.
    conv_repo = ChannelConversationRepository(db)
    existing = conv_repo.get_active(account.id, wa_id)

    template = await approved_template_for_send(
        db, account, template_name, language, components,
        starts_conversation=existing is None)

    if existing is not None:
        # An open conversation already carries this number; send there instead
        # of splitting the thread. The window may even be open, but a template
        # send inside the window is legal and simpler than branching.
        conversation, session_id = existing, existing.session_id
        customer = None
        session_record = SessionToAgentRepository(db).get_session(session_id)
        if session_record is None:
            raise OutboundError(409, "Conversation session is missing; cannot send safely")
    else:
        customer = _resolve_customer(db, account, phone, customer_id, customer_name)
        session_id = uuid.uuid4()
        new_session = SessionToAgentRepository(db).create_session(
            session_id=session_id,
            agent_id=str(agent_id),
            customer_id=str(customer.id),
            organization_id=str(account.organization_id),
            channel=account.channel_type,
        )
        session_record = new_session
        await notify_new_chat(db, new_session)
        conversation = conv_repo.create(
            channel_account_id=account.id,
            channel_type=account.channel_type,
            external_conversation_id=wa_id,
            external_user_id=wa_id,
            session_id=session_id,
            organization_id=account.organization_id,
            agent_id=agent_id,
            customer_id=customer.id,
            last_inbound_at=None,
        )

    rendered = render_template_body(template, components)
    result = await deliver_whatsapp_template(
        db,
        session_record,
        template_name=template_name,
        language=language,
        components=components,
        rendered_text=rendered,
    )
    if not result.ok:
        if existing is None and not result.ambiguous:
            # A failed send must not leave an empty thread in the inbox: drop
            # the conversation, then the session it points at. The customer
            # row stays — harmless, and reused on the next attempt.
            #
            # Guarded, because an exception escaping here would replace the 502
            # (which names Meta's actual reason) with an opaque 500 AND leave
            # the empty thread this block exists to remove. Failing to clean up
            # is worth a log; losing the reason the send failed is not.
            from app.models.session_to_agent import SessionToAgent
            try:
                db.delete(conversation)
                db.query(SessionToAgent).filter(
                    SessionToAgent.session_id == session_id).delete()
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Could not roll back the empty outbound thread for "
                             f"session {session_id}: {e}")
        raise OutboundError(502, result.reason or "WhatsApp did not accept the message")

    # The AI reads this when the customer replies: a bare "yes" is meaningless
    # without knowing what we asked (see _run_chat_agent).
    conv_repo.set_extra(conversation, {
        **(conversation.extra or {}),
        "outbound_template": rendered,
    })
    return session_id
