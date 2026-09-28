"""Central de alertas e pendencias (#107, #117) — PROJECAO, so leitura.

Cada item e um fato oficial que pede atencao AGORA, calculado a cada
requisicao a partir da fonte que ja governa aquele dado. Nada e gravado:
sem tabela, sem job, sem dual-write. O item some sozinho quando o problema
e resolvido na tela de origem. A tabela legada ``alertas`` (001) e o CRUD
``fail_closed`` de /api/alertas/ ficam intocados.

Mesmo contrato do Dashboard (UX-02): a ILPI vem da sessao, nunca do cliente,
e cada regra so e calculada se o contexto le o modulo de origem — sem essa
leitura a regra nao existe para ele (nem contagem, para nao vazar fato
clinico). ``alertas:ler`` sozinho nao abre nada (RBAC por origem). Os limiares
abaixo sao os da decisao do responsavel (26/09) e a tela os exibe; a janela do
plantao e recorte de periodo, nao tolerancia de atraso (D.2 continua valendo:
atrasado e so "passou do horario").

Contrato do item (#117, ROADMAP §16):
- ``id`` estavel: ``regra:referencia[:contexto]``; texto livre entra como hash
  curto; nunca horario atual nem posicao. Recalcular nao muda o id.
- ``natureza`` (alerta | pendencia) e independente de ``gravidade``.
- ``desde``: quando nasceu a situacao de origem (nulo quando a fonte nao tem
  origem confiavel). ``prazo``: quando vence/venceu, so se o dominio fornece
  um vencimento real; validade por data D vale ate o fim do dia D no fuso da
  ILPI. "Agora" e referencia de apresentacao do cliente, nunca do item.
- Localizacao operacional minima (``unidade``/``quarto``/``leito``/``local``):
  atributo contextual do residente de um item ja autorizado; nao exige nem
  concede ``quartos_leitos:ler``.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
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
ORDEM_NATUREZA = {"alerta": 0, "pendencia": 1, "informativo": 2, "atividade": 3}

# Alerta: pede acao/atencao no plantao. Pendencia: algo a regularizar.
NATUREZA = {
    "doses_sem_registro": "alerta",
    "cuidados_sem_registro": "alerta",
    "intercorrencia_grave_aberta": "alerta",
    "intercorrencia_aberta_prolongada": "alerta",
    "ausencia_prolongada": "alerta",
    "admissao_parada": "pendencia",
    "documento_aguardando_validacao": "pendencia",
    "documento_vencido": "pendencia",
    "documento_vencendo": "pendencia",
    "avaliacao_vencida": "pendencia",
    "grau_ausente": "pendencia",
    "grau_vencido": "pendencia",
    "pais_ausente": "pendencia",
    "pais_parado": "pendencia",
    "pais_vencido": "pendencia",
    "residente_sem_leito": "pendencia",
    "acesso_nao_utilizado": "pendencia",
}

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


def _hash(*partes: str | None) -> str:
    """Hash curto e deterministico para contexto em texto livre no id (nulo != vazio)."""
    return hashlib.sha1("\x1f".join("\x00" if p is None else p for p in partes).encode("utf-8")).hexdigest()[:12]


def _local(unidade: str | None, quarto: str | None, leito: str | None) -> str | None:
    # Mesmo formato do rotuloLeito do frontend: "Ala B · Quarto 12 · Leito A".
    partes = [unidade, f"Quarto {quarto}" if quarto else None, f"Leito {leito}" if leito else None]
    return " · ".join(p for p in partes if p) or None


class _Coletor:
    """Junta os itens de todas as regras, com teto por regra."""

    def __init__(self, nomes: dict[str, str], leitos: dict[str, tuple]):
        self.nomes = nomes
        self.leitos = leitos
        self.itens: list[dict] = []
        self._por_regra: dict[str, int] = defaultdict(int)

    def add(self, regra, categoria, gravidade, titulo, *, referencia, chave=None, residente_id=None,
            detalhe=None, desde=None, prazo=None):
        if self._por_regra[regra] >= LIMITE_POR_REGRA:
            return
        self._por_regra[regra] += 1
        unidade, quarto, leito = self.leitos.get(residente_id, (None, None, None)) if residente_id else (None, None, None)
        self.itens.append({
            "id": f"{regra}:{chave or referencia}",
            "regra": regra,
            "categoria": categoria,
            "gravidade": gravidade,
            "natureza": NATUREZA[regra],
            "titulo": titulo,
            "detalhe": detalhe,
            "residente_id": residente_id,
            "residente_nome": self.nomes.get(residente_id) if residente_id else None,
            "referencia_id": referencia,
            "unidade": unidade,
            "quarto": quarto,
            "leito": leito,
            "local": _local(unidade, quarto, leito),
            "desde": _utc(desde) if isinstance(desde, datetime) else None,
            "prazo": _utc(prazo) if isinstance(prazo, datetime) else None,
        })


async def _fuso(db: AsyncSession, ilpi_id: str) -> ZoneInfo:
    instituicao = await db.get(m.Instituicao, ilpi_id)
    try:
        return ZoneInfo((instituicao.fuso_horario if instituicao else None) or FUSO_PADRAO)
    except ZoneInfoNotFoundError:
        return ZoneInfo(FUSO_PADRAO)


class _Calendario:
    """Hoje e fim de validade no fuso da ILPI."""

    def __init__(self, fuso: ZoneInfo, agora: datetime):
        self.fuso = fuso
        self.hoje = agora.astimezone(fuso).date()

    def fim_do_dia(self, dia: date) -> datetime:
        # Validade D vale ate o fim do dia D: vence as 00:00 de D+1 no fuso da ILPI.
        return datetime.combine(dia + timedelta(days=1), time.min, tzinfo=self.fuso).astimezone(timezone.utc)


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
            # A etapa e contexto: parada em Triagem e parada em Contrato sao situacoes distintas.
            c.add("admissao_parada", "admissao_documentos", "atencao",
                  f"Admissão parada em {ETAPA.get(admissao.situacao, admissao.situacao)}",
                  referencia=admissao.id, chave=f"{admissao.id}:{admissao.situacao}",
                  residente_id=admissao.residente_id,
                  detalhe=f"Sem avanço há {_plural(dias, 'dia', 'dias')}.", desde=desde)


async def _documentos(db, ilpi, cal: _Calendario, c: _Coletor):
    docs = (await db.scalars(select(m.Documento).where(m.Documento.instituicao_id == ilpi)
                             .order_by(m.Documento.created_at, m.Documento.id))).all()
    horizonte = cal.hoje + timedelta(days=DIAS_DOCUMENTO_VENCENDO)
    for doc in docs:
        # Mesmo predicado da pendencia da admissao: so a validacao humana cumpre.
        if doc.obrigatorio and doc.situacao != "validado":
            c.add("documento_aguardando_validacao", "admissao_documentos", "atencao",
                  f"Documento obrigatório aguardando validação: {doc.tipo}",
                  referencia=doc.id, residente_id=doc.residente_id, desde=doc.created_at)
        if doc.validade is None:
            continue
        prazo = cal.fim_do_dia(doc.validade)
        if doc.validade < cal.hoje:
            c.add("documento_vencido", "admissao_documentos", "atencao", f"Documento vencido: {doc.tipo}",
                  referencia=doc.id, residente_id=doc.residente_id, detalhe=f"Venceu em {_data_br(doc.validade)}.",
                  desde=prazo, prazo=prazo)
        elif doc.validade <= horizonte:
            c.add("documento_vencendo", "admissao_documentos", "aviso", f"Documento vence em breve: {doc.tipo}",
                  referencia=doc.id, residente_id=doc.residente_id, detalhe=f"Vence em {_data_br(doc.validade)}.",
                  prazo=prazo)


async def _avaliacoes(db, ilpi, cal: _Calendario, c: _Coletor):
    avaliacoes = (await db.scalars(select(m.Avaliacao).where(m.Avaliacao.ilpi_id == ilpi)
                                   .order_by(m.Avaliacao.data, m.Avaliacao.id))).all()
    grupos: dict[tuple, list] = defaultdict(list)
    for a in avaliacoes:
        grupos[(a.residente_id, a.tipo, a.instrumento)].append(a)
    for (residente_id, tipo, instrumento), lista in grupos.items():
        # Vale a regra da admissao: sem validade ou validade >= hoje cumpre.
        if any(a.validade is None or a.validade >= cal.hoje for a in lista):
            continue
        recente = lista[-1]
        # A cobertura do grupo acabou quando venceu a validade mais longa.
        fim = max(a.validade for a in lista)
        nome = " · ".join(x for x in (tipo, instrumento) if x)
        prazo = cal.fim_do_dia(fim)
        # A situacao e do grupo (residente, tipo, instrumento), nao da ultima avaliacao.
        c.add("avaliacao_vencida", "avaliacao_grau_pais", "atencao", f"Avaliação vencida: {nome}",
              referencia=recente.id, chave=f"{residente_id}:{_hash(tipo, instrumento)}",
              residente_id=residente_id, detalhe=f"Venceu em {_data_br(fim)}.", desde=prazo, prazo=prazo)


async def _graus(db, ilpi, cal: _Calendario, ativos, c: _Coletor):
    graus = {g.residente_id: g for g in (await db.scalars(select(m.GrauDependencia).where(
        m.GrauDependencia.ilpi_id == ilpi, m.GrauDependencia.situacao == "ativo"))).all()}
    for residente_id in ativos:
        grau = graus.get(residente_id)
        if grau is None:
            # Sem origem confiavel (nunca teve, foi revogado...): desde fica nulo.
            c.add("grau_ausente", "avaliacao_grau_pais", "atencao", "Sem grau de dependência confirmado",
                  referencia=residente_id, residente_id=residente_id)
        elif grau.validade is not None and grau.validade < cal.hoje:
            prazo = cal.fim_do_dia(grau.validade)
            c.add("grau_vencido", "avaliacao_grau_pais", "atencao", "Grau de dependência vencido",
                  referencia=grau.id, residente_id=residente_id, detalhe=f"Venceu em {_data_br(grau.validade)}.",
                  desde=prazo, prazo=prazo)


async def _planos(db, ilpi, agora, cal: _Calendario, ativos, c: _Coletor):
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
                      chave=f"{plano.id}:{plano.situacao}", residente_id=plano.residente_id,
                      detalhe=f"Sem mudança há {_plural((agora - mudou).days, 'dia', 'dias')}.", desde=mudou)
        elif plano.situacao == "vigente" and plano.data_final is not None and plano.data_final < cal.hoje:
            prazo = cal.fim_do_dia(plano.data_final)
            c.add("pais_vencido", "avaliacao_grau_pais", "atencao", "PAIS vigente com prazo encerrado",
                  referencia=plano.id, residente_id=plano.residente_id,
                  detalhe=f"Data final: {_data_br(plano.data_final)}.", desde=prazo, prazo=prazo)


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
            # O horario previsto mais antigo sem registro e a origem e o prazo que passou.
            c.add(regra, "plantao", gravidade, f"{_plural(total, um, varios)} sem registro",
                  referencia=residente_id, residente_id=residente_id,
                  detalhe=f"Horário previsto já passou nas últimas {HORAS_JANELA_PLANTAO} horas.",
                  desde=mais_antigo, prazo=mais_antigo)


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


def _leitos(ativos, com_leito, c: _Coletor):
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


_FIM_DOS_TEMPOS = datetime.max.replace(tzinfo=timezone.utc)


def _ordem(item: dict, agora: datetime) -> tuple:
    """Gravidade > alerta antes de pendencia > mais atrasado/antigo > id estavel.

    Referencia temporal: prazo ja vencido; senao ``desde``. So com prazo futuro,
    vem depois, o que vence primeiro antes. Sem tempo algum, por ultimo.
    """
    prazo, desde = item["prazo"], item["desde"]
    if prazo is not None and prazo <= agora:
        faixa, t = 0, prazo
    elif desde is not None:
        faixa, t = 0, desde
    elif prazo is not None:
        faixa, t = 1, prazo
    else:
        faixa, t = 2, _FIM_DOS_TEMPOS
    return (ORDEM_GRAVIDADE[item["gravidade"]], ORDEM_NATUREZA[item["natureza"]], faixa, t, item["id"])


@central_alertas_router.get("/", response_model=s.AlertaGestorResponse)
async def listar_alertas(
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("alertas:ler")),
):
    # PROJECAO: nenhuma linha e criada, alterada ou auditada aqui.
    chaves = set(await allowed_permission_keys(db, context))
    ilpi = context.ilpi_id
    agora = datetime.now(timezone.utc)
    cal = _Calendario(await _fuso(db, ilpi), agora)

    nomes: dict[str, str] = {}
    leitos: dict[str, tuple] = {}
    ativos: list[str] | None = None
    if "residentes:ler" in chaves:
        residentes = (await db.execute(select(m.Residente.id, m.Residente.nome, m.Residente.situacao)
                                       .where(m.Residente.instituicao_id == ilpi).order_by(m.Residente.nome))).all()
        nomes = {r.id: r.nome for r in residentes}
        ativos = [r.id for r in residentes if r.situacao == RESIDENTE_ATIVO]
        # Localizacao minima: uma consulta, mesmo gate do nome; indice unico garante 1 leito por residente.
        leitos = {r.residente_atual_id: (r.unidade, r.quarto, r.leito) for r in (await db.execute(
            select(m.QuartoLeito.residente_atual_id, m.QuartoLeito.unidade, m.QuartoLeito.quarto, m.QuartoLeito.leito)
            .where(m.QuartoLeito.instituicao_id == ilpi, m.QuartoLeito.residente_atual_id.is_not(None))
        )).all()}
    c = _Coletor(nomes, leitos)

    if "admissoes:ler" in chaves:
        await _admissoes(db, ilpi, agora, c)
    if "documentos:ler" in chaves:
        await _documentos(db, ilpi, cal, c)
    if "avaliacoes:ler" in chaves:
        await _avaliacoes(db, ilpi, cal, c)
    if "grau_dependencia:ler" in chaves and ativos is not None:
        await _graus(db, ilpi, cal, ativos, c)
    if "planos_cuidados:ler" in chaves:
        await _planos(db, ilpi, agora, cal, ativos, c)
    if "plantao:ler" in chaves:
        # Mesma origem do Meu Plantao: plantao:ler projeta cuidados e doses pendentes.
        await _plantao(db, ilpi, agora, c)
    if "intercorrencias:ler" in chaves:
        await _intercorrencias(db, ilpi, agora, c)
    if "quartos_leitos:ler" in chaves and ativos is not None:
        _leitos(ativos, set(leitos), c)
    if "ausencias:ler" in chaves:
        await _ausencias(db, ilpi, agora, c)
    if "funcionarios:ler" in chaves:
        await _acessos(db, ilpi, agora, c)

    c.itens.sort(key=lambda a: _ordem(a, agora))
    contagem = {chave: 0 for chave in (*ORDEM_GRAVIDADE, *ORDEM_NATUREZA)}
    for item in c.itens:
        contagem[item["gravidade"]] += 1
        contagem[item["natureza"]] += 1
    contagem["total"] = len(c.itens)
    return {"gerado_em": agora, "contagem": contagem, "alertas": c.itens}
