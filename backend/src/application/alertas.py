"""#107: central de alertas do Administrador da ILPI — PROJECAO, so leitura.

Cada alerta e um fato oficial que pede atencao AGORA, calculado a cada
requisicao a partir da fonte que ja governa aquele dado. Nada e gravado:
sem tabela, sem job, sem dual-write. O alerta some sozinho quando o problema
e resolvido na tela de origem. A tabela legada ``alertas`` (001) e o CRUD
``fail_closed`` de /api/alertas/ ficam intocados.

Mesmo contrato do Dashboard (UX-02): a ILPI vem da sessao, nunca do cliente,
e cada regra so e calculada se o contexto le o modulo de origem — sem essa
leitura a regra nao existe para ele (nem contagem, para nao vazar fato
clinico). Os limiares abaixo sao os da decisao do responsavel (26/09) e a tela
os exibe; a janela do plantao e recorte de periodo, nao tolerancia de atraso
(D.2 continua valendo: atrasado e so "passou do horario").
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .rotina import _has_admin_vigente, _has_execucao_vigente, _utc
from .security import SecurityContext, allowed_permission_keys, require_permission

central_alertas_router = APIRouter(prefix="/central-alertas", tags=["alertas"])

DIAS_ADMISSAO_PARADA = 7
DIAS_DOCUMENTO_VENCENDO = 30
DIAS_PAIS_PARADO = 7
HORAS_JANELA_PLANTAO = 24
HORAS_INTERCORRENCIA_PROLONGADA = 24
DIAS_AUSENCIA_PROLONGADA = 7
DIAS_ACESSO_NAO_UTILIZADO = 7
LIMITE_POR_REGRA = 100

FUSO_PADRAO = "America/Sao_Paulo"
RESIDENTE_ATIVO = "Ativo"
ADMISSAO_ENCERRADA = ("concluida", "cancelada", "desistencia")
PAIS_EM_CICLO = ("rascunho", "em_elaboracao", "em_revisao", "aprovado")
ORDEM_GRAVIDADE = {"critico": 0, "atencao": 1, "aviso": 2}

ETAPA = {
    "pre_cadastro": "Pré-cadastro", "triagem": "Triagem", "documentacao": "Documentação",
    "avaliacoes": "Avaliações", "contrato": "Contrato", "quarto_leito": "Quarto e leito", "pais": "PAIS",
}
SITUACAO_PAIS = {"rascunho": "Rascunho", "em_elaboracao": "Em elaboração", "em_revisao": "Em revisão", "aprovado": "Aprovado"}
AUSENCIA = {"hospitalizacao": "Hospitalização", "saida_temporaria": "Saída temporária"}


def _data_br(valor: date) -> str:
    return valor.strftime("%d/%m/%Y")


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


class _Coletor:
    """Junta os alertas de todas as regras, com teto por regra."""

    def __init__(self, nomes: dict[str, str]):
        self.nomes = nomes
        self.itens: list[dict] = []
        self._por_regra: dict[str, int] = defaultdict(int)

    def add(self, regra, categoria, gravidade, titulo, *, referencia, residente_id=None, detalhe=None, desde=None):
        if self._por_regra[regra] >= LIMITE_POR_REGRA:
            return
        self._por_regra[regra] += 1
        self.itens.append({
            "id": f"{regra}:{referencia}",
            "regra": regra,
            "categoria": categoria,
            "gravidade": gravidade,
            "titulo": titulo,
            "detalhe": detalhe,
            "residente_id": residente_id,
            "residente_nome": self.nomes.get(residente_id) if residente_id else None,
            "referencia_id": referencia,
            "desde": _utc(desde) if isinstance(desde, datetime) else None,
        })


async def _hoje(db: AsyncSession, ilpi_id: str, agora: datetime) -> date:
    instituicao = await db.get(m.Instituicao, ilpi_id)
    try:
        fuso = ZoneInfo((instituicao.fuso_horario if instituicao else None) or FUSO_PADRAO)
    except ZoneInfoNotFoundError:
        fuso = ZoneInfo(FUSO_PADRAO)
    return agora.astimezone(fuso).date()


async def _admissoes(db, ilpi, agora, c: _Coletor):
    ultima = (select(m.AdmissaoHistorico.admissao_id, func.max(m.AdmissaoHistorico.created_at).label("em"))
              .where(m.AdmissaoHistorico.ilpi_id == ilpi).group_by(m.AdmissaoHistorico.admissao_id).subquery())
    linhas = (await db.execute(
        select(m.Admissao, ultima.c.em).outerjoin(ultima, ultima.c.admissao_id == m.Admissao.id)
        .where(m.Admissao.ilpi_id == ilpi, m.Admissao.situacao.not_in(ADMISSAO_ENCERRADA))
        .order_by(m.Admissao.iniciada_em, m.Admissao.id)
    )).all()
    limite = agora - timedelta(days=DIAS_ADMISSAO_PARADA)
    for admissao, transicao in linhas:
        desde = _utc(transicao or admissao.iniciada_em)
        if desde is not None and desde < limite:
            dias = (agora - desde).days
            c.add("admissao_parada", "admissao_documentos", "atencao",
                  f"Admissão parada em {ETAPA.get(admissao.situacao, admissao.situacao)}",
                  referencia=admissao.id, residente_id=admissao.residente_id,
                  detalhe=f"Sem avanço há {_plural(dias, 'dia', 'dias')}.", desde=desde)


async def _documentos(db, ilpi, hoje, c: _Coletor):
    docs = (await db.scalars(select(m.Documento).where(m.Documento.instituicao_id == ilpi)
                             .order_by(m.Documento.created_at, m.Documento.id))).all()
    horizonte = hoje + timedelta(days=DIAS_DOCUMENTO_VENCENDO)
    for doc in docs:
        # Mesmo predicado da pendencia da admissao: so a validacao humana cumpre.
        if doc.obrigatorio and doc.situacao != "validado":
            c.add("documento_aguardando_validacao", "admissao_documentos", "atencao",
                  f"Documento obrigatório aguardando validação: {doc.tipo}",
                  referencia=doc.id, residente_id=doc.residente_id, desde=doc.created_at)
        if doc.validade is None:
            continue
        if doc.validade < hoje:
            c.add("documento_vencido", "admissao_documentos", "atencao", f"Documento vencido: {doc.tipo}",
                  referencia=doc.id, residente_id=doc.residente_id, detalhe=f"Venceu em {_data_br(doc.validade)}.")
        elif doc.validade <= horizonte:
            c.add("documento_vencendo", "admissao_documentos", "aviso", f"Documento vence em breve: {doc.tipo}",
                  referencia=doc.id, residente_id=doc.residente_id, detalhe=f"Vence em {_data_br(doc.validade)}.")


async def _avaliacoes(db, ilpi, hoje, c: _Coletor):
    avaliacoes = (await db.scalars(select(m.Avaliacao).where(m.Avaliacao.ilpi_id == ilpi)
                                   .order_by(m.Avaliacao.data, m.Avaliacao.id))).all()
    grupos: dict[tuple, list] = defaultdict(list)
    for a in avaliacoes:
        grupos[(a.residente_id, a.tipo, a.instrumento)].append(a)
    for (residente_id, tipo, instrumento), lista in grupos.items():
        # Vale a regra da admissao: sem validade ou validade >= hoje cumpre.
        if any(a.validade is None or a.validade >= hoje for a in lista):
            continue
        recente = lista[-1]
        nome = " · ".join(x for x in (tipo, instrumento) if x)
        c.add("avaliacao_vencida", "avaliacao_grau_pais", "atencao", f"Avaliação vencida: {nome}",
              referencia=recente.id, residente_id=residente_id, detalhe=f"Venceu em {_data_br(recente.validade)}.")


async def _graus(db, ilpi, hoje, ativos, c: _Coletor):
    graus = {g.residente_id: g for g in (await db.scalars(select(m.GrauDependencia).where(
        m.GrauDependencia.ilpi_id == ilpi, m.GrauDependencia.situacao == "ativo"))).all()}
    for residente_id in ativos:
        grau = graus.get(residente_id)
        if grau is None:
            c.add("grau_ausente", "avaliacao_grau_pais", "atencao", "Sem grau de dependência confirmado",
                  referencia=residente_id, residente_id=residente_id)
        elif grau.validade is not None and grau.validade < hoje:
            c.add("grau_vencido", "avaliacao_grau_pais", "atencao", "Grau de dependência vencido",
                  referencia=grau.id, residente_id=residente_id, detalhe=f"Venceu em {_data_br(grau.validade)}.")


async def _planos(db, ilpi, agora, hoje, ativos, c: _Coletor):
    planos = (await db.scalars(select(m.PlanoCuidados).where(m.PlanoCuidados.ilpi_id == ilpi)
                               .order_by(m.PlanoCuidados.created_at, m.PlanoCuidados.id))).all()
    com_vigente = {p.residente_id for p in planos if p.situacao == "vigente"}
    if ativos is not None:
        for residente_id in ativos:
            if residente_id not in com_vigente:
                c.add("pais_ausente", "avaliacao_grau_pais", "critico", "Sem PAIS vigente",
                      referencia=residente_id, residente_id=residente_id)
    limite = agora - timedelta(days=DIAS_PAIS_PARADO)
    for plano in planos:
        if plano.situacao in PAIS_EM_CICLO:
            mudou = _utc(plano.updated_at or plano.created_at)
            if mudou is not None and mudou < limite:
                c.add("pais_parado", "avaliacao_grau_pais", "aviso",
                      f"PAIS parado em {SITUACAO_PAIS[plano.situacao]}", referencia=plano.id,
                      residente_id=plano.residente_id,
                      detalhe=f"Sem mudança há {_plural((agora - mudou).days, 'dia', 'dias')}.", desde=mudou)
        elif plano.situacao == "vigente" and plano.data_final is not None and plano.data_final < hoje:
            c.add("pais_vencido", "avaliacao_grau_pais", "atencao", "PAIS vigente com prazo encerrado",
                  referencia=plano.id, residente_id=plano.residente_id,
                  detalhe=f"Data final: {_data_br(plano.data_final)}.")


async def _plantao(db, ilpi, agora, c: _Coletor):
    inicio = agora - timedelta(hours=HORAS_JANELA_PLANTAO)
    fontes = (
        ("cuidados_sem_registro", "atencao", m.OcorrenciaCuidado, _has_execucao_vigente, ("cuidado", "cuidados")),
        ("doses_sem_registro", "critico", m.DosePrevista, _has_admin_vigente, ("dose de medicação", "doses de medicação")),
    )
    for regra, gravidade, modelo, registrado, (um, varios) in fontes:
        linhas = (await db.execute(
            select(modelo.residente_id, func.count(), func.min(modelo.previsto_em))
            .where(modelo.ilpi_id == ilpi, modelo.situacao == "prevista",
                   modelo.previsto_em >= inicio, modelo.previsto_em < agora, ~registrado())
            .group_by(modelo.residente_id).order_by(func.min(modelo.previsto_em))
        )).all()
        for residente_id, total, mais_antigo in linhas:
            c.add(regra, "plantao", gravidade, f"{_plural(total, um, varios)} sem registro",
                  referencia=residente_id, residente_id=residente_id,
                  detalhe=f"Horário previsto já passou nas últimas {HORAS_JANELA_PLANTAO} horas.", desde=mais_antigo)


async def _intercorrencias(db, ilpi, agora, c: _Coletor):
    abertas = (await db.scalars(select(m.Intercorrencia).where(
        m.Intercorrencia.ilpi_id == ilpi, m.Intercorrencia.situacao == "aberta",
    ).order_by(m.Intercorrencia.ocorrido_em, m.Intercorrencia.id))).all()
    limite = agora - timedelta(hours=HORAS_INTERCORRENCIA_PROLONGADA)
    for i in abertas:
        ocorrido = _utc(i.ocorrido_em)
        if i.gravidade == "grave":
            c.add("intercorrencia_grave_aberta", "plantao", "critico", f"Intercorrência grave aberta: {i.tipo}",
                  referencia=i.id, residente_id=i.residente_id, desde=ocorrido)
        elif ocorrido is not None and ocorrido < limite:
            c.add("intercorrencia_aberta_prolongada", "plantao", "atencao",
                  f"Intercorrência aberta há mais de {HORAS_INTERCORRENCIA_PROLONGADA} horas: {i.tipo}",
                  referencia=i.id, residente_id=i.residente_id, desde=ocorrido)


async def _leitos(db, ilpi, ativos, c: _Coletor):
    com_leito = set((await db.scalars(select(m.QuartoLeito.residente_atual_id).where(
        m.QuartoLeito.instituicao_id == ilpi, m.QuartoLeito.residente_atual_id.is_not(None)))).all())
    for residente_id in ativos:
        if residente_id not in com_leito:
            c.add("residente_sem_leito", "ocupacao_equipe", "atencao", "Residente ativo sem leito",
                  referencia=residente_id, residente_id=residente_id)


async def _ausencias(db, ilpi, agora, c: _Coletor):
    limite = agora - timedelta(days=DIAS_AUSENCIA_PROLONGADA)
    ausencias = (await db.scalars(select(m.Ausencia).where(
        m.Ausencia.instituicao_id == ilpi, m.Ausencia.data_fim.is_(None), m.Ausencia.data_inicio < limite,
    ).order_by(m.Ausencia.data_inicio, m.Ausencia.id))).all()
    for a in ausencias:
        c.add("ausencia_prolongada", "ocupacao_equipe", "aviso",
              f"{AUSENCIA.get(a.tipo, 'Ausência')} sem retorno há mais de {DIAS_AUSENCIA_PROLONGADA} dias",
              referencia=a.id, residente_id=a.residente_id, detalhe=a.motivo, desde=a.data_inicio)


async def _acessos(db, ilpi, agora, c: _Coletor):
    limite = agora - timedelta(days=DIAS_ACESSO_NAO_UTILIZADO)
    linhas = (await db.execute(
        select(m.Funcionario, func.coalesce(m.User.updated_at, m.User.created_at))
        .join(m.User, m.User.id == m.Funcionario.usuario_id)
        .where(m.Funcionario.ilpi_id == ilpi, m.Funcionario.situacao == "ativo",
               m.User.ativo.is_(True), m.User.exige_troca_senha.is_(True))
        .order_by(m.Funcionario.nome, m.Funcionario.id)
    )).all()
    for funcionario, gerada in linhas:
        gerada = _utc(gerada)
        if gerada is not None and gerada < limite:
            c.add("acesso_nao_utilizado", "ocupacao_equipe", "aviso", f"Acesso ainda não utilizado: {funcionario.nome}",
                  referencia=funcionario.id,
                  detalhe=f"Senha temporária gerada há mais de {DIAS_ACESSO_NAO_UTILIZADO} dias e ainda não trocada.",
                  desde=gerada)


@central_alertas_router.get("/", response_model=s.AlertaGestorResponse)
async def listar_alertas(
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("alertas:ler")),
):
    # PROJECAO: nenhuma linha e criada, alterada ou auditada aqui.
    chaves = set(await allowed_permission_keys(db, context))
    ilpi = context.ilpi_id
    agora = datetime.now(timezone.utc)
    hoje = await _hoje(db, ilpi, agora)

    nomes: dict[str, str] = {}
    ativos: list[str] | None = None
    if "residentes:ler" in chaves:
        residentes = (await db.execute(select(m.Residente.id, m.Residente.nome, m.Residente.situacao)
                                       .where(m.Residente.instituicao_id == ilpi).order_by(m.Residente.nome))).all()
        nomes = {r.id: r.nome for r in residentes}
        ativos = [r.id for r in residentes if r.situacao == RESIDENTE_ATIVO]
    c = _Coletor(nomes)

    if "admissoes:ler" in chaves:
        await _admissoes(db, ilpi, agora, c)
    if "documentos:ler" in chaves:
        await _documentos(db, ilpi, hoje, c)
    if "avaliacoes:ler" in chaves:
        await _avaliacoes(db, ilpi, hoje, c)
    if "grau_dependencia:ler" in chaves and ativos is not None:
        await _graus(db, ilpi, hoje, ativos, c)
    if "planos_cuidados:ler" in chaves:
        await _planos(db, ilpi, agora, hoje, ativos, c)
    if "plantao:ler" in chaves:
        await _plantao(db, ilpi, agora, c)
    if "intercorrencias:ler" in chaves:
        await _intercorrencias(db, ilpi, agora, c)
    if "quartos_leitos:ler" in chaves and ativos is not None:
        await _leitos(db, ilpi, ativos, c)
    if "ausencias:ler" in chaves:
        await _ausencias(db, ilpi, agora, c)
    if "funcionarios:ler" in chaves:
        await _acessos(db, ilpi, agora, c)

    fim_dos_tempos = datetime.max.replace(tzinfo=timezone.utc)
    c.itens.sort(key=lambda a: (ORDEM_GRAVIDADE[a["gravidade"]], a["desde"] or fim_dos_tempos, a["titulo"], a["id"]))
    contagem = {g: 0 for g in ORDEM_GRAVIDADE}
    for item in c.itens:
        contagem[item["gravidade"]] += 1
    return {"gerado_em": agora, "contagem": contagem, "alertas": c.itens}
