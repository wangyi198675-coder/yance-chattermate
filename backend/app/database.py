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

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from sqlalchemy.pool import QueuePool


def get_database_connect_args(database_url: str) -> dict:
    """Driver connect args with a finite PostgreSQL network deadline.

    pool_timeout only bounds waiting for a SQLAlchemy pool slot. The psycopg
    driver connection attempt needs connect_timeout to avoid an unbounded
    startup/runtime wait when the database network path is blackholed.
    """
    if database_url.startswith("postgresql"):
        return {
            "options": "-c client_encoding=utf8",
            # libpq treats zero as unlimited; never allow configuration to
            # recreate the indefinite connection wait this fix removes.
            "connect_timeout": max(1, settings.DATABASE_CONNECT_TIMEOUT),
        }
    return {}


# Create SQLAlchemy engine with Unicode support
# t3.micro RDS has ~45-65 max connections, reserve some for admin and other services
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    poolclass=QueuePool,
    pool_size=5,  # Conservative pool size for t3.micro
    max_overflow=10,  # Allow up to 15 total connections from this pool
    pool_timeout=30,  # Timeout waiting for connection
    pool_recycle=1800,  # Recycle connections after 30 minutes
    connect_args=get_database_connect_args(settings.DATABASE_URL),
    json_serializer=lambda obj: __import__('json').dumps(obj, ensure_ascii=False),
    json_deserializer=lambda s: __import__('json').loads(s)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
