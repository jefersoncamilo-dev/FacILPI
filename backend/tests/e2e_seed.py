"""Seed sintetico do E2E Playwright (frontend/e2e). Banco DISPOSABLE_TEST apenas.

Uso: python -m tests.e2e_seed <diretorio-temporario>

O diretorio e criado pelo setup do Playwright fora do repositorio; o banco
SQLite fica dentro dele e passa pelos mesmos guards da suite
(`db_safety.register_temp_root` + `run_alembic`). A senha das contas vem de
E2E_PASSWORD, gerada a cada execucao e nunca gravada: o `seed.json` de saida
leva so ids, nomes e e-mails.

O cenario e montado pela API em processo (mesmo caminho de validacao dos
testes), com sessao de teste; o navegador depois entra pela tela de login.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx

ALVO = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if ALVO is None:
    raise SystemExit("uso: python -m tests.e2e_seed <diretorio-temporario>")

from tests import db_safety  # noqa: E402

db_safety.register_temp_root(ALVO)
DB_PATH = db_safety.validate_sqlite_path(ALVO / "e2e.db")
DB_URL = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["DATABASE_URL"] = DB_URL

SENHA = os.environ.get("E2E_PASSWORD")
if not SENHA or len(SENHA) < 16:
    raise SystemExit("E2E_PASSWORD ausente ou curta: o setup do Playwright gera uma por execucao")

from sqlalchemy import select  # noqa: E402

from src import main  # noqa: E402
from src.application.auth import hash_password  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from src.infrastructure.database import SessionLocal  # noqa: E402
from tests.sessao_teste import abrir_sessao, token_de  # noqa: E402

RESIDENTE_A = "Maria Sintética E2E"
RESIDENTE_B = "Joana Outra ILPI E2E"
RESIDENTE_ADMISSAO = "Ana Em Admissão E2E"
INTERVENCAO = "Banho assistido E2E"
MEDICAMENTO = "Medicamento Sintético E2E"
AREA = "Ala E2E"


def _id() -> str:
    return str(uuid.uuid4())


def _ok(resposta: httpx.Response, status: int = 200) -> dict:
    assert resposta.status_code == status, f"{resposta.request.url}: {resposta.status_code} {resposta.text}"
    return resposta.json()


async def _permissoes_institucionais(db) -> set[str]:
    """Uniao dos templates institucionais de head: o gestor E2E percorre todas as telas."""
    return set((await db.scalars(
        select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
        .join(m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id)
        .where(m.Perfil.ilpi_id.is_(None), m.Perfil.escopo == "ilpi"))).all())


async def _perfil(db, ilpi, chaves, sufixo):
    perfil = m.Perfil(id=_id(), ilpi_id=ilpi.id, nome="Gestão E2E", chave=f"gestao_e2e_{sufixo.lower()}",
                      escopo="ilpi", situacao="ativo")
    db.add(perfil)
    await db.flush()
    for permissao in (await db.scalars(select(m.Permissao).where(m.Permissao.chave.in_(chaves)))).all():
        db.add(m.PerfilPermissao(perfil_id=perfil.id, permissao_id=permissao.id))
    await db.flush()
    return perfil


async def _usuario(db, ilpi, perfil, nome, email):
    user = m.User(id=_id(), nome=nome, email=email,
                  password_hash=hash_password(SENHA), ativo=True, exige_troca_senha=False)
    db.add(user)
    await db.flush()
    db.add_all([
        m.Funcionario(id=_id(), ilpi_id=ilpi.id, usuario_id=user.id, nome=user.nome, email=user.email, situacao="ativo"),
        m.UsuarioIlpiPerfil(id=_id(), usuario_id=user.id, perfil_id=perfil.id, ilpi_id=ilpi.id, situacao="ativo",
                            data_inicial=datetime.now(timezone.utc) - timedelta(minutes=1)),
    ])
    await db.flush()
    await abrir_sessao(db, user)
    return user


def _h(user, ilpi) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_de(user)}", "X-Scope": "ilpi", "X-ILPI-ID": ilpi.id}


async def _cenario() -> dict:
    agora = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        chaves = await _permissoes_institucionais(db)
        assert "residentes:ler" in chaves and "passagem_plantao:ler" in chaves, "templates institucionais ausentes"
        ilpi_a = m.Instituicao(id=_id(), razao_social="ILPI Sintética A", situacao="ATIVA")
        ilpi_b = m.Instituicao(id=_id(), razao_social="ILPI Sintética B", situacao="ATIVA")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        perfil_a = await _perfil(db, ilpi_a, chaves, "A")
        perfil_b = await _perfil(db, ilpi_b, chaves, "B")
        gestor_a = await _usuario(db, ilpi_a, perfil_a, "Gestora E2E A", "gestora-a@example.com")
        # Quem recebe a passagem: outra pessoa da mesma ILPI.
        colega_a = await _usuario(db, ilpi_a, perfil_a, "Enfermeira E2E A", "enfermeira-a@example.com")
        gestor_b = await _usuario(db, ilpi_b, perfil_b, "Gestora E2E B", "gestora-b@example.com")
        maria = m.Residente(id=_id(), instituicao_id=ilpi_a.id, nome=RESIDENTE_A, situacao="Ativo",
                            data_nascimento=date(1940, 5, 1))
        joana = m.Residente(id=_id(), instituicao_id=ilpi_b.id, nome=RESIDENTE_B, situacao="Ativo",
                            data_nascimento=date(1938, 2, 3))
        ana = m.Residente(id=_id(), instituicao_id=ilpi_a.id, nome=RESIDENTE_ADMISSAO, situacao="Em admissao",
                          data_nascimento=date(1942, 7, 9))
        revisor = m.Funcionario(id=_id(), ilpi_id=ilpi_a.id, nome="Enfermeira Revisora E2E", situacao="ativo")
        db.add_all([maria, joana, ana, revisor])
        await db.commit()

    transporte = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://e2e") as c:
        h = _h(gestor_a, ilpi_a)
        admissao = _ok(await c.post("/api/admissoes/", headers=h, json={"residente_id": ana.id}), 201)

        pid = _ok(await c.post("/api/planos-cuidados/", headers=h, json={
            "residente_id": maria.id, "data_inicial": agora.date().isoformat(), "objetivos": "Plano E2E"}), 201)["id"]
        _ok(await c.patch(f"/api/planos-cuidados/{pid}", headers=h, json={"situacao": "em_elaboracao"}))
        _ok(await c.post(f"/api/planos-cuidados/{pid}/necessidades", headers=h,
                         json={"descricao": "Higiene", "origem": "manual"}), 201)
        _ok(await c.post(f"/api/planos-cuidados/{pid}/metas", headers=h, json={"descricao": "Manter higiene"}), 201)
        iid = _ok(await c.post(f"/api/planos-cuidados/{pid}/intervencoes", headers=h,
                               json={"descricao": INTERVENCAO, "frequencia": "diaria"}), 201)["id"]
        _ok(await c.post(f"/api/planos-cuidados/{pid}/revisar", headers=h, json={"funcionario_id": revisor.id}))
        _ok(await c.post(f"/api/planos-cuidados/{pid}/aprovar", headers=h, json={"funcionario_id": revisor.id}))
        _ok(await c.post(f"/api/planos-cuidados/{pid}/ativar", headers=h))
        _ok(await c.post("/api/programacoes-cuidado/", headers=h, json={
            "plano_id": pid, "intervencao_id": iid, "horarios": ["08:00", "20:00"], "timezone": "America/Sao_Paulo",
            "vigencia_inicio": (agora - timedelta(hours=1)).isoformat(), "prioridade": "alta"}), 201)

        med = _ok(await c.post("/api/medicamentos/", headers=h, json={"nome": MEDICAMENTO, "unidade": "comprimido"}), 201)
        pre = _ok(await c.post("/api/prescricoes/", headers=h, json={
            "residente_id": maria.id, "medicamento_id": med["id"], "prescritor_nome": "Dra Sintética",
            "prescritor_categoria": "medico", "dose": "1", "unidade": "comprimido", "via": "oral",
            "inicio": agora.date().isoformat()}), 201)
        _ok(await c.post(f"/api/prescricoes/{pre['id']}/ativar", headers=h, json={
            "horarios": ["08:00", "20:00"], "timezone": "America/Sao_Paulo",
            "vigencia_inicio": (agora - timedelta(hours=1)).isoformat()}))

        area = _ok(await c.post("/api/escala/areas", headers=h, json={"nome": AREA, "tipo": "ala"}), 201)
        leito = _ok(await c.post("/api/quartos_leitos/", headers=h, json={"unidade": AREA, "quarto": "1", "leito": "A"}), 201)
        _ok(await c.post(f"/api/quartos_leitos/{leito['id']}/alocar", headers=h, json={"residente_id": maria.id}))
        _ok(await c.post(f"/api/escala/areas/{area['id']}/leitos", headers=h, json={"quarto_leito_id": leito["id"]}), 201)

    return {
        "ilpiA": {"nome": ilpi_a.razao_social, "gestora": {"email": gestor_a.email, "nome": gestor_a.nome},
                  "colega": {"email": colega_a.email, "nome": colega_a.nome}},
        "ilpiB": {"nome": ilpi_b.razao_social, "gestora": {"email": gestor_b.email, "nome": gestor_b.nome}},
        "residenteA": {"id": maria.id, "nome": RESIDENTE_A},
        "residenteB": {"id": joana.id, "nome": RESIDENTE_B},
        "admissaoA": {"id": admissao["id"], "residente": RESIDENTE_ADMISSAO},
        "planoA": {"id": pid, "intervencao": INTERVENCAO},
        "medicamento": MEDICAMENTO,
        "area": AREA,
    }


def main_() -> None:
    migracao = db_safety.run_alembic(DB_URL, "upgrade", "head")
    if migracao.returncode != 0:
        raise SystemExit(f"alembic falhou:\n{migracao.stdout}\n{migracao.stderr}")
    dados = asyncio.run(_cenario())
    (ALVO / "seed.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"seed E2E pronto em {ALVO}")


if __name__ == "__main__":
    main_()
