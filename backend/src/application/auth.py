import os
import time
import logging
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..infrastructure.database import get_db
from ..infrastructure.models import RefreshToken, User

AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
AUTH_CONTEXT_REQUIRED = "AUTH_CONTEXT_REQUIRED"

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod-min-32-chars-please")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY = int(os.getenv("JWT_EXPIRY", "3600"))
RATE_LIMIT_AUTH = int(os.getenv("RATE_LIMIT_AUTH", "10"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth"
ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")).lower()
REFRESH_COOKIE_SECURE = os.getenv(
    "REFRESH_COOKIE_SECURE",
    "true" if ENVIRONMENT in {"homolog", "homologacao", "staging", "production", "prod"} else "false",
).lower() == "true"

logger = logging.getLogger("facilpi.security")
security = HTTPBearer(auto_error=False)

# Simple in-memory rate limit per IP (for demo; production should use redis)
_rate_store: Dict[str, list] = {}

def check_rate_limit(key: str, limit: int = RATE_LIMIT_AUTH, window_sec: int = 60):
    now = time.time()
    lst = _rate_store.get(key, [])
    # clean old
    lst = [t for t in lst if now - t < window_sec]
    if len(lst) >= limit:
        raise HTTPException(status_code=429, detail="Muitas tentativas. Tente novamente em instantes.")
    lst.append(now)
    _rate_store[key] = lst

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

def create_access_token(
    user: User,
    *,
    scope: str | None = None,
    ilpi_id: str | None = None,
    perfil_id: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=JWT_EXPIRY)
    payload = {
        "sub": user.id,
        "email": user.email,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
        "exige_troca_senha": bool(getattr(user, "exige_troca_senha", False)),
    }
    if scope is not None:
        payload["scope"] = scope
        payload["ilpi_id"] = ilpi_id
        payload["perfil_id"] = perfil_id
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise _authentication_required("expired_token")
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise _authentication_required("invalid_token")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(18)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=REFRESH_COOKIE_SECURE,
        samesite="strict",
    )


async def issue_refresh_token(
    db: AsyncSession,
    user: User,
    *,
    scope: str | None,
    ilpi_id: str | None,
    perfil_id: str | None,
    request: Request | None = None,
    token_family: str | None = None,
    replaces: RefreshToken | None = None,
) -> str:
    raw_token = generate_refresh_token()
    now = datetime.now(timezone.utc)
    refresh_id = str(uuid.uuid4())
    family = token_family or str(uuid.uuid4())
    row = RefreshToken(
        id=refresh_id,
        user_id=user.id,
        token_hash=token_hash(raw_token),
        jti=str(uuid.uuid4()),
        token_family=family,
        ilpi_id=ilpi_id,
        perfil_id=perfil_id,
        expires_at=now + timedelta(days=REFRESH_TOKEN_DAYS),
        ip=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(row)
    await db.flush()
    if replaces is not None:
        replaces.revoked_at = now
        replaces.replaced_by = row.id
    return raw_token


async def load_refresh_token(db: AsyncSession, raw_token: str) -> RefreshToken | None:
    if not raw_token:
        return None
    return (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash(raw_token))
        )
    ).scalar_one_or_none()


def refresh_token_is_valid(row: RefreshToken | None) -> bool:
    if row is None or row.revoked_at is not None:
        return False
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


async def revoke_user_refresh_tokens(db: AsyncSession, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    for row in rows:
        row.revoked_at = now


def _authentication_required(reason: str) -> HTTPException:
    # Never include the token or decoder exception in the response/log.
    logger.warning("authentication_denied code=%s reason=%s", AUTHENTICATION_REQUIRED, reason)
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": AUTHENTICATION_REQUIRED,
            "message": "Autenticação obrigatória",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authentication_context_required(user_id: str) -> HTTPException:
    logger.warning(
        "authentication_denied code=%s reason=user_inactive user_id=%s",
        AUTH_CONTEXT_REQUIRED,
        user_id,
    )
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": AUTH_CONTEXT_REQUIRED,
            "message": "Contexto de autorização não disponível",
        },
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if (
        credentials is None
        or not isinstance(credentials.scheme, str)
        or credentials.scheme.lower() != "bearer"
    ):
        raise _authentication_required("missing_or_invalid_scheme")
    token = credentials.credentials
    payload = decode_access_token(token)

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise _authentication_required("missing_subject")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise _authentication_required("user_not_found")
    if not user.ativo:
        raise _authentication_context_required(user.id)
    return user
