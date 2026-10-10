"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
"""

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import cors
from app.core.config import settings
from app.core.socketio import sio
from app.core.application import app as api
import app.database as database
import app.main as main


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env(site_dir: Path, database_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": database_url,
            "ENVIRONMENT": "test",
            "REDIS_ENABLED": "false",
            "NO_ENTERPRISE": "1",
        }
    )
    current = env.get("PYTHONPATH")
    paths = [str(site_dir), str(BACKEND_ROOT)]
    if current:
        paths.append(current)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def test_static_cors_origins_exist_without_database_access():
    with patch("app.database.SessionLocal") as session_local:
        origins = cors.get_static_cors_origins()

    session_local.assert_not_called()
    assert origins == set(cors.BASE_CORS_ORIGINS)
    assert set(settings.CORS_ORIGINS).issubset(origins)


def test_import_app_main_performs_no_database_query(tmp_path):
    sentinel = tmp_path / "db-io-during-import.txt"
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        """
import os
from pathlib import Path
from sqlalchemy.orm import Session

_real_execute = Session.execute

def _guard_execute(self, *args, **kwargs):
    Path(os.environ["WINDOW21_DB_IO_SENTINEL"]).write_text("Session.execute")
    raise RuntimeError("DB I/O attempted during app.main import")

Session.execute = _guard_execute
""".lstrip(),
        encoding="utf-8",
    )
    env = _subprocess_env(
        tmp_path,
        "postgresql+psycopg://test:test@203.0.113.1:5432/chattermate",
    )
    env["WINDOW21_DB_IO_SENTINEL"] = str(sentinel)

    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print('IMPORT_OK')"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout
    assert not sentinel.exists(), "app.main import attempted database I/O"


def test_import_app_main_is_bounded_even_if_psycopg_connect_would_block(tmp_path):
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        """
import time
import psycopg

def _blocked_connect(*args, **kwargs):
    time.sleep(60)
    raise RuntimeError("simulated blackholed PostgreSQL")

psycopg.connect = _blocked_connect
""".lstrip(),
        encoding="utf-8",
    )
    env = _subprocess_env(
        tmp_path,
        "postgresql+psycopg://test:test@203.0.113.1:5432/chattermate",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import time; t=time.perf_counter(); import app.main; "
            "print(f'IMPORT_SECONDS={time.perf_counter()-t:.3f}')",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "IMPORT_SECONDS=" in result.stdout


def test_postgresql_connect_timeout_is_finite_and_non_postgres_is_unchanged(monkeypatch):
    pg_args = database.get_database_connect_args(
        "postgresql+psycopg://user:pass@db.example/chattermate"
    )
    assert pg_args["options"] == "-c client_encoding=utf8"
    assert isinstance(pg_args["connect_timeout"], int)
    assert 0 < pg_args["connect_timeout"] <= 30

    # libpq treats connect_timeout=0 as unbounded, so even a bad env override
    # must not silently restore the original indefinite-wait failure mode.
    monkeypatch.setattr(settings, "DATABASE_CONNECT_TIMEOUT", 0)
    assert database.get_database_connect_args(
        "postgresql+psycopg://user:pass@db.example/chattermate"
    )["connect_timeout"] == 1

    assert database.get_database_connect_args("sqlite:///:memory:") == {}


def test_socketio_import_uses_only_static_origins():
    assert set(sio.eio.cors_allowed_origins) == cors.get_static_cors_origins()


def test_dynamic_cors_keeps_org_help_center_and_custom_domain_semantics(monkeypatch):
    db = MagicMock()
    org_repo = MagicMock()
    org_repo.get_active_organizations.return_value = [
        SimpleNamespace(domain="acme.example")
    ]
    hc_repo = MagicMock()
    hc_repo.list_enabled_slugs.return_value = ["docs"]
    hc_repo.list_verified_domains.return_value = ["help.customer.example"]

    monkeypatch.setattr("app.database.SessionLocal", lambda: db)
    monkeypatch.setattr(
        "app.repositories.organization.OrganizationRepository",
        lambda _db: org_repo,
    )
    monkeypatch.setattr(
        "app.repositories.help_center.HelpCenterRepository",
        lambda _db: hc_repo,
    )
    cors.refresh_cors_origins()
    origins = cors.get_cors_origins()

    assert "https://acme.example" in origins
    assert "http://www.acme.example" in origins
    assert f"https://docs.{settings.HELP_CENTER_BASE_DOMAIN}" in origins
    assert "https://help.customer.example" in origins
    assert "http://help.customer.example" in origins
    import re
    assert re.match(
        cors.get_cors_origin_regex(),
        f"https://docs.{settings.HELP_CENTER_BASE_DOMAIN}",
    )
    db.close.assert_called_once_with()
    cors.refresh_cors_origins()


def test_local_cors_update_converges_fastapi_and_socketio_without_duplicate_owner(
    monkeypatch,
):
    test_api = FastAPI()
    test_api.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors.get_static_cors_origins()),
        allow_origin_regex=cors.get_cors_origin_regex(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    dynamic = [
        "https://chattermate.chat",
        "https://acme.example",
        "https://docs.chattermate.help",
        "https://help.customer.example",
    ]

    assert cors.update_local_cors(test_api, dynamic) is True

    cors_layers = [
        middleware
        for middleware in test_api.user_middleware
        if middleware.cls is CORSMiddleware
    ]
    assert len(cors_layers) == 1
    assert cors_layers[0].kwargs["allow_origins"] == dynamic
    assert set(sio.eio.cors_allowed_origins) == set(dynamic)


@pytest.mark.asyncio
async def test_startup_refreshes_dynamic_origins_after_import_and_converges(
    monkeypatch,
):
    test_api = FastAPI()
    test_api.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors.get_static_cors_origins()),
        allow_origin_regex=cors.get_cors_origin_regex(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    dynamic = {
        "https://chattermate.chat",
        "https://acme.example",
        "https://docs.chattermate.help",
    }

    monkeypatch.setattr(cors, "refresh_cors_origins", lambda: None)
    monkeypatch.setattr(cors, "get_cors_origins", lambda: dynamic)
    with (
        patch("app.core.redis.get_redis", return_value=None),
        patch("app.main.initialize_cors_listener") as listener,
        patch("app.main.configure_socketio") as configure,
        patch("app.main.run_auto_closer_loop", new=AsyncMock()) as auto_closer,
    ):
        await main.startup_event(test_api)
        await test_api.state.auto_closer_task

    cors_layers = [
        middleware
        for middleware in test_api.user_middleware
        if middleware.cls is CORSMiddleware
    ]
    assert len(cors_layers) == 1
    assert set(cors_layers[0].kwargs["allow_origins"]) == dynamic
    assert set(sio.eio.cors_allowed_origins) == dynamic
    configure.assert_called_once_with()
    listener.assert_called_once_with()
    auto_closer.assert_awaited_once_with()
