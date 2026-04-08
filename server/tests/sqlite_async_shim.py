"""AsyncSession-compatible shim for SQLite tests in restricted environments."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


class AsyncSessionShim:
    """Minimal async wrapper around a sync SQLAlchemy Session."""

    def __init__(self, session: Session):
        self._session = session

    async def __aenter__(self) -> AsyncSessionShim:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._session.close()

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def add_all(self, instances: Iterable[Any]) -> None:
        self._session.add_all(list(instances))

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, instance: Any, attribute_names: list[str] | None = None) -> None:
        self._session.refresh(instance, attribute_names=attribute_names)

    async def flush(self) -> None:
        self._session.flush()

    async def execute(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return self._session.execute(statement, params=params, **kwargs)

    async def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        return self._session.get(entity, ident, **kwargs)

    async def delete(self, instance: Any) -> None:
        self._session.delete(instance)

    async def close(self) -> None:
        self._session.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


class AsyncSessionMakerShim:
    """Callable object compatible with async_sessionmaker() usage."""

    def __init__(self, sync_session_maker: sessionmaker[Session]):
        self._sync_session_maker = sync_session_maker

    def __call__(self, *args: Any, **kwargs: Any) -> AsyncSessionShim:
        return AsyncSessionShim(self._sync_session_maker(*args, **kwargs))


def create_sqlite_async_shim(db_path: str) -> tuple[Engine, AsyncSessionMakerShim]:
    """Build a file-backed SQLite engine plus async-session shim."""
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    sync_session_maker = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, AsyncSessionMakerShim(sync_session_maker)
