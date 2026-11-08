import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://payops:payops_local@localhost:5433/payops_test")
os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].replace("/payops?", "/payops_test?")
if not os.environ["DATABASE_URL"].endswith("payops_test"):
    raise RuntimeError("tests must run against the payops_test database")

# Deterministic: tests never depend on the developer .env webhook / provider settings.
os.environ["PAYPAL_WEBHOOK_ID"] = ""
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["LOCAL_CONSOLE"] = "0"
os.environ["REPLAY_LLM"] = "0"

import pytest
from sqlalchemy import text

from app.db.models import Base
from app.db.session import SessionLocal, engine

AS_OF = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)


# Guard the engine actually in use (not just the env var): if app.db.session was imported before this file set
# DATABASE_URL, the engine would point at the real database and drop_all below would wipe it.
if engine.url.database != "payops_test":
    raise RuntimeError(f"refusing to run destructive fixtures against database {engine.url.database!r}")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    assert engine.url.database == "payops_test"
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def db():
    assert engine.url.database == "payops_test"
    with engine.begin() as c:
        names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    with SessionLocal() as s:
        yield s
