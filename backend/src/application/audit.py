from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m


SENSITIVE_KEY_PARTS = (
    "senha",
    "password",
    "password_hash",
    "token",
    "cookie",
    "segredo",
    "secret",
    "bootstrap_token",
    "authorization",
)


def _is_sensitive_key(key: Any) -> bool:
    text = str(key).lower()
    return any(part in text for part in SENSITIVE_KEY_PARTS)


def _clean(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _clean(item)
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_clean(item) for item in value]
    return str(value)


def sanitize(value: Any) -> Any:
    return _clean(value)


def dumps_safe(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = sanitize(value)
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)


def add_audit(
    db: AsyncSession,
    *,
    acao: str,
    entidade: str | None = None,
    registro_id: str | None = None,
    usuario_id: str | None = None,
    ilpi_id: str | None = None,
    valores_anteriores: Any = None,
    valores_posteriores: Any = None,
    request: Request | None = None,
) -> m.Auditoria:
    audit = m.Auditoria(
        acao=acao,
        entidade=entidade,
        registro_id=registro_id,
        usuario_id=usuario_id,
        ilpi_id=ilpi_id,
        valores_anteriores=dumps_safe(valores_anteriores),
        valores_posteriores=dumps_safe(valores_posteriores),
        ip=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(audit)
    return audit
