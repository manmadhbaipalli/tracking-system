import uuid
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token, create_refresh_token, decode_token
from app.config import settings
from app.exceptions import AuthInvalidCredentials, AuthTokenRevoked, ConflictError
from app.logging_config import get_logger
from app.models import RefreshToken, User

logger = get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, email: str, password: str) -> User:
    existing = get_user_by_email(db, email)
    if existing:
        raise ConflictError("Email already registered")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("User created", extra={"user_id": user.id, "email": email})
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    # Same error for missing user and wrong password — no user enumeration
    if not user or not verify_password(password, user.hashed_password):
        raise AuthInvalidCredentials("Invalid email or password")

    logger.info("User authenticated", extra={"user_id": user.id})
    return user


def create_token_pair(db: Session, user: User) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    access_token = create_access_token(str(user.id), jti)
    refresh_token = create_refresh_token(str(user.id), jti)

    expires_at = datetime.now(tz=timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    db_token = RefreshToken(
        jti=jti,
        user_id=user.id,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(db_token)
    db.commit()

    return access_token, refresh_token


def refresh_tokens(db: Session, refresh_token_str: str) -> tuple[str, str]:
    claims = decode_token(refresh_token_str, expected_type="refresh")
    jti = claims["jti"]

    db_token = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    if not db_token or db_token.revoked:
        raise AuthTokenRevoked("Refresh token has been revoked")

    now = datetime.now(tz=timezone.utc)
    # Compare timezone-aware now with expires_at (may be naive from SQLite)
    expires_at = db_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise AuthTokenRevoked("Refresh token has expired")

    # Revoke old token
    db_token.revoked = True
    db.commit()

    user = db.query(User).filter(User.id == db_token.user_id).first()
    return create_token_pair(db, user)


def revoke_refresh_token(db: Session, refresh_token_str: str) -> None:
    # Raises AuthTokenInvalid if malformed
    claims = decode_token(refresh_token_str, expected_type="refresh")
    jti = claims["jti"]

    db_token = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    if db_token and not db_token.revoked:
        db_token.revoked = True
        db.commit()
    # Idempotent: already revoked or not found → silently succeed
