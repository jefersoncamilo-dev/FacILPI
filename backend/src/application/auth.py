import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..infrastructure.database import get_db
from ..infrastructure.models import User

AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
AUTH_CONTEXT_REQUIRED = "AUTH_CONTEXT_REQUIRED"

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod-min-32-chars-please")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY = int(os.getenv("JWT_EXPIRY", "3600"))
RATE_LIMIT_AUTH = int(os.getenv("RATE_LIMIT_AUTH", "10"))

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

def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=JWT_EXPIRY)
    payload = {
        "sub": user.id,
        "email": user.email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


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
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise _authentication_required("expired_token")
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise _authentication_required("invalid_token")

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
