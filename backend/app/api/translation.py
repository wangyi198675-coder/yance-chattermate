"""Authenticated Window178 translation composition API."""
from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.database import get_db
from app.models.agent import Agent
from app.models.chat_history import ChatHistory
from app.models.customer import Customer
from app.models.session_to_agent import SessionToAgent
from app.models.user import User
from app.services.translation import (
    CHINESE_TARGET,
    TranslationProviderError,
    contact_target_language,
    failed_projection,
    get_translation_owner,
    infer_source_language,
    normalize_target_language,
    public_language_code,
    realism_context,
    set_contact_language,
    set_observed_language,
    source_sha256,
    stored_projection,
    success_projection,
    validate_integrity,
    persist_projection,
)

router = APIRouter()


class ContactLanguageRequest(BaseModel):
    language: str = Field(min_length=2, max_length=16)


class EnsureTranslationsRequest(BaseModel):
    message_ids: list[int] = Field(min_length=1, max_length=50)
    force: bool = False


class TranslationPreviewRequest(BaseModel):
    customer_id: UUID
    session_id: UUID
    text: str = Field(min_length=1, max_length=5000)
    source_language: Optional[str] = Field(default=None, max_length=16)


def _customer_for_user(db: Session, customer_id: UUID, current_user: User) -> Customer:
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.organization_id == current_user.organization_id,
    ).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="customer_not_found")
    return customer


def _persona_instructions_for_session(
    db: Session,
    *,
    session_id: UUID,
    customer_id: UUID,
    current_user: User,
) -> list[str]:
    session_row = db.query(SessionToAgent).filter(
        SessionToAgent.session_id == session_id,
        SessionToAgent.customer_id == customer_id,
        SessionToAgent.organization_id == current_user.organization_id,
    ).first()
    if not session_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    if not session_row.agent_id:
        return []
    agent = db.query(Agent).filter(
        Agent.id == session_row.agent_id,
        Agent.organization_id == current_user.organization_id,
    ).first()
    return list(agent.instructions or []) if agent else []


def _provider_error(exc: TranslationProviderError) -> HTTPException:
    detail = str(exc)
    if detail == "translation_owner_not_configured":
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    if detail == "unsupported_target_language":
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="translation_provider_failed")


@router.get("/health")
async def translation_health(current_user: User = Depends(get_current_user)):
    _ = current_user
    return await get_translation_owner().health()


@router.put("/contacts/{customer_id}/language")
async def update_contact_language(
    customer_id: UUID,
    payload: ContactLanguageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = _customer_for_user(db, customer_id, current_user)
    language = payload.language.strip().lower().replace("_", "-")
    try:
        metadata = set_contact_language(customer, language)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    return {
        "customerId": str(customer.id),
        "preferredLanguage": metadata.get("preferredLanguage", "auto"),
        "effectiveLanguage": contact_target_language(customer),
    }


@router.post("/messages/ensure")
async def ensure_message_translations(
    payload: EnsureTranslationsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requested = list(dict.fromkeys(payload.message_ids))
    rows = db.query(ChatHistory).filter(
        ChatHistory.id.in_(requested),
        ChatHistory.organization_id == current_user.organization_id,
    ).all()
    by_id = {row.id: row for row in rows}
    owner = get_translation_owner()
    projections: list[dict] = []

    for message_id in requested:
        message = by_id.get(message_id)
        if not message or message.message_type != "user":
            continue

        current = stored_projection(message)
        if current and current.get("status") in {"success", "failed"} and not payload.force:
            projections.append(current)
            continue

        source = message.message or ""
        deterministic_source = infer_source_language(source)
        if deterministic_source == "zh":
            # Same-language translation is a no-op and creates no translation state.
            continue

        try:
            result = await owner.translate(
                source,
                target_language=CHINESE_TARGET,
                context=(
                    realism_context(
                        message.customer,
                        direction="inbound",
                        persona_instructions=(message.agent.instructions if message.agent else []),
                    )
                    if message.customer
                    else None
                ),
            )
        except TranslationProviderError as exc:
            projection = failed_projection(
                message,
                error_code=(
                    "OWNER_NOT_CONFIGURED"
                    if str(exc) == "translation_owner_not_configured"
                    else "PROVIDER_FAILED"
                ),
                source_language=deterministic_source,
                target_language=CHINESE_TARGET,
            )
            persist_projection(message, projection)
            projections.append(projection)
            continue

        detected = public_language_code(result.detected_source_language) or deterministic_source
        if detected == "zh":
            # DeepL detected same-language source. Do not create a successful shadow projection.
            attrs = dict(message.attributes or {})
            attrs.pop("yance_translation", None)
            message.attributes = attrs
            if message.customer:
                set_observed_language(message.customer, detected)
            continue

        failures = validate_integrity(
            source,
            result.text,
            source_language=detected,
            target_language="zh",
        )
        if failures:
            projection = failed_projection(
                message,
                error_code="TRANSLATION_OUTPUT_INVALID",
                failures=failures,
                source_language=detected,
                target_language=CHINESE_TARGET,
            )
        else:
            projection = success_projection(
                message,
                result,
                target_language=CHINESE_TARGET,
            )
        persist_projection(message, projection)
        if message.customer:
            set_observed_language(message.customer, detected)
        projections.append(projection)

    db.commit()
    return {"translations": projections}


@router.post("/messages/{message_id}/recompute")
async def recompute_message_translation(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await ensure_message_translations(
        EnsureTranslationsRequest(message_ids=[message_id], force=True),
        current_user,
        db,
    )


@router.post("/preview")
async def translation_preview(
    payload: TranslationPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = _customer_for_user(db, payload.customer_id, current_user)
    persona_instructions = _persona_instructions_for_session(
        db,
        session_id=payload.session_id,
        customer_id=payload.customer_id,
        current_user=current_user,
    )
    target = contact_target_language(customer)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="contact_language_unknown",
        )
    if not normalize_target_language(target):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="unsupported_target_language",
        )

    source_language = public_language_code(payload.source_language) or infer_source_language(payload.text)
    if source_language and source_language == public_language_code(target):
        return {
            "status": "same_language",
            "text": payload.text,
            "sourceLanguage": source_language,
            "targetLanguage": public_language_code(target),
            "integrity": "passed",
            "sourceSha256": source_sha256(payload.text),
            "stylePolicy": "persona_chat_preserve_v1",
            "humanLikeness": "preserved",
        }

    owner = get_translation_owner()
    try:
        result = await owner.translate(
            payload.text,
            target_language=target,
            source_language=source_language,
            context=realism_context(
                customer,
                direction="outbound",
                persona_instructions=persona_instructions,
            ),
        )
    except TranslationProviderError as exc:
        raise _provider_error(exc) from exc

    detected = public_language_code(result.detected_source_language) or source_language
    if detected and detected == public_language_code(target):
        set_observed_language(customer, detected)
        db.commit()
        return {
            "status": "same_language",
            "text": payload.text,
            "sourceLanguage": detected,
            "targetLanguage": public_language_code(target),
            "integrity": "passed",
            "sourceSha256": source_sha256(payload.text),
            "stylePolicy": "persona_chat_preserve_v1",
            "humanLikeness": "preserved",
        }

    failures = validate_integrity(
        payload.text,
        result.text,
        source_language=detected,
        target_language=target,
    )
    if failures:
        return {
            "status": "failed",
            "errorCode": "TRANSLATION_OUTPUT_INVALID",
            "integrity": "failed",
            "integrityFailures": sorted(set(failures)),
            "sourceLanguage": detected,
            "targetLanguage": public_language_code(target),
            "sourceSha256": source_sha256(payload.text),
            "stylePolicy": "persona_chat_preserve_v1",
            "humanLikeness": "blocked",
        }

    if detected:
        set_observed_language(customer, detected)
        db.commit()
    return {
        "status": "success",
        "text": result.text,
        "sourceLanguage": detected,
        "targetLanguage": public_language_code(target),
        "integrity": "passed",
        "provider": "deepl",
        "providerModel": result.model_type,
        "sourceSha256": source_sha256(payload.text),
        "stylePolicy": "persona_chat_preserve_v1",
        "humanLikeness": "preserved",
    }
