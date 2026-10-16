from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import secrets
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..application.audit import add_audit
from ..application.auth import hash_password
from ..application.bootstrap_state import (
    PLATFORM_BOOTSTRAPPED,
    UNINITIALIZED,
    assert_state,
    load_bootstrap_state,
    transition_state,
)
from ..application.fase3a import ADMIN_EMAIL, PLATFORM_SUPERUSER_KEY, _new_id, _temporary_password
from ..infrastructure import models as m
from ..infrastructure.database import SessionLocal


@dataclass(frozen=True)
class BootstrapResult:
    user_id: str
    email: str
    temporary_password: str
    state: str


class BootstrapFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _validate_token(provided_token: str | None) -> None:
    expected_token = os.getenv("BOOTSTRAP_TOKEN")
    if not expected_token:
        raise BootstrapFailure("BOOTSTRAP_TOKEN_MISSING", "BOOTSTRAP_TOKEN ausente")
    if not provided_token or not secrets.compare_digest(expected_token, provided_token):
        raise BootstrapFailure("BOOTSTRAP_TOKEN_INVALID", "BOOTSTRAP_TOKEN incorreto")


async def run_bootstrap(provided_token: str | None) -> BootstrapResult:
    _validate_token(provided_token)
    temporary_password = _temporary_password()
    async with SessionLocal() as db:
        try:
            state = await load_bootstrap_state(db, for_update=True)
            assert_state(state, UNINITIALIZED)

            existing = (
                await db.execute(select(m.User).where(m.User.email == ADMIN_EMAIL))
            ).scalar_one_or_none()
            if existing is not None:
                raise BootstrapFailure("BOOTSTRAP_ADMIN_EXISTS", "admin@ilpi.com já existe")

            profile = (
                await db.execute(
                    select(m.Perfil).where(
                        m.Perfil.chave == PLATFORM_SUPERUSER_KEY,
                        m.Perfil.ilpi_id.is_(None),
                        m.Perfil.escopo == "global",
                    )
                )
            ).scalar_one_or_none()
            if profile is None:
                raise BootstrapFailure("PLATFORM_PROFILE_MISSING", "Perfil platform_superuser ausente")

            user = m.User(
                id=_new_id(),
                nome="Administrador da Plataforma",
                email=ADMIN_EMAIL,
                password_hash=hash_password(temporary_password),
                ativo=True,
                is_superuser=True,
                exige_troca_senha=True,
            )
            link = m.UsuarioIlpiPerfil(
                id=_new_id(),
                usuario_id=user.id,
                ilpi_id=None,
                perfil_id=profile.id,
                situacao="ativo",
            )
            db.add_all([user, link])
            await db.flush()
            add_audit(
                db,
                acao="bootstrap.executado",
                entidade="users",
                registro_id=user.id,
                usuario_id=user.id,
                valores_posteriores={
                    "email": user.email,
                    "is_superuser": True,
                    "exige_troca_senha": True,
                    "perfil": PLATFORM_SUPERUSER_KEY,
                },
            )
            add_audit(
                db,
                acao="usuario_ilpi_perfil.criado",
                entidade="usuario_ilpi_perfis",
                registro_id=link.id,
                usuario_id=user.id,
                valores_posteriores={"usuario_id": user.id, "perfil_id": profile.id, "ilpi_id": None},
            )
            transition_state(db, state, PLATFORM_BOOTSTRAPPED, usuario_id=user.id)
            await db.commit()
            return BootstrapResult(user.id, user.email, temporary_password, PLATFORM_BOOTSTRAPPED)
        except BootstrapFailure:
            await db.rollback()
            raise
        except HTTPException as error:
            await db.rollback()
            detail = error.detail if isinstance(error.detail, dict) else {}
            raise BootstrapFailure(
                str(detail.get("code") or "BOOTSTRAP_CONFLICT"),
                str(detail.get("message") or "Bootstrap não permitido"),
            ) from error
        except IntegrityError as error:
            await db.rollback()
            raise BootstrapFailure("BOOTSTRAP_CONFLICT", "Bootstrap concorrente ou duplicado") from error


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa bootstrap seguro do FáciLPI")
    parser.add_argument("--token", dest="token", default=None)
    # PLATFORM-2: a senha inicial do operador da plataforma e a credencial mais
    # poderosa do sistema. Imprimi-la sempre a levava para o log do runner de
    # deploy, que costuma ser retido e compartilhado. Agora a exibicao e um pedido
    # explicito de quem executa.
    parser.add_argument(
        "--show-password",
        dest="show_password",
        action="store_true",
        help="Exibe a senha temporária inicial no terminal (dado sensível).",
    )
    return parser.parse_args()


def _provided_token(args: argparse.Namespace) -> str | None:
    if args.token:
        return args.token
    env_input = os.getenv("BOOTSTRAP_TOKEN_INPUT")
    if env_input:
        return env_input
    return getpass.getpass("BOOTSTRAP_TOKEN: ")


def main() -> int:
    args = _parse_args()
    try:
        result = asyncio.run(run_bootstrap(_provided_token(args)))
    except BootstrapFailure as error:
        print(f"BLOCKED_BOOTSTRAP: {error.code}: {error}")
        return 1

    print("BOOTSTRAP_OK")
    print(f"email={result.email}")
    print(f"estado={result.state}")
    if args.show_password:
        print(f"senha_temporaria={result.temporary_password}")
        print("ATENCAO: dado sensivel, exibido uma unica vez. Nao fica gravado.")
    else:
        # O bootstrap e one-shot por banco: nao ha como repeti-lo para recuperar a
        # senha. Dizer isso aqui e mais util do que deixar o operador descobrir
        # depois — so o hash existe no banco.
        print("senha_temporaria=NAO_EXIBIDA")
        print(
            "A senha inicial NAO foi exibida e NAO pode ser recuperada: apenas o "
            "hash existe no banco. Para obte-la, o bootstrap precisa ser executado "
            "com --show-password em um banco ainda nao inicializado."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
