"""Shared test fixtures."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_db
from app.main import create_app
from app.models import Base, create_tables

# Use an in-memory SQLite database for tests
TEST_DATABASE_URL = "sqlite://"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture()
def db_session(engine):
    """Yield a transactional session that is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    """FastAPI test client wired to the test database session."""
    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

VALID_EMAIL = "test@example.com"
VALID_PASSWORD = "Secr3tPass!"


@pytest.fixture()
def registered_user(client):
    """Register a user and return the response JSON."""
    resp = client.post(
        "/auth/register",
        json={"email": VALID_EMAIL, "password": VALID_PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def tokens(client, registered_user):
    """Log in and return the token pair."""
    resp = client.post(
        "/auth/login",
        json={"email": VALID_EMAIL, "password": VALID_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
