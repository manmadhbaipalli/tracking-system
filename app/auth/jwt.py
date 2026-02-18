import uuid
from datetime import datetime, timedelta, timezone

from jose import ExpiredSignatureError, JWTError, jwt

from app.config import settings
from app.exceptions import AuthTokenExpired, AuthTokenInvalid


def create_access_token(subject: str, jti: str | None = None) -> str:
    jti = jti or uuid.uuid4().hex
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "jti": jti,
        "type": "access",
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=settings.algorithm)


def create_refresh_token(subject: str, jti: str) -> str:
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": subject,
        "jti": jti,
        "type": "refresh",
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=settings.algorithm)


def decode_token(token: str, expected_type: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=["HS256"],
        )
    except ExpiredSignatureError:
        raise AuthTokenExpired("Token has expired")
    except JWTError:
        raise AuthTokenInvalid("Token is invalid")

    if claims.get("type") != expected_type:
        raise AuthTokenInvalid(f"Expected token type '{expected_type}', got '{claims.get('type')}'")

    return claims
