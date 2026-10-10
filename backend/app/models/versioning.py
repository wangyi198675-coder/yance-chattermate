"""Configure narrow third-party model history before ORM models are declared.

SQLAlchemy-Continuum owns version/history mechanics only. Canonical current state
remains in the ChatterMate model tables.
"""
from sqlalchemy_continuum import make_versioned

_CONFIGURED = False


def configure_model_versioning() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    make_versioned(user_cls=None)
    _CONFIGURED = True
