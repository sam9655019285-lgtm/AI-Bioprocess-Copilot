"""SQLite engine, table creation and session handling.

The database lives at backend/data/bioprocess.db unless BIOPROCESS_DB_URL is set
(the tests point it at a temporary file).
"""

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, SQLModel, create_engine

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "bioprocess.db"
DATABASE_URL = os.environ.get("BIOPROCESS_DB_URL", f"sqlite:///{DEFAULT_DB_PATH.as_posix()}")


def create_db_engine(url: str) -> Engine:
    new_engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(new_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        # SQLite only enforces foreign keys (and ON DELETE CASCADE) when asked to.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return new_engine


engine = create_db_engine(DATABASE_URL)


def init_db(target: Engine | None = None) -> None:
    """Create the database file and tables if they do not exist yet."""
    target = target or engine
    database = make_url(str(target.url)).database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    from . import db_models  # noqa: F401  (registers the tables)

    SQLModel.metadata.create_all(target)


def get_session():
    """FastAPI dependency: one session per request."""
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope():
    """Session for code outside a request (e.g. the simulator WebSocket)."""
    with Session(engine) as session:
        yield session
