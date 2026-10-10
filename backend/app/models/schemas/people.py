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

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import date, datetime

from app.models.customer import LeadStage


class PersonProfileAgeObservation(BaseModel):
    value: int
    observed_at: Optional[str] = None
    confidence: Optional[float] = None
    source_ref: Optional[str] = None


class PersonProfileAvatar(BaseModel):
    url: str
    source_channel: Optional[str] = None
    provider_user_id: Optional[str] = None
    observed_at: Optional[str] = None
    source_ref: Optional[str] = None
    confidence: Optional[float] = None


class PersonProfileProjection(BaseModel):
    """Bounded read projection over Customer.meta_data.person_profile.

    This is deliberately a DTO only: Customer.meta_data remains the canonical
    storage authority and no second profile/contact store is introduced.
    """
    birth_date: Optional[str] = None
    birth_year: Optional[int] = None
    age: Optional[int] = None
    age_precision: Optional[str] = None
    age_observation: Optional[PersonProfileAgeObservation] = None
    country_code: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    raw_location: Optional[str] = None
    occupation: Optional[str] = None
    avatar: Optional[PersonProfileAvatar] = None


def project_person_profile(
    meta_data: Optional[Dict[str, Any]],
    *,
    as_of: Optional[date] = None,
) -> Optional[PersonProfileProjection]:
    """Project admitted fixed profile keys without mutating canonical JSON.

    Age precedence is exact birth date -> birth year -> latest accepted observed
    age. Observed ages are never incremented: without a birth fact we cannot
    infer a birthday.
    """
    if not isinstance(meta_data, dict):
        return None
    raw = meta_data.get("person_profile")
    if not isinstance(raw, dict):
        return None

    today = as_of or date.today()
    out: Dict[str, Any] = {}

    def copy_text(key: str) -> None:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value

    for key in ("country_code", "country", "region", "city", "raw_location", "occupation"):
        copy_text(key)

    birth_date_raw = raw.get("birth_date")
    parsed_birth_date: Optional[date] = None
    if isinstance(birth_date_raw, str) and birth_date_raw.strip():
        try:
            parsed_birth_date = date.fromisoformat(birth_date_raw.strip()[:10])
        except ValueError:
            parsed_birth_date = None
        if parsed_birth_date and parsed_birth_date <= today:
            out["birth_date"] = birth_date_raw
            out["age"] = (
                today.year
                - parsed_birth_date.year
                - ((today.month, today.day) < (parsed_birth_date.month, parsed_birth_date.day))
            )
            out["age_precision"] = "exact"

    birth_year_raw = raw.get("birth_year")
    birth_year: Optional[int] = None
    if isinstance(birth_year_raw, int) and not isinstance(birth_year_raw, bool):
        birth_year = birth_year_raw
    elif isinstance(birth_year_raw, str) and birth_year_raw.isdigit():
        birth_year = int(birth_year_raw)
    if birth_year and 1900 <= birth_year <= today.year:
        out["birth_year"] = birth_year
        if "age" not in out:
            out["age"] = today.year - birth_year
            out["age_precision"] = "year"

    observation = raw.get("age_observation")
    if isinstance(observation, dict):
        value = observation.get("value")
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 130:
            obs: Dict[str, Any] = {"value": value}
            for key in ("observed_at", "source_ref"):
                obs_value = observation.get(key)
                if isinstance(obs_value, str) and obs_value:
                    obs[key] = obs_value
            confidence = observation.get("confidence")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                obs["confidence"] = float(confidence)
            out["age_observation"] = obs
            if "age" not in out:
                out["age"] = value
                out["age_precision"] = "observed"

    avatar = raw.get("avatar")
    if isinstance(avatar, dict):
        url = avatar.get("url")
        if isinstance(url, str) and url.strip():
            projected_avatar: Dict[str, Any] = {"url": url}
            for key in ("source_channel", "provider_user_id", "observed_at", "source_ref"):
                avatar_value = avatar.get(key)
                if isinstance(avatar_value, str) and avatar_value:
                    projected_avatar[key] = avatar_value
            confidence = avatar.get("confidence")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                projected_avatar["confidence"] = float(confidence)
            out["avatar"] = projected_avatar

    if not out:
        return None
    return PersonProfileProjection(**out)


class PersonListItem(BaseModel):
    id: UUID
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_anonymous: bool = False
    lead_stage: LeadStage
    qualified: bool = False
    source: Optional[Dict[str, Any]] = None
    captured_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    synced: bool = False  # phase 1: CRM sync not implemented
    profile: Optional[PersonProfileProjection] = None


class PeopleListResponse(BaseModel):
    items: List[PersonListItem]
    total: int
    page: int
    page_size: int


class PeopleStats(BaseModel):
    total_people: int
    # Engaged-but-unidentified browser sessions — the lead-capture funnel's
    # raw top, shown as a count beside the tabs, not as directory rows.
    anonymous: int = 0
    new_leads_7d: int
    customers: int
    synced_to_crm: int = 0  # phase 1: always 0


class TimelineEntry(BaseModel):
    stage: str
    at: datetime


class PersonConversation(BaseModel):
    session_id: UUID
    agent_name: Optional[str] = None
    status: Optional[str] = None
    last_message: Optional[str] = None
    created_at: Optional[datetime] = None


class PersonDetail(BaseModel):
    id: UUID
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    # True when something can reach/recognize this person (real email, phone,
    # or a qualifying capture). Gates Mark-as-customer and outbound actions.
    identified: bool = False
    is_anonymous: bool = False
    lead_stage: LeadStage
    qualified: bool = False
    source: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    lead_qualified_at: Optional[datetime] = None
    meta_data: Optional[Dict[str, Any]] = None
    profile: Optional[PersonProfileProjection] = None
    # AI-written qualification summary from the conversation.
    summary: Optional[str] = None
    # Contact/detail fields captured across submissions.
    captured_attributes: Dict[str, Any] = {}
    timeline: List[TimelineEntry] = []
    conversations: List[PersonConversation] = []


class PersonUpdateRequest(BaseModel):
    """Drawer edit: both fields optional; phone "" clears the number."""
    full_name: Optional[str] = None
    phone: Optional[str] = None
