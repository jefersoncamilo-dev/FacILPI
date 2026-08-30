import os
import time
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

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod-min-32-chars-please")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY = int(os.getenv("JWT_EXPIRY", "3600"))
RATE_LIMIT_AUTH = int(os.getenv("RATE_LIMIT_AUTH", "10"))

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

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Não autenticado")
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.ativo:
        raise HTTPException(status_code=401, detail="Usuário não encontrado ou inativo")
    return user
