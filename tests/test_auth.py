"""Tests for authentication endpoints and service layer."""
import pytest

from tests.conftest import VALID_EMAIL, VALID_PASSWORD


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_success(self, client):
        resp = client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": "ValidPass1!"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "new@example.com"
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data
        # Password must never be returned
        assert "password" not in data
        assert "hashed_password" not in data

    def test_register_duplicate_email(self, client, registered_user):
        resp = client.post(
            "/auth/register",
            json={"email": VALID_EMAIL, "password": VALID_PASSWORD},
        )
        assert resp.status_code == 409

    def test_register_invalid_email(self, client):
        resp = client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "ValidPass1!"},
        )
        assert resp.status_code == 422

    def test_register_password_too_short(self, client):
        resp = client.post(
            "/auth/register",
            json={"email": "short@example.com", "password": "abc"},
        )
        assert resp.status_code == 422

    def test_register_missing_fields(self, client):
        resp = client.post("/auth/register", json={})
        assert resp.status_code == 422

    def test_register_missing_password(self, client):
        resp = client.post("/auth/register", json={"email": "a@b.com"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_success(self, client, registered_user):
        resp = client.post(
            "/auth/login",
            json={"email": VALID_EMAIL, "password": VALID_PASSWORD},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client, registered_user):
        resp = client.post(
            "/auth/login",
            json={"email": VALID_EMAIL, "password": "WrongPass!"},
        )
        assert resp.status_code == 401

    def test_login_unknown_email(self, client):
        resp = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "AnyPass!"},
        )
        assert resp.status_code == 401

    def test_login_invalid_email_format(self, client):
        resp = client.post(
            "/auth/login",
            json={"email": "bad-email", "password": "AnyPass!"},
        )
        assert resp.status_code == 422

    def test_login_no_user_enumeration(self, client, registered_user):
        """Wrong password and unknown user must return the same status code."""
        resp_wrong_pw = client.post(
            "/auth/login",
            json={"email": VALID_EMAIL, "password": "WrongPass!"},
        )
        resp_unknown = client.post(
            "/auth/login",
            json={"email": "noone@example.com", "password": "AnyPass!"},
        )
        assert resp_wrong_pw.status_code == resp_unknown.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

class TestRefresh:
    def test_refresh_success(self, client, tokens):
        resp = client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New tokens must be different from old ones
        assert data["access_token"] != tokens["access_token"]
        assert data["refresh_token"] != tokens["refresh_token"]

    def test_refresh_old_token_revoked(self, client, tokens):
        """After refresh, the original refresh token must be invalidated."""
        original_refresh = tokens["refresh_token"]
        # First refresh succeeds
        client.post("/auth/refresh", json={"refresh_token": original_refresh})
        # Reusing the old token must fail
        resp = client.post("/auth/refresh", json={"refresh_token": original_refresh})
        assert resp.status_code == 401

    def test_refresh_invalid_token(self, client):
        resp = client.post(
            "/auth/refresh",
            json={"refresh_token": "not.a.valid.token"},
        )
        assert resp.status_code == 401

    def test_refresh_access_token_as_refresh(self, client, tokens):
        """Using an access token where a refresh token is expected must fail."""
        resp = client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["access_token"]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_success(self, client, tokens):
        resp = client.post(
            "/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    def test_logout_token_invalidated(self, client, tokens):
        """After logout the refresh token must not work for a new refresh."""
        client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
        resp = client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert resp.status_code == 401

    def test_logout_idempotent(self, client, tokens):
        """Calling logout twice on the same token must succeed both times."""
        refresh_token = tokens["refresh_token"]
        resp1 = client.post("/auth/logout", json={"refresh_token": refresh_token})
        resp2 = client.post("/auth/logout", json={"refresh_token": refresh_token})
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    def test_logout_invalid_token(self, client):
        resp = client.post(
            "/auth/logout",
            json={"refresh_token": "garbage"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Service-level unit tests
# ---------------------------------------------------------------------------

class TestAuthService:
    def test_hash_and_verify_password(self):
        from app.auth.service import hash_password, verify_password

        hashed = hash_password("MyP@ssw0rd")
        assert hashed != "MyP@ssw0rd"
        assert verify_password("MyP@ssw0rd", hashed) is True
        assert verify_password("WrongPass", hashed) is False

    def test_create_user(self, db_session):
        from app.auth.service import create_user

        user = create_user(db_session, "unit@example.com", "SecretPass1")
        assert user.id is not None
        assert user.email == "unit@example.com"
        assert user.is_active is True

    def test_create_user_duplicate_raises(self, db_session):
        from app.auth.service import create_user
        from app.exceptions import ConflictError

        create_user(db_session, "dup@example.com", "SecretPass1")
        with pytest.raises(ConflictError):
            create_user(db_session, "dup@example.com", "OtherPass1")

    def test_authenticate_user_success(self, db_session):
        from app.auth.service import authenticate_user, create_user

        create_user(db_session, "auth@example.com", "SecretPass1")
        user = authenticate_user(db_session, "auth@example.com", "SecretPass1")
        assert user.email == "auth@example.com"

    def test_authenticate_user_wrong_password(self, db_session):
        from app.auth.service import authenticate_user, create_user
        from app.exceptions import AuthInvalidCredentials

        create_user(db_session, "badpw@example.com", "SecretPass1")
        with pytest.raises(AuthInvalidCredentials):
            authenticate_user(db_session, "badpw@example.com", "WrongPass")

    def test_authenticate_user_not_found(self, db_session):
        from app.auth.service import authenticate_user
        from app.exceptions import AuthInvalidCredentials

        with pytest.raises(AuthInvalidCredentials):
            authenticate_user(db_session, "ghost@example.com", "AnyPass")


# ---------------------------------------------------------------------------
# JWT unit tests
# ---------------------------------------------------------------------------

class TestJWT:
    def test_create_and_decode_access_token(self):
        from app.auth.jwt import create_access_token, decode_token

        token = create_access_token("42")
        claims = decode_token(token, "access")
        assert claims["sub"] == "42"
        assert claims["type"] == "access"

    def test_wrong_token_type_rejected(self):
        from app.auth.jwt import create_access_token, decode_token
        from app.exceptions import AuthTokenInvalid

        token = create_access_token("42")
        with pytest.raises(AuthTokenInvalid):
            decode_token(token, "refresh")

    def test_tampered_token_rejected(self):
        from app.auth.jwt import create_access_token, decode_token
        from app.exceptions import AuthTokenInvalid

        token = create_access_token("42")
        tampered = token[:-4] + "xxxx"
        with pytest.raises(AuthTokenInvalid):
            decode_token(tampered, "access")

    def test_expired_token_raises(self):
        """Create a token with a past expiry and verify the right error is raised."""
        from datetime import datetime, timedelta, timezone

        from jose import jwt

        from app.auth.jwt import decode_token
        from app.config import settings
        from app.exceptions import AuthTokenExpired

        past = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        payload = {
            "sub": "1",
            "jti": "abc",
            "type": "access",
            "exp": past,
            "iat": past - timedelta(minutes=15),
        }
        token = jwt.encode(
            payload,
            settings.secret_key.get_secret_value(),
            algorithm=settings.algorithm,
        )
        with pytest.raises(AuthTokenExpired):
            decode_token(token, "access")
