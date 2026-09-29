"""Camada Operacional, Fase 4 (#125): passagem de plantao persistida.

A passagem e o REGISTRO do que foi comunicado na troca de turno, nao fonte de
fatos clinicos:
- a parte automatica e montada pelo SERVIDOR (nunca aceita do cliente) a partir
  das fontes reais e do RBAC de quem entrega: alertas/pendencias da projecao,
  intercorrencias abertas, atividades (cuidados e doses) nao concluidas na
  janela do plantao e ausencias ativas — recortada pelos residentes da area;
- a parte manual sao observacoes curtas (ate 280 caracteres) com categoria e
  residente opcional — nao e prontuario paralelo;
- quem recebe ve cada item com a situacao ATUAL da fonte (ainda aberto /
  resolvido desde entao), filtrado pela leitura de origem DELE, e confirma o
  recebimento. Quem entregou nao confirma o proprio recebimento.
Tenant sempre da sessao; 404 cross-tenant; toda mutacao auditada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .alertas import HORAS_JANELA_PLANTAO, ORIGEM_DA_REGRA, projetar
from .audit import add_audit
from .operacao import _encerrar_plantao, _responsabilidades, _travar_plantao, funcionario_da_sessao, residentes_das_areas
from .rotina import _has_admin_vigente, _has_execucao_vigente, _utc, meu_plantao
from .security import (PERMISSION_DENIED, RESOURCE_NOT_FOUND, SecurityContext, allowed_permission_keys,
                       require_ilpi_context, require_permission)

passagens_router = APIRouter(prefix="/passagens", tags=["passagens"], dependencies=[Depends(require_ilpi_context)])

PASSAGEM_CONFLITO = "PASSAGEM_CONFLITO"
HORAS_JANELA_SEM_PLANTAO = 12
# Cuidados e doses entram como ATIVIDADE (item a item, com horario); o alerta agregado repetiria.
REGRAS_COBERTAS_POR_ATIVIDADE = {"cuidados_sem_registro", "doses_sem_registro"}
Categoria = Literal["assistencial", "comportamento", "familia_visitas", "estrutura_materiais", "outro"]
Origem = Literal["alerta", "intercorrencia", "atividade", "ausencia", "observacao"]
AUSENCIA = {"hospitalizacao": "Hospitalização", "saida_temporaria": "Saída temporária"}
TITULO_MAX = 255  # passagem_itens.titulo
LIMITE_ATIVIDADES = 5000
# Regras que sao a mesma situacao em outro estagio: o documento que vencia e agora venceu continua aberto.
FAMILIA_DA_REGRA = {"documento_vencendo": "documento_validade", "documento_vencido": "documento_validade"}


# Alertas cuja fonte e um registro com situacao propria: a situacao atual vem da FONTE, nao do id do
# alerta (a gravidade da intercorrencia pode ser corrigida e o alerta trocar de regra, seguindo aberta).
FONTE_DO_ALERTA = {**{r: "intercorrencia" for r in ORIGEM_DA_REGRA if r.startswith("intercorrencia_")},
                   "ausencia_prolongada": "ausencia"}
LOTE_IN = 1000  # asyncpg aceita ate 32767 parametros por consulta


def _familia(regra: Optional[str]) -> str:
    return FAMILIA_DA_REGRA.get(regra or "", regra or "")


def _regras_da_familia(regra: Optional[str]) -> set[str]:
    familia = _familia(regra)
    return {r for r in ORIGEM_DA_REGRA if _familia(r) == familia}


class Observacao(BaseModel):
    categoria: Categoria
    residente_id: Optional[str] = None
    texto: str = Field(..., min_length=1, max_length=280)

    @field_validator("texto")
    @classmethod
    def _texto(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Escreva a observação")
        return v


class Entregar(BaseModel):
    area_id: Optional[str] = None
    observacoes: list[Observacao] = Field(default_factory=list, max_length=20)
    encerrar_plantao: bool = False


class ItemPassagem(BaseModel):
    id: Optional[str] = None
    origem: Origem
    alerta_id: Optional[str] = None
    regra: Optional[str] = None
    referencia_id: Optional[str] = None
    residente_id: Optional[str] = None
    residente_nome: Optional[str] = None
    gravidade: Optional[str] = None
    natureza: Optional[str] = None
    titulo: str
    previsto_em: Optional[datetime] = None
    categoria: Optional[Categoria] = None
    texto: Optional[str] = None
    # Situacao ATUAL da fonte para quem consulta (nulo em observacao).
    situacao_atual: Optional[Literal["aberto", "resolvido"]] = None


class Previa(BaseModel):
    area_id: Optional[str] = None
    area_nome: Optional[str] = None
    janela_inicio: datetime
    janela_fim: datetime
    itens: list[ItemPassagem]


class PassagemResposta(BaseModel):
    id: str
    area_id: Optional[str] = None
    area_nome: Optional[str] = None
    plantao_id: Optional[str] = None
    janela_inicio: datetime
    janela_fim: datetime
    situacao: Literal["entregue", "recebida"]
    entregue_por_nome: str
    entregue_por_mim: bool
    entregue_em: datetime
    recebida_por_nome: Optional[str] = None
    recebida_em: Optional[datetime] = None
    da_minha_area: bool = False
    itens: list[ItemPassagem]
    # Itens que existem mas cuja origem quem consulta nao le (so a contagem).
    itens_sem_acesso: int = 0


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _nao_encontrado():
    raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})


def _conflito(mensagem: str):
    raise HTTPException(status_code=409, detail={"code": PASSAGEM_CONFLITO, "message": mensagem})


def _negado(mensagem: str):
    raise HTTPException(status_code=403, detail={"code": PERMISSION_DENIED, "message": mensagem})


def _pode_ver(item: dict, chaves: set[str]) -> bool:
    origem = item["origem"]
    if origem == "alerta":
        exige = ORIGEM_DA_REGRA.get(item.get("regra") or "")
        return exige is not None and exige <= chaves
    if origem == "intercorrencia":
        return "intercorrencias:ler" in chaves
    if origem == "atividade":
        # Dose so com permissao de medicacao (#131), como no Meu Plantao e na central.
        return "plantao:ler" in chaves and (item.get("regra") != "medicacao" or "administracoes:ler" in chaves)
    if origem == "ausencia":
        return "ausencias:ler" in chaves
    return True  # observacao: quem le a passagem le o que foi dito


async def _escopo(db, context, area_id, plantao, chaves: set[str]) -> list[tuple[str, str]]:
    """Areas (id, nome) da passagem.

    Sem area informada: TODAS as areas pelas quais a pessoa responde agora (uniao
    dos residentes); sem plantao/responsabilidade, lista vazia = a ILPI, recortada
    pelo RBAC. Area informada: precisa ser uma delas — salvo a coordenacao
    (``escala:gerenciar``), que pode passar a de qualquer area da ILPI.
    """
    minhas = {r.area_id: r.area_nome for r in await _responsabilidades(
        db, context.ilpi_id, plantao_ids=[plantao.id], abertas=True)} if plantao else {}
    if area_id:
        area = (await db.execute(select(m.AreaOperacional).where(
            m.AreaOperacional.id == area_id, m.AreaOperacional.ilpi_id == context.ilpi_id))).scalar_one_or_none()
        if area is None:
            _nao_encontrado()
        if area.id not in minhas and "escala:gerenciar" not in chaves:
            _negado("Você não responde por esta área neste plantão")
        return [(area.id, area.nome)]
    return sorted(minhas.items(), key=lambda a: (a[1], a[0]))


def _area_unica(areas: list[tuple[str, str]]) -> tuple[Optional[str], Optional[str]]:
    """Previa: uma area e ela; varias saem juntas (nomes unidos) — a entrega gera uma passagem por area."""
    if not areas:
        return None, None
    if len(areas) == 1:
        return areas[0]
    return None, ", ".join(nome for _, nome in areas)


async def _plantao_ativo(db, context, funcionario) -> Optional[m.Plantao]:
    if funcionario is None:
        return None
    return (await db.execute(select(m.Plantao).where(
        m.Plantao.ilpi_id == context.ilpi_id, m.Plantao.funcionario_id == funcionario.id,
        m.Plantao.situacao == "em_andamento"))).scalar_one_or_none()


async def montar_previa(db: AsyncSession, context: SecurityContext, areas: list[tuple[str, str]],
                        janela_inicio: datetime, agora: datetime) -> list[dict]:
    """Parte automatica, so com dados reais e o RBAC de quem entrega."""
    chaves = set(await allowed_permission_keys(db, context))
    escopo: Optional[set[str]] = None
    if areas:
        por_area = await residentes_das_areas(db, context.ilpi_id, [a for a, _ in areas])
        escopo = {r for residentes in por_area.values() for r in residentes}
    no_escopo = (lambda r: r is not None and r in escopo) if escopo is not None else (lambda r: True)
    itens: list[dict] = []

    com_alerta: set[str] = set()
    ausencias_com_alerta: set[str] = set()
    proj_itens = (await projetar(db, context)).itens if "alertas:ler" in chaves else []
    for a in proj_itens:
        if a["regra"] in REGRAS_COBERTAS_POR_ATIVIDADE or not no_escopo(a["residente_id"]):
            continue
        itens.append({"origem": "alerta", "alerta_id": a["id"], "regra": a["regra"], "referencia_id": a["referencia_id"],
                      "residente_id": a["residente_id"], "gravidade": a["gravidade"], "natureza": a["natureza"],
                      "titulo": a["titulo"], "previsto_em": a["prazo"]})
        if a["regra"].startswith("intercorrencia_"):
            com_alerta.add(a["referencia_id"])
        if a["regra"] == "ausencia_prolongada":
            ausencias_com_alerta.add(a["referencia_id"])

    if "intercorrencias:ler" in chaves:
        # Direto da fonte (sem teto): toda intercorrencia aberta do escopo que ainda nao veio como alerta.
        for x in (await db.scalars(select(m.Intercorrencia).where(
                m.Intercorrencia.ilpi_id == context.ilpi_id, m.Intercorrencia.situacao == "aberta")
                .order_by(m.Intercorrencia.ocorrido_em.desc(), m.Intercorrencia.id))).all():
            if no_escopo(x.residente_id) and x.id not in com_alerta:
                itens.append({"origem": "intercorrencia", "referencia_id": x.id, "residente_id": x.residente_id,
                              "titulo": f"Intercorrência aberta: {x.tipo}"})

    if "plantao:ler" in chaves:
        # Mesma projecao do Meu Plantao. Atividades: a janela de 24 h do alerta que elas substituem
        # (o que o turno herdou e segue pendente tambem passa adiante), nunca menor que a do plantao.
        pendencias = await meu_plantao(a_partir_de=min(janela_inicio, agora - timedelta(hours=HORAS_JANELA_PLANTAO)),
                                       ate=agora, residente_id=None, limit=LIMITE_ATIVIDADES, db=db, context=context)
        for p in pendencias:
            if p["origem"] == "intercorrencia" or not no_escopo(p["residente_id"]):
                continue
            rotulo = "Cuidado sem registro" if p["origem"] == "cuidado" else "Dose de medicação sem registro"
            itens.append({"origem": "atividade", "regra": p["origem"], "referencia_id": p["registro_id"],
                          "residente_id": p["residente_id"], "previsto_em": p["previsto_em"],
                          "titulo": f"{rotulo}: {p['descricao']}" if p["origem"] == "cuidado" else rotulo})

    if "ausencias:ler" in chaves:
        for a in (await db.scalars(select(m.Ausencia).where(
                m.Ausencia.instituicao_id == context.ilpi_id, m.Ausencia.data_fim.is_(None))
                .order_by(m.Ausencia.data_inicio, m.Ausencia.id))).all():
            if no_escopo(a.residente_id) and a.id not in ausencias_com_alerta:
                itens.append({"origem": "ausencia", "referencia_id": a.id, "residente_id": a.residente_id,
                              "titulo": f"{AUSENCIA.get(a.tipo, 'Ausência')} em andamento", "previsto_em": _utc(a.data_inicio)})
    for item in itens:
        item["titulo"] = item["titulo"][:TITULO_MAX]
    return itens


async def _em_lotes(db, consulta, coluna, ids: set[str]) -> set[str]:
    """Ids de ``ids`` que a consulta devolve, em lotes (sem estourar o limite de parametros)."""
    lista, achados = sorted(ids), set()
    for inicio in range(0, len(lista), LOTE_IN):
        achados |= set((await db.scalars(consulta.where(coluna.in_(lista[inicio:inicio + LOTE_IN])))).all())
    return achados


async def _situacao_atual(db, context, itens: list[dict]) -> None:
    """Status ATUAL de cada fonte para quem consulta (mesma projecao, mesmas fontes)."""
    if not itens:
        return
    ilpi = context.ilpi_id
    ids_alerta: set[str] = set()
    chaves_alerta: set[tuple[str, str]] = set()
    confiaveis: set[str] = set()
    if any(i["origem"] == "alerta" for i in itens):
        proj = await projetar(db, context)
        ids_alerta = {a["id"] for a in proj.itens}
        # Mesma situacao com outro id (etapa/estagio mudou): continua aberta.
        chaves_alerta = {(_familia(a["regra"]), a["referencia_id"]) for a in proj.itens}
        # Sem leitura da origem ou com teto atingido, a ausencia do alerta nao prova que resolveu.
        confiaveis = proj.avaliadas - proj.truncadas
    por_origem: dict[str, set[str]] = {}
    for i in itens:
        if i.get("referencia_id"):
            chave = FONTE_DO_ALERTA.get(i.get("regra") or "") if i["origem"] == "alerta" else None
            chave = f"{chave}:" if chave else i["origem"] + ":" + (i.get("regra") or "")
            por_origem.setdefault(chave, set()).add(i["referencia_id"])
    abertas_inter = await _em_lotes(db, select(m.Intercorrencia.id).where(
        m.Intercorrencia.ilpi_id == ilpi, m.Intercorrencia.situacao == "aberta"),
        m.Intercorrencia.id, por_origem.get("intercorrencia:", set()))
    cuidados_pendentes = await _em_lotes(db, select(m.OcorrenciaCuidado.id).where(
        m.OcorrenciaCuidado.ilpi_id == ilpi, m.OcorrenciaCuidado.situacao == "prevista", ~_has_execucao_vigente()),
        m.OcorrenciaCuidado.id, por_origem.get("atividade:cuidado", set()))
    doses_pendentes = await _em_lotes(db, select(m.DosePrevista.id).where(
        m.DosePrevista.ilpi_id == ilpi, m.DosePrevista.situacao == "prevista", ~_has_admin_vigente()),
        m.DosePrevista.id, por_origem.get("atividade:medicacao", set()))
    ausencias_abertas = await _em_lotes(db, select(m.Ausencia.id).where(
        m.Ausencia.instituicao_id == ilpi, m.Ausencia.data_fim.is_(None)),
        m.Ausencia.id, por_origem.get("ausencia:", set()))
    for i in itens:
        origem, ref = i["origem"], i.get("referencia_id")
        if origem == "observacao":
            i["situacao_atual"] = None
            continue
        fonte = FONTE_DO_ALERTA.get(i.get("regra") or "") if origem == "alerta" else None
        if fonte is not None:
            aberto = ref in (abertas_inter if fonte == "intercorrencia" else ausencias_abertas)
            i["situacao_atual"] = "aberto" if aberto else "resolvido"
            continue
        if origem == "alerta":
            if i.get("alerta_id") in ids_alerta or (_familia(i.get("regra")), ref) in chaves_alerta:
                i["situacao_atual"] = "aberto"
            elif _regras_da_familia(i.get("regra")) <= confiaveis:
                i["situacao_atual"] = "resolvido"
            else:
                i["situacao_atual"] = None  # nao da para afirmar
            continue
        aberto = {
            "intercorrencia": ref in abertas_inter,
            "atividade": ref in (cuidados_pendentes if i.get("regra") == "cuidado" else doses_pendentes),
            "ausencia": ref in ausencias_abertas,
        }[origem]
        i["situacao_atual"] = "aberto" if aberto else "resolvido"


async def _nomes_residentes(db, context, chaves, itens) -> None:
    ids = {i["residente_id"] for i in itens if i.get("residente_id")}
    nomes = {}
    if ids and "residentes:ler" in chaves:
        nomes = dict((await db.execute(select(m.Residente.id, m.Residente.nome).where(
            m.Residente.instituicao_id == context.ilpi_id, m.Residente.id.in_(ids)))).all())
    for i in itens:
        i["residente_nome"] = nomes.get(i.get("residente_id"))


@passagens_router.get("/previa", response_model=Previa)
async def previa(area_id: Optional[str] = None, db: AsyncSession = Depends(get_db),
                 context: SecurityContext = Depends(require_permission("passagem_plantao:registrar"))):
    agora = _agora()
    chaves = set(await allowed_permission_keys(db, context))
    funcionario = await funcionario_da_sessao(db, context)
    plantao = await _plantao_ativo(db, context, funcionario)
    areas = await _escopo(db, context, area_id, plantao, chaves)
    inicio = _utc(plantao.inicio_em) if plantao else agora - timedelta(hours=HORAS_JANELA_SEM_PLANTAO)
    itens = await montar_previa(db, context, areas, inicio, agora)
    await _nomes_residentes(db, context, chaves, itens)
    area_id_unica, area_nome = _area_unica(areas)
    return Previa(area_id=area_id_unica, area_nome=area_nome,
                  janela_inicio=inicio, janela_fim=agora, itens=[ItemPassagem(**i) for i in itens])


async def _por_area(db, ilpi, areas, automaticos: list[dict], manuais: list[dict]) -> list[tuple[Optional[str], list[dict]]]:
    """Uma passagem por area: cada proximo turno confirma a SUA (o leito esta em no maximo uma area ativa).

    Itens automaticos seguem o residente; observacao sobre residente da area vai para ela, observacao
    geral (ou de residente fora das areas) vai para todas.
    """
    if len(areas) <= 1:
        return [(areas[0][0] if areas else None, automaticos + manuais)]
    area_de = {r: area for area, residentes in (await residentes_das_areas(db, ilpi, [a for a, _ in areas])).items()
               for r in residentes}
    grupos: dict[str, list[dict]] = {a: [] for a, _ in areas}
    primeira = areas[0][0]
    for item in automaticos:
        # Residente que trocou de leito entre as duas leituras: fica na primeira area (nunca 500).
        grupos[area_de.get(item["residente_id"], primeira)].append(item)
    for item in manuais:
        destino = area_de.get(item.get("residente_id"))
        for area_id in ([destino] if destino else list(grupos)):
            grupos[area_id].append(item)
    return list(grupos.items())


@passagens_router.post("/", response_model=list[PassagemResposta], status_code=201)
async def entregar(payload: Entregar, request: Request, db: AsyncSession = Depends(get_db),
                   context: SecurityContext = Depends(require_permission("passagem_plantao:registrar"))):
    ilpi = context.ilpi_id
    agora = _agora()
    chaves = set(await allowed_permission_keys(db, context))
    if payload.encerrar_plantao and "plantao:registrar" not in chaves:
        _negado("Encerrar o plantão exige permissão para registrar plantão")
    funcionario = await funcionario_da_sessao(db, context)
    plantao = await _plantao_ativo(db, context, funcionario)
    areas = await _escopo(db, context, payload.area_id, plantao, chaves)
    residentes_obs = {o.residente_id for o in payload.observacoes if o.residente_id}
    if residentes_obs:
        existentes = set((await db.scalars(select(m.Residente.id).where(
            m.Residente.instituicao_id == ilpi, m.Residente.id.in_(residentes_obs)))).all())
        if existentes != residentes_obs:
            _nao_encontrado()
    inicio = _utc(plantao.inicio_em) if plantao else agora - timedelta(hours=HORAS_JANELA_SEM_PLANTAO)
    automaticos = await montar_previa(db, context, areas, inicio, agora)
    manuais = [{"origem": "observacao", "residente_id": o.residente_id, "categoria": o.categoria, "texto": o.texto,
                "titulo": o.texto[:TITULO_MAX]} for o in payload.observacoes]
    campos = ("origem", "alerta_id", "regra", "referencia_id", "residente_id", "gravidade", "natureza", "titulo",
              "previsto_em", "categoria", "texto")
    passagens = []
    for area_id, itens in await _por_area(db, ilpi, areas, automaticos, manuais):
        passagem = m.PassagemPlantao(
            ilpi_id=ilpi, plantao_id=plantao.id if plantao else None, area_id=area_id,
            janela_inicio=inicio, janela_fim=agora, situacao="entregue", entregue_por=context.user.id,
            entregue_por_funcionario_id=funcionario.id if funcionario else None, entregue_em=agora)
        db.add(passagem)
        await db.flush()
        for ordem, item in enumerate(itens):
            db.add(m.PassagemItem(ilpi_id=ilpi, passagem_id=passagem.id, ordem=ordem,
                                  **{c: item.get(c) for c in campos}))
        add_audit(db, acao="passagens_plantao.entregar", entidade="passagens_plantao", registro_id=passagem.id,
                  usuario_id=context.user.id, ilpi_id=ilpi,
                  valores_posteriores={"area_id": area_id, "plantao_id": passagem.plantao_id,
                                       "itens_automaticos": sum(i["origem"] != "observacao" for i in itens),
                                       "observacoes": sum(i["origem"] == "observacao" for i in itens)},
                  request=request)
        passagens.append(passagem)
    if payload.encerrar_plantao and plantao is not None:
        plantao = await _travar_plantao(db, ilpi, plantao.id)
        if plantao.situacao == "em_andamento":
            await _encerrar_plantao(db, context, request, plantao)
    await db.commit()
    return await _respostas(db, context, passagens)


async def _respostas(db, context, passagens: list[m.PassagemPlantao]) -> list[PassagemResposta]:
    if not passagens:
        return []
    ilpi = context.ilpi_id
    chaves = set(await allowed_permission_keys(db, context))
    ids = [p.id for p in passagens]
    itens_db = (await db.scalars(select(m.PassagemItem).where(
        m.PassagemItem.ilpi_id == ilpi, m.PassagemItem.passagem_id.in_(ids))
        .order_by(m.PassagemItem.passagem_id, m.PassagemItem.ordem))).all()
    por_passagem: dict[str, list[dict]] = {i: [] for i in ids}
    sem_acesso: dict[str, int] = {i: 0 for i in ids}
    for it in itens_db:
        item = {c: getattr(it, c) for c in ("id", "origem", "alerta_id", "regra", "referencia_id", "residente_id",
                                            "gravidade", "natureza", "titulo", "previsto_em", "categoria", "texto")}
        item["previsto_em"] = _utc(item["previsto_em"])
        if _pode_ver(item, chaves):
            por_passagem[it.passagem_id].append(item)
        else:
            sem_acesso[it.passagem_id] += 1
    todos = [i for lista in por_passagem.values() for i in lista]
    await _situacao_atual(db, context, todos)
    await _nomes_residentes(db, context, chaves, todos)
    usuarios = {p.entregue_por for p in passagens} | {p.recebida_por for p in passagens if p.recebida_por}
    nomes = dict((await db.execute(select(m.User.id, m.User.nome).where(m.User.id.in_(usuarios)))).all())
    nomes.update(dict((await db.execute(select(m.Funcionario.usuario_id, m.Funcionario.nome).where(
        m.Funcionario.ilpi_id == ilpi, m.Funcionario.usuario_id.in_(usuarios)))).all()))
    areas = dict((await db.execute(select(m.AreaOperacional.id, m.AreaOperacional.nome).where(
        m.AreaOperacional.ilpi_id == ilpi, m.AreaOperacional.id.in_({p.area_id for p in passagens if p.area_id})))).all())
    funcionario = await funcionario_da_sessao(db, context)
    plantao = await _plantao_ativo(db, context, funcionario)
    minhas_areas = {r.area_id for r in await _responsabilidades(db, ilpi, plantao_ids=[plantao.id], abertas=True)} if plantao else set()
    return [PassagemResposta(
        id=p.id, area_id=p.area_id, area_nome=areas.get(p.area_id), plantao_id=p.plantao_id,
        janela_inicio=_utc(p.janela_inicio), janela_fim=_utc(p.janela_fim), situacao=p.situacao,
        entregue_por_nome=nomes.get(p.entregue_por, ""), entregue_por_mim=p.entregue_por == context.user.id,
        entregue_em=_utc(p.entregue_em), recebida_por_nome=nomes.get(p.recebida_por) if p.recebida_por else None,
        recebida_em=_utc(p.recebida_em), da_minha_area=p.area_id is not None and p.area_id in minhas_areas,
        itens=[ItemPassagem(**i) for i in por_passagem[p.id]], itens_sem_acesso=sem_acesso[p.id]) for p in passagens]


@passagens_router.get("/", response_model=list[PassagemResposta])
async def listar(situacao: Literal["entregue", "recebida", "todas"] = "entregue", limit: int = Query(20, ge=1, le=100),
                 db: AsyncSession = Depends(get_db),
                 context: SecurityContext = Depends(require_permission("passagem_plantao:ler"))):
    consulta = select(m.PassagemPlantao).where(m.PassagemPlantao.ilpi_id == context.ilpi_id)
    if situacao != "todas":
        consulta = consulta.where(m.PassagemPlantao.situacao == situacao)
    passagens = (await db.scalars(consulta.order_by(m.PassagemPlantao.entregue_em.desc(), m.PassagemPlantao.id)
                                  .limit(limit))).all()
    return await _respostas(db, context, list(passagens))


@passagens_router.get("/{passagem_id}", response_model=PassagemResposta)
async def detalhe(passagem_id: str, db: AsyncSession = Depends(get_db),
                  context: SecurityContext = Depends(require_permission("passagem_plantao:ler"))):
    passagem = (await db.execute(select(m.PassagemPlantao).where(
        m.PassagemPlantao.id == passagem_id, m.PassagemPlantao.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if passagem is None:
        _nao_encontrado()
    return (await _respostas(db, context, [passagem]))[0]


@passagens_router.post("/{passagem_id}/receber", response_model=PassagemResposta)
async def receber(passagem_id: str, request: Request, db: AsyncSession = Depends(get_db),
                  context: SecurityContext = Depends(require_permission("passagem_plantao:registrar"))):
    passagem = (await db.execute(select(m.PassagemPlantao).where(
        m.PassagemPlantao.id == passagem_id, m.PassagemPlantao.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if passagem is None:
        _nao_encontrado()
    if passagem.situacao != "entregue":
        _conflito("Esta passagem já foi recebida")
    if passagem.entregue_por == context.user.id:
        _conflito("Quem entregou não confirma o próprio recebimento")
    ilpi, uid = context.ilpi_id, context.user.id
    funcionario = await funcionario_da_sessao(db, context)
    agora = _agora()
    # Condicional: se outra pessoa confirmou nesse meio-tempo, esta recebe 409 (nunca sobrescreve).
    resultado = await db.execute(
        update(m.PassagemPlantao).where(m.PassagemPlantao.id == passagem_id, m.PassagemPlantao.ilpi_id == ilpi,
                                        m.PassagemPlantao.situacao == "entregue")
        .values(situacao="recebida", recebida_por=uid, recebida_em=agora,
                recebida_por_funcionario_id=funcionario.id if funcionario else None)
        .execution_options(synchronize_session=False))
    if resultado.rowcount != 1:
        await db.rollback()
        _conflito("Esta passagem já foi recebida")
    add_audit(db, acao="passagens_plantao.receber", entidade="passagens_plantao", registro_id=passagem_id,
              usuario_id=uid, ilpi_id=ilpi, valores_anteriores={"situacao": "entregue"},
              valores_posteriores={"situacao": "recebida"}, request=request)
    await db.commit()
    passagem = (await db.execute(select(m.PassagemPlantao).where(
        m.PassagemPlantao.id == passagem_id, m.PassagemPlantao.ilpi_id == ilpi)
        .execution_options(populate_existing=True))).scalar_one()
    return (await _respostas(db, context, [passagem]))[0]
