"""Test setup: every test runs against a fresh temporary SQLite database.

BIOPROCESS_DB_URL must be set before the app is imported, so it is set here at
module level (pytest imports conftest.py before the test modules).
"""

import os
import tempfile
from pathlib import Path

import pytest

TEST_DB_PATH = Path(tempfile.mkdtemp(prefix="bioprocess-test-")) / "test.db"
os.environ["BIOPROCESS_DB_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"

from sqlmodel import SQLModel  # noqa: E402

from app import db  # noqa: E402

assert Path(db.engine.url.database).resolve() != db.DEFAULT_DB_PATH.resolve(), "tests must not use the dev database"


@pytest.fixture(autouse=True)
def fresh_database():
    SQLModel.metadata.drop_all(db.engine)
    db.init_db()
    yield
