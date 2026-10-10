from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import types

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_APP_ROOT = _BACKEND_ROOT / "app"
for name, path in {
    "app": _APP_ROOT,
    "app.models": _APP_ROOT / "models",
    "app.models.schemas": _APP_ROOT / "models" / "schemas",
}.items():
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]
        sys.modules[name] = pkg

from app.models.schemas.people import project_person_profile


def test_birth_date_projects_dynamic_exact_age():
    profile = project_person_profile(
        {"person_profile": {"birth_date": "1983-10-07"}},
        as_of=date(2026, 10, 6),
    )
    assert profile is not None
    assert profile.age == 42
    assert profile.age_precision == "exact"


def test_birth_year_projects_year_level_precision():
    profile = project_person_profile(
        {"person_profile": {"birth_year": 1983}},
        as_of=date(2026, 10, 6),
    )
    assert profile is not None
    assert profile.age == 43
    assert profile.age_precision == "year"
    assert profile.birth_year == 1983


def test_observed_age_is_not_treated_as_timeless_birth_fact():
    meta = {
        "person_profile": {
            "age_observation": {
                "value": 43,
                "observed_at": "2026-09-01T10:00:00Z",
                "confidence": 0.9,
                "source_ref": "message:42",
            }
        }
    }
    profile = project_person_profile(meta, as_of=date(2030, 10, 6))
    assert profile is not None
    assert profile.age == 43
    assert profile.age_precision == "observed"
    assert profile.age_observation is not None
    assert profile.age_observation.observed_at == "2026-09-01T10:00:00Z"
    assert "age" not in meta["person_profile"]


def test_missing_or_invalid_person_profile_is_absent():
    assert project_person_profile(None) is None
    assert project_person_profile({}) is None
    assert project_person_profile({"person_profile": "Berlin"}) is None


def test_city_and_occupation_project_from_fixed_profile_keys():
    profile = project_person_profile(
        {"person_profile": {"city": "Berlin", "occupation": "Designer", "country_code": "DE"}}
    )
    assert profile is not None
    assert profile.city == "Berlin"
    assert profile.occupation == "Designer"
    assert profile.country_code == "DE"


def test_projection_never_overwrites_canonical_location_values():
    meta = {
        "person_profile": {
            "country": "Germany",
            "city": "Cuxhaven",
            "raw_location": "Cuxhaven, Germany",
        }
    }
    original = deepcopy(meta)
    profile = project_person_profile(meta)
    assert profile is not None
    assert profile.city == "Cuxhaven"
    assert meta == original


def test_avatar_is_bounded_current_accepted_projection():
    profile = project_person_profile(
        {
            "person_profile": {
                "avatar": {
                    "url": "https://example.test/avatar.jpg",
                    "source_channel": "messenger",
                    "provider_user_id": "psid-1",
                    "observed_at": "2026-10-05T12:00:00Z",
                    "source_ref": "meta-thread:1",
                    "confidence": 0.99,
                }
            }
        }
    )
    assert profile is not None
    assert profile.avatar is not None
    assert profile.avatar.url == "https://example.test/avatar.jpg"
    assert profile.avatar.source_channel == "messenger"


def test_projection_is_wired_into_native_people_and_recent_chat_paths():
    people_repo = (_APP_ROOT / "repositories" / "people.py").read_text(encoding="utf-8")
    chat_repo = (_APP_ROOT / "repositories" / "chat.py").read_text(encoding="utf-8")

    assert '"profile": project_person_profile(customer.meta_data)' in people_repo
    assert "Customer.meta_data.label('customer_meta_data')" in chat_repo
    assert "'profile': project_person_profile(r.customer_meta_data)" in chat_repo


def test_customer_model_does_not_gain_profile_columns():
    customer_model = (_APP_ROOT / "models" / "customer.py").read_text(encoding="utf-8")
    assert "profile = Column(" not in customer_model
    assert "birth_date = Column(" not in customer_model
    assert "occupation = Column(" not in customer_model
