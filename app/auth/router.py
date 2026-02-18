from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app import schemas
from app.auth import service
from app.config import get_db

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


@router.post("/register", response_model=schemas.UserResponse, status_code=201)
def register(body: schemas.RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user account."""
    user = service.create_user(db, body.email, body.password)
    return user


@router.post("/login", response_model=schemas.TokenResponse)
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and receive access + refresh tokens."""
    user = service.authenticate_user(db, body.email, body.password)
    access_token, refresh_token = service.create_token_pair(db, user)
    return schemas.TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=schemas.TokenResponse)
def refresh(body: schemas.RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new token pair."""
    access_token, refresh_token = service.refresh_tokens(db, body.refresh_token)
    return schemas.TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", response_model=schemas.MessageResponse)
def logout(body: schemas.LogoutRequest, db: Session = Depends(get_db)):
    """Revoke a refresh token (invalidate the session)."""
    service.revoke_refresh_token(db, body.refresh_token)
    return schemas.MessageResponse(message="Logged out successfully")
