"""SQLAlchemy engine and session factory."""
from __future__ import annotations

import os
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://zenkos:zenkos_dev@localhost:5433/zenkos",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Iterator[Session]:
    """Yield a SQLAlchemy session and close it when the caller is done."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
