"""Sessao real para usuarios criados diretamente pelos testes (PH02-05 / #74).

Desde o PR-2 o access token precisa de `sid` — a familia de refresh da sessao —
e `get_current_user` recusa token cuja sessao nao exista ou nao esteja ativa.
Testes que criam o usuario direto no banco e cunham o token sem passar pelo
login abrem aqui uma sessao de verdade, pela mesma `issue_refresh_token` que o
login usa, gravada na sessao do teste (entra no proximo commit dele).

`token_de` falha explicitamente para usuario sem sessao aberta: um token sem
`sid` seria recusado pelo servidor e o teste quebraria longe da causa.
"""

from __future__ import annotations

import uuid

from src.application.auth import create_access_token, issue_refresh_token

_SESSOES: dict[str, str] = {}


async def abrir_sessao(db, user) -> str:
    familia = str(uuid.uuid4())
    await issue_refresh_token(
        db,
        user,
        scope=None,
        ilpi_id=None,
        perfil_id=None,
        token_family=familia,
    )
    _SESSOES[user.id] = familia
    return familia


def token_de(user, **context) -> str:
    familia = _SESSOES.get(user.id)
    if familia is None:
        raise AssertionError(
            f"usuario de teste {user.id} sem sessao aberta: chame "
            "abrir_sessao(db, user) ao cria-lo"
        )
    return create_access_token(user, sid=familia, **context)
