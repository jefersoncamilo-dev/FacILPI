from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from .audit import add_audit


BOOTSTRAP_STATE_ID = "00000000-0000-0000-0000-000000000001"

UNINITIALIZED = "UNINITIALIZED"
PLATFORM_BOOTSTRAPPED = "PLATFORM_BOOTSTRAPPED"
FIRST_PASSWORD_CHANGED = "FIRST_PASSWORD_CHANGED"
ILPI_CREATED = "ILPI_CREATED"
ONBOARDING_IN_PROGRESS = "ONBOARDING_IN_PROGRESS"
ONBOARDING_COMPLETED = "ONBOARDING_COMPLETED"

STATE_ORDER = (
    UNINITIALIZED,
    PLATFORM_BOOTSTRAPPED,
    FIRST_PASSWORD_CHANGED,
    ILPI_CREATED,
    ONBOARDING_IN_PROGRESS,
    ONBOARDING_COMPLETED,
)
STATE_INDEX = {state: index for index, state in enumerate(STATE_ORDER)}

STATE_TIMESTAMP_FIELD = {
    PLATFORM_BOOTSTRAPPED: "platform_bootstrapped_at",
    FIRST_PASSWORD_CHANGED: "first_password_changed_at",
    ILPI_CREATED: "ilpi_created_at",
    ONBOARDING_IN_PROGRESS: "onboarding_started_at",
    ONBOARDING_COMPLETED: "onboarding_completed_at",
}


def state_conflict(message: str, *, code: str = "INVALID_BOOTSTRAP_STATE") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


async def load_bootstrap_state(db: AsyncSession, *, for_update: bool = False) -> m.BootstrapState:
    query = select(m.BootstrapState).where(m.BootstrapState.id == BOOTSTRAP_STATE_ID)
    if for_update:
        query = query.with_for_update()
    state = (await db.execute(query)).scalar_one_or_none()
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "BOOTSTRAP_STATE_MISSING", "message": "Estado de bootstrap ausente"},
        )
    return state


def assert_state(state: m.BootstrapState, expected: str) -> None:
    if state.estado != expected:
        raise state_conflict(
            f"Estado atual {state.estado}; esperado {expected}",
        )


def transition_state(
    db: AsyncSession,
    state: m.BootstrapState,
    next_state: str,
    *,
    usuario_id: str | None,
    request=None,
    detalhes: dict | None = None,
) -> None:
    current_index = STATE_INDEX.get(state.estado)
    next_index = STATE_INDEX.get(next_state)
    if current_index is None or next_index is None or next_index != current_index + 1:
        raise state_conflict(
            f"Transição inválida de {state.estado} para {next_state}",
            code="BOOTSTRAP_FORWARD_ONLY",
        )

    before = {"estado": state.estado}
    state.estado = next_state
    state.atualizado_por = usuario_id
    timestamp_field = STATE_TIMESTAMP_FIELD[next_state]
    setattr(state, timestamp_field, datetime.now(timezone.utc))

    after = {"estado": next_state}
    if detalhes:
        after.update(detalhes)
    add_audit(
        db,
        acao="bootstrap.estado_transicionado",
        entidade="bootstrap_state",
        registro_id=state.id,
        usuario_id=usuario_id,
        valores_anteriores=before,
        valores_posteriores=after,
        request=request,
    )


def public_status(state: m.BootstrapState) -> dict:
    return {
        "estado": state.estado,
        "platform_bootstrapped_at": state.platform_bootstrapped_at,
        "first_password_changed_at": state.first_password_changed_at,
        "ilpi_created_at": state.ilpi_created_at,
        "onboarding_started_at": state.onboarding_started_at,
        "onboarding_completed_at": state.onboarding_completed_at,
    }
