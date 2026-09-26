import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  BedDouble,
  BellRing,
  CheckCircle2,
  HeartHandshake,
  ChevronDown,
  ClipboardList,
  DoorOpen,
  NotebookPen,
  Pill,
  TriangleAlert,
  UserRoundPlus,
  Users,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'
import { api } from '../services/api'
import { getPlantao, PLANTAO_LIMIT_PADRAO, rotuloDoItem, type PlantaoItem } from '../services/plantao'
import { getResumoDashboard, type DashboardResumo } from '../services/dashboard'
import { GRAVIDADES as GRAVIDADES_ALERTA, listarAlertas, ROTULO_GRAVIDADE as ROTULO_ALERTA, type CentralAlertas } from '../services/alertas'
import { ItemAlerta } from '../components/alertas/ItemAlerta'
import { getSinaisVitais, type SinalVital } from '../services/sinaisVitais'
import { getIntercorrencias, GRAVIDADES, type Intercorrencia } from '../services/intercorrencias'
import { useAuth } from '../context/AuthContext'
import { usePermissoes } from '../context/PermissoesContext'
import { MetricCard } from '../components/ui/metric-card'
import { Badge, Skeleton } from '../components/ui/feedback'
import { Button } from '../components/ui/button'
import { BarraSegmentada, Legenda, MiniBarras, percentual, Rosca, type Segmento } from '../components/ui/charts'
import { acoesDoPerfil, type AcaoRapida } from '../components/shell/acoesRapidas'
import { rotuloSituacaoResidente } from '../lib/rotulos'
import { cn } from '../lib/utils'

/**
 * Início (UX-02 / #85; visual UX-11 / #101). Responde à pergunta de quem abre:
 *  - gestão: "Como está minha instituição?" — indicadores do resumo oficial;
 *  - operação: "O que preciso fazer agora?" — pendências do turno primeiro.
 *
 * Todo número e todo gráfico vêm de fonte oficial: GET /dashboard/resumo
 * (contagens no banco, por permissão), a projeção /plantao/ e as listas de
 * sinais vitais e intercorrências. Indisponível nunca vira zero; nada sem fonte
 * é exibido — conformidade e tendências não têm fonte (GAP #71). Alertas têm
 * fonte desde a #107 (GET /central-alertas/, só com `alertas:ler`).
 */

// Indisponível não é zero: sem resposta da fonte, o valor é este traço.
// (Classes completas: o Tailwind não enxerga nomes montados em tempo de execução.)
// Links de texto com alvo de toque >= 24px (WCAG 2.5.8); 32px na prática.
const LINK = 'inline-flex min-h-[32px] items-center text-primary hover:underline'
const COLUNAS_INDICADORES: Record<number, string> = { 1: 'xl:grid-cols-1', 2: 'xl:grid-cols-2', 3: 'xl:grid-cols-3', 4: 'xl:grid-cols-4' }
const INDISPONIVEL = '—'
const HORA = 3600_000
const ACOES_VISIVEIS = 6
const ALERTAS_NO_INICIO = 5

type Carga<T> = { status: 'carregando' } | { status: 'ok'; dados: T } | { status: 'erro' }

type ResidenteResumo = { id: string; nome: string; situacao?: string | null; grau_dependencia?: string | null }

const ORIGEM: Record<PlantaoItem['origem'], { rotulo: string; icone: LucideIcon; bolha: string }> = {
  cuidado: { rotulo: 'Cuidado', icone: ClipboardList, bolha: 'bg-brand-soft text-emerald-800' },
  medicacao: { rotulo: 'Medicação', icone: Pill, bolha: 'bg-sky-50 text-sky-800' },
  intercorrencia: { rotulo: 'Intercorrência', icone: TriangleAlert, bolha: 'bg-orange-50 text-orange-800' },
}

function saudacao(agora = new Date()): string {
  const hora = Number(new Intl.DateTimeFormat('pt-BR', { hour: 'numeric', hour12: false, timeZone: 'America/Sao_Paulo' }).format(agora))
  if (hora < 12) return 'Bom dia'
  if (hora < 18) return 'Boa tarde'
  return 'Boa noite'
}

function dataPorExtenso(agora = new Date()): string {
  return new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'America/Sao_Paulo' }).format(agora)
}

// Sem horário previsto só existe para intercorrência aberta: o estado real é
// "Aberta" (UX-11), não "sem hora".
function horaPrevista(iso?: string | null): string {
  if (!iso) return 'Aberta'
  return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' }).format(new Date(iso))
}

const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`

/** Pendências com horário distribuídas nas próximas 12 h (atrasadas contam na 1ª hora). */
export function pendenciasPorHora(itens: PlantaoItem[], agora = Date.now()): { valores: number[]; rotulos: string[] } {
  const valores = Array.from({ length: 12 }, () => 0)
  const rotulos = valores.map((_, i) => `${new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', timeZone: 'America/Sao_Paulo' }).format(new Date(agora + i * HORA))}h`)
  for (const item of itens) {
    if (!item.previsto_em) continue
    const indice = Math.max(0, Math.floor((Date.parse(item.previsto_em) - agora) / HORA))
    if (indice < 12) valores[indice] += 1
  }
  return { valores, rotulos }
}

export function Dashboard() {
  const { activeContext } = useAuth()
  const { pode, status: permissoes } = usePermissoes()
  const [resumo, setResumo] = useState<Carga<DashboardResumo>>({ status: 'carregando' })
  const [pendencias, setPendencias] = useState<Carga<PlantaoItem[]>>({ status: 'carregando' })
  const [residentes, setResidentes] = useState<Carga<ResidenteResumo[]>>({ status: 'carregando' })
  const [alertas, setAlertas] = useState<Carga<CentralAlertas>>({ status: 'carregando' })

  const podePlantao = pode('plantao:ler')
  const podeResidentes = pode('residentes:ler')
  // Só com a permissão confirmada pelo backend (indisponível não consulta às cegas).
  const podeAlertas = permissoes === 'ok' && pode('alertas:ler')
  // Perfil de experiência: quem responde pela instituição vê o espelho dela
  // primeiro; quem está no turno vê primeiro o que precisa fazer.
  const gestao = pode('funcionarios:ler') || pode('quartos_leitos:ler') || pode('admissoes:ler')

  useEffect(() => {
    getResumoDashboard()
      .then(dados => setResumo({ status: 'ok', dados }))
      .catch(() => setResumo({ status: 'erro' }))
  }, [])

  useEffect(() => {
    if (permissoes === 'carregando' || !podePlantao) return
    getPlantao()
      .then(dados => setPendencias({ status: 'ok', dados }))
      .catch(() => setPendencias({ status: 'erro' }))
  }, [permissoes, podePlantao])

  useEffect(() => {
    if (permissoes === 'carregando' || !podeResidentes) return
    api.get<ResidenteResumo[]>('/residentes/')
      .then(r => setResidentes({ status: 'ok', dados: r.data || [] }))
      .catch(() => setResidentes({ status: 'erro' }))
  }, [permissoes, podeResidentes])

  useEffect(() => {
    if (!podeAlertas) return
    listarAlertas()
      .then(dados => setAlertas({ status: 'ok', dados }))
      .catch(() => setAlertas({ status: 'erro' }))
  }, [podeAlertas])

  const nomes = new Map((residentes.status === 'ok' ? residentes.dados : []).map(r => [r.id, r.nome]))
  const cards = montarIndicadores({ resumo, pendencias, gestao, pode, podePlantao })
  // UX-11: o próprio perfil de acesso define as ações (catálogo por permissão).
  const acoes = permissoes === 'carregando' ? [] : acoesDoPerfil(pode, gestao)

  return (
    <div className="space-y-6">
      <BoasVindas
        ilpi={activeContext?.ilpiNome}
        perfil={activeContext?.perfilNome}
        resumo={resumo}
        pendencias={pendencias}
        gestao={gestao}
        atalhos={gestao ? [] : acoes.filter(a => a.destaque)}
      />

      {cards.length > 0 && (
        <section aria-label="Indicadores" className={`grid grid-cols-2 gap-3 sm:gap-4 ${COLUNAS_INDICADORES[cards.length] ?? 'xl:grid-cols-4'}`}>
          {cards}
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {podeAlertas && (
            <Painel
              titulo="Precisa de atenção"
              icone={BellRing}
              acao={<Link to="/alertas" className={LINK}>Ver todos os alertas</Link>}
            >
              <PrecisaDeAtencao carga={alertas} />
            </Painel>
          )}
          {podePlantao && (
            <Painel
              titulo="Próximas pendências do turno"
              icone={ClipboardList}
              acao={<Link to="/plantao" className={LINK}>Abrir Meu Plantão</Link>}
            >
              <LinhaDoTempo carga={pendencias} nomes={nomes} />
            </Painel>
          )}
          {gestao && <VisaoDaInstituicao resumo={resumo} />}
          {podeResidentes && (
            <Painel
              titulo="Residentes recentes"
              icone={Users}
              acao={<Link to="/residentes" className={LINK}>Ver todos</Link>}
            >
              <ListaResidentes carga={residentes} podeCriar={pode('residentes:criar')} />
            </Painel>
          )}
        </div>

        <div className="space-y-6">
          {acoes.length > 0 && <AcoesRapidas acoes={acoes} />}
          <AtividadeRecente nomes={nomes} />
        </div>
      </div>
    </div>
  )
}

/**
 * Faixa de boas-vindas: saudação, contexto e o "agora" em fatos curtos, só com
 * fontes que a sessão lê. Fonte indisponível sai da frase — nunca vira zero.
 */
function BoasVindas({ ilpi, perfil, resumo, pendencias, gestao, atalhos }: {
  ilpi?: string | null; perfil?: string | null; resumo: Carga<DashboardResumo>; pendencias: Carga<PlantaoItem[]>
  gestao: boolean; atalhos: AcaoRapida[]
}) {
  const fatos: { texto: string; icone: LucideIcon; alerta?: boolean }[] = []
  const dados = resumo.status === 'ok' ? resumo.dados : null
  if (dados?.intercorrencias_abertas != null) {
    const n = dados.intercorrencias_abertas
    fatos.push(n > 0
      ? { texto: plural(n, 'intercorrência aberta', 'intercorrências abertas'), icone: TriangleAlert, alerta: true }
      : { texto: 'Nenhuma intercorrência aberta', icone: TriangleAlert })
  }
  if (pendencias.status === 'ok') {
    const n = pendencias.dados.length
    fatos.push({ texto: n === 0 ? 'Nenhuma pendência no plantão' : plural(n, 'pendência no plantão', 'pendências no plantão'), icone: ClipboardList })
  }
  if (dados?.ausencias_ativas && dados.ausencias_ativas.total > 0) {
    fatos.push({ texto: plural(dados.ausencias_ativas.total, 'residente ausente', 'residentes ausentes'), icone: DoorOpen })
  }
  if (gestao && dados?.admissoes_em_andamento) {
    fatos.push({ texto: plural(dados.admissoes_em_andamento, 'admissão em andamento', 'admissões em andamento'), icone: UserRoundPlus })
  }

  return (
    <section aria-label="Resumo do momento" className="relative overflow-hidden rounded-card border border-emerald-100 bg-gradient-to-br from-emerald-50 via-white to-teal-50 p-5 shadow-card sm:p-7">
      <div aria-hidden="true" className="pointer-events-none absolute -right-16 -top-20 size-64 rounded-full bg-emerald-200/40 blur-3xl" />
      <div aria-hidden="true" className="pointer-events-none absolute -bottom-24 right-40 size-56 rounded-full bg-teal-200/30 blur-3xl" />
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0 space-y-2">
          <h1 className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-800">Início</h1>
          <p className="font-display text-2xl font-bold tracking-tight text-foreground sm:text-3xl">{saudacao()}!</p>
          <p className="text-sm text-slate-600">{[ilpi, perfil, dataPorExtenso()].filter(Boolean).join(' · ')}</p>
          {fatos.length > 0 && (
            <ul aria-label="Agora" className="flex flex-wrap gap-2 pt-1">
              {fatos.map(f => (
                <li key={f.texto} className={cn('inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold',
                  f.alerta ? 'border-orange-200 bg-orange-50 text-orange-800' : 'border-emerald-200 bg-white/80 text-emerald-900')}>
                  <f.icone className="size-3.5" aria-hidden="true" />{f.texto}
                </li>
              ))}
            </ul>
          )}
        </div>
        {atalhos.length === 0 && (
          <span aria-hidden="true" className="hidden size-20 shrink-0 items-center justify-center rounded-3xl bg-white/70 text-emerald-700 shadow-sm ring-1 ring-emerald-100 lg:inline-flex">
            <HeartHandshake className="size-10" />
          </span>
        )}
        {atalhos.length > 0 && (
          <div className="flex flex-col gap-2 sm:flex-row lg:shrink-0">
            {atalhos.map(a => (
              <Button key={a.id} asChild size="lg" variant={a.destaque === 'alerta' ? 'alerta' : 'default'} className="shadow-sm">
                <Link to={a.to}><a.icone aria-hidden="true" />{a.rotulo}</Link>
              </Button>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

function montarIndicadores({
  resumo,
  pendencias,
  gestao,
  pode,
  podePlantao,
}: {
  resumo: Carga<DashboardResumo>
  pendencias: Carga<PlantaoItem[]>
  gestao: boolean
  pode: (chave?: string) => boolean
  podePlantao: boolean
}): ReactNode[] {
  const carregando = resumo.status === 'carregando'
  const dados = resumo.status === 'ok' ? resumo.dados : null
  const indisponivel = <span>Indisponível no momento</span>
  // Com o resumo em erro, mostra o traço só onde a sessão PODE ler — indicar
  // indisponibilidade de um módulo que ela nem acessa seria ruído.
  const mostrar = (bloco: keyof DashboardResumo, permissao: string) =>
    carregando ? pode(permissao) : dados ? dados[bloco] !== null && dados[bloco] !== undefined : pode(permissao)
  const ocupacao = dados?.ocupacao
  const horas = pendencias.status === 'ok' ? pendenciasPorHora(pendencias.dados) : null

  const card = {
    pendencias: podePlantao ? (
      <MetricCard
        key="pendencias"
        icon={ClipboardList}
        titulo="Pendências do turno"
        carregando={pendencias.status === 'carregando'}
        valor={pendencias.status === 'ok'
          ? pendencias.dados.length >= PLANTAO_LIMIT_PADRAO ? `${PLANTAO_LIMIT_PADRAO}+` : pendencias.dados.length
          : INDISPONIVEL}
        tom={pendencias.status !== 'ok' ? 'neutro' : pendencias.dados.length > 0 ? 'alerta' : 'normal'}
        visual={horas && horas.valores.some(v => v > 0)
          ? <MiniBarras valores={horas.valores} rotulos={horas.rotulos} titulo="Pendências com horário nas próximas 12 horas" />
          : undefined}
        detalhe={pendencias.status === 'erro' ? indisponivel : 'Próximas 24 horas'}
        acao={<Link to="/plantao" className={LINK}>Ver Meu Plantão</Link>}
      />
    ) : null,
    residentes: mostrar('residentes_total', 'residentes:ler') ? (
      // PH02-03 (#71): "cadastrados", não "ativos" — a situação do residente
      // ainda não é governada (#76); o total é contagem oficial, sem teto.
      <MetricCard
        key="residentes"
        icon={Users}
        titulo="Residentes cadastrados"
        carregando={carregando}
        valor={dados?.residentes_total ?? INDISPONIVEL}
        tom={dados ? 'normal' : 'neutro'}
        visual={dados?.admissoes_em_andamento
          ? <span className="inline-flex rounded-full bg-sky-50 px-2.5 py-1 text-xs font-semibold text-sky-800">{dados.admissoes_em_andamento} em admissão</span>
          : undefined}
        detalhe={dados ? undefined : indisponivel}
        acao={<Link to="/residentes" className={LINK}>Ver residentes</Link>}
      />
    ) : null,
    ocupacao: mostrar('ocupacao', 'quartos_leitos:ler') ? (
      // Fonte governada: leitos (ocupado = com residente atual). Nunca derivada
      // do número de residentes.
      <MetricCard
        key="ocupacao"
        icon={BedDouble}
        titulo="Ocupação de leitos"
        carregando={carregando}
        valor={ocupacao ? `${ocupacao.ocupados}/${ocupacao.leitos_ativos}` : INDISPONIVEL}
        tom={ocupacao ? 'normal' : 'neutro'}
        visual={ocupacao && ocupacao.leitos_ativos > 0 ? <BarraSegmentada titulo="Leitos" segmentos={segmentosLeitos(ocupacao)} /> : undefined}
        detalhe={!ocupacao
          ? indisponivel
          : ocupacao.leitos_ativos === 0
            ? 'Nenhum leito ativo cadastrado'
            : `${percentual(ocupacao.ocupados, ocupacao.leitos_ativos)}% ocupados · ${ocupacao.livres} ${ocupacao.livres === 1 ? 'livre' : 'livres'}`}
      />
    ) : null,
    ausencias: mostrar('ausencias_ativas', 'ausencias:ler') ? (
      <MetricCard
        key="ausencias"
        icon={DoorOpen}
        titulo="Ausentes agora"
        carregando={carregando}
        valor={dados?.ausencias_ativas?.total ?? INDISPONIVEL}
        tom={dados?.ausencias_ativas ? 'normal' : 'neutro'}
        detalhe={dados?.ausencias_ativas
          ? `${dados.ausencias_ativas.hospitalizacoes} em hospitalização`
          : indisponivel}
      />
    ) : null,
    intercorrencias: mostrar('intercorrencias_abertas', 'intercorrencias:ler') ? (
      <MetricCard
        key="intercorrencias"
        icon={TriangleAlert}
        titulo="Intercorrências abertas"
        carregando={carregando}
        valor={dados?.intercorrencias_abertas ?? INDISPONIVEL}
        tom={dados?.intercorrencias_abertas == null ? 'neutro' : dados.intercorrencias_abertas > 0 ? 'alerta' : 'normal'}
        detalhe={!dados ? indisponivel : dados.intercorrencias_abertas ? 'Em aberto agora' : 'Nenhuma aberta agora'}
        acao={<Link to="/intercorrencias" className={LINK}>Ver intercorrências</Link>}
      />
    ) : null,
  }

  const ordem: (keyof typeof card)[] = gestao
    ? ['residentes', 'ocupacao', 'ausencias', 'intercorrencias', 'pendencias']
    : ['pendencias', 'intercorrencias', 'residentes', 'ausencias', 'ocupacao']
  return ordem.map(k => card[k]).filter(Boolean).slice(0, 4)
}

function segmentosLeitos(o: NonNullable<DashboardResumo['ocupacao']>): Segmento[] {
  return [
    { rotulo: 'Ocupados', valor: o.ocupados, fundo: 'bg-primary', traco: 'stroke-primary' },
    { rotulo: 'Livres', valor: o.livres, fundo: 'bg-emerald-300', traco: 'stroke-emerald-300' },
    { rotulo: 'Indisponíveis', valor: o.indisponiveis, fundo: 'bg-slate-300', traco: 'stroke-slate-300' },
  ]
}

/** Ações rápidas em blocos (catálogo por permissão; ver components/shell/acoesRapidas). */
function AcoesRapidas({ acoes }: { acoes: AcaoRapida[] }) {
  const [todas, setTodas] = useState(false)
  const visiveis = todas ? acoes : acoes.slice(0, ACOES_VISIVEIS)
  return (
    <Painel titulo="Ações rápidas">
      <ul className="grid grid-cols-2 gap-2">
        {visiveis.map(a => (
          <li key={a.id}>
            <Link
              to={a.to}
              className={cn(
                'group flex h-full min-h-[92px] flex-col justify-between gap-3 rounded-xl p-3 text-sm font-semibold leading-tight transition duration-150 hover:-translate-y-0.5 hover:shadow-cardHover motion-reduce:transition-none motion-reduce:hover:translate-y-0',
                a.destaque === 'primario' && 'bg-primary text-primary-foreground hover:bg-brand-ink',
                a.destaque === 'alerta' && 'bg-alerta-forte text-white hover:bg-orange-800',
                !a.destaque && 'border border-border bg-card text-foreground hover:border-brand/40 hover:bg-brand-soft/60',
              )}
            >
              <span aria-hidden="true" className={cn('inline-flex size-9 items-center justify-center rounded-full',
                a.destaque ? 'bg-white/20' : 'bg-brand-soft text-emerald-800')}>
                <a.icone className="size-[18px]" />
              </span>
              {a.rotulo}
            </Link>
          </li>
        ))}
      </ul>
      {acoes.length > ACOES_VISIVEIS && (
        <button type="button" onClick={() => setTodas(t => !t)} aria-expanded={todas}
          className="mt-3 inline-flex min-h-[40px] w-full items-center justify-center gap-1.5 rounded-lg text-sm font-semibold text-primary hover:bg-brand-soft/60">
          {todas ? 'Menos ações' : `Mais ações (${acoes.length - ACOES_VISIVEIS})`}
          <ChevronDown className={cn('size-4 transition-transform', todas && 'rotate-180')} aria-hidden="true" />
        </button>
      )}
    </Painel>
  )
}

const JANELA_ATIVIDADE_H = 12
const ROTULO_GRAVIDADE = Object.fromEntries(GRAVIDADES.map(g => [g.value, g.label])) as Record<string, string>

type Registro = { id: string; residenteId: string; quando: number; texto: string; tipo: 'sinal' | 'intercorrencia'; grave?: boolean }

/**
 * Atividade recente no turno (UX-11 / #101): os últimos registros das
 * últimas 12 h, lidos das listas oficiais de sinais vitais e intercorrências
 * — nada criado nem copiado. Cada fonte só é consultada com a própria
 * permissão; fonte que falha vira aviso de visão parcial, nunca "nada".
 */
function AtividadeRecente({ nomes }: { nomes: Map<string, string> }) {
  const { pode } = usePermissoes()
  const podeSinais = pode('sinais_vitais:ler')
  const podeIntercorrencias = pode('intercorrencias:ler')
  const [carga, setCarga] = useState<{ status: 'carregando' } | { status: 'ok'; registros: Registro[]; parcial: boolean }>({ status: 'carregando' })

  useEffect(() => {
    if (!podeSinais && !podeIntercorrencias) return
    let vigente = true
    const desde = Date.now() - JANELA_ATIVIDADE_H * HORA
    const quando = (iso?: string | null) => (iso ? Date.parse(iso) : NaN)
    Promise.allSettled([
      podeSinais ? getSinaisVitais({ limit: 30 }) : Promise.resolve([] as SinalVital[]),
      podeIntercorrencias ? getIntercorrencias({ limit: 30 }) : Promise.resolve([] as Intercorrencia[]),
    ]).then(([sinais, intercorrencias]) => {
      if (!vigente) return
      const registros: Registro[] = []
      if (sinais.status === 'fulfilled') {
        for (const s of sinais.value) registros.push({ id: `s:${s.id}`, residenteId: s.residente_id, quando: quando(s.data), texto: 'Sinais vitais aferidos', tipo: 'sinal' })
      }
      if (intercorrencias.status === 'fulfilled') {
        for (const i of intercorrencias.value) {
          registros.push({
            id: `i:${i.id}`, residenteId: i.residente_id, quando: quando(i.ocorrido_em), tipo: 'intercorrencia', grave: i.gravidade === 'grave',
            texto: `Intercorrência: ${i.tipo}${i.gravidade ? ` (${(ROTULO_GRAVIDADE[i.gravidade] || i.gravidade).toLowerCase()})` : ''}${i.situacao === 'encerrada' ? ' · encerrada' : ''}`,
          })
        }
      }
      setCarga({
        status: 'ok',
        registros: registros.filter(r => r.quando >= desde).sort((a, b) => b.quando - a.quando).slice(0, 6),
        parcial: sinais.status === 'rejected' || intercorrencias.status === 'rejected',
      })
    })
    return () => { vigente = false }
  }, [podeSinais, podeIntercorrencias])

  if (!podeSinais && !podeIntercorrencias) return null
  return (
    <Painel titulo="Atividade recente no turno" icone={Activity}>
      {carga.status === 'carregando' ? <Carregando /> : (
        <div className="space-y-3">
          {carga.parcial && <p className="text-xs text-orange-800">Parte da atividade não pôde ser consultada agora.</p>}
          {carga.registros.length === 0 ? (
            carga.parcial ? null : <Vazio icon={Activity} titulo={`Nenhum registro nas últimas ${JANELA_ATIVIDADE_H} horas`} texto="Sinais vitais e intercorrências registrados aparecem aqui." />
          ) : (
            <ul className="relative space-y-0.5">
              {/* Trilho da linha do tempo, atrás dos pontos. */}
              <span aria-hidden="true" className="absolute bottom-4 left-[4.1rem] top-4 w-px bg-border" />
              {carga.registros.map(r => (
                <li key={r.id} className="relative">
                  {/* A linha inteira leva ao prontuário: alvo de toque de 44px. */}
                  <Link to={`/residentes/${r.residenteId}`} className="-mx-2 flex min-h-[44px] items-center gap-3 rounded-lg px-2 py-2 hover:bg-muted">
                    <span className="w-12 shrink-0 text-sm font-semibold tabular-nums text-foreground">{horaPrevista(new Date(r.quando).toISOString())}</span>
                    <span aria-hidden="true" className={cn('relative size-2.5 shrink-0 rounded-full ring-4 ring-card',
                      r.tipo === 'sinal' ? 'bg-brand' : r.grave ? 'bg-critico' : 'bg-alerta')} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-foreground">{r.texto}</span>
                      <span className="block truncate text-xs text-muted-foreground">{nomes.get(r.residenteId) || 'Abrir prontuário'}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Painel>
  )
}

/** #107: os primeiros alertas da central (críticos antes), da mesma fonte oficial. */
function PrecisaDeAtencao({ carga }: { carga: Carga<CentralAlertas> }) {
  if (carga.status === 'carregando') return <Carregando />
  if (carga.status === 'erro') {
    return <Falha titulo="Não foi possível carregar os alertas" texto="Isso não significa que não há pendências." />
  }
  const { alertas, contagem } = carga.dados
  if (alertas.length === 0) {
    return <Vazio icon={CheckCircle2} titulo="Nada pedindo atenção agora" texto="Quando algo ficar pendente, vencer ou sair do combinado, aparece aqui." />
  }
  const resto = alertas.length - ALERTAS_NO_INICIO
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {GRAVIDADES_ALERTA.map(g => `${ROTULO_ALERTA[g]}: ${contagem[g]}`).join(' · ')}
      </p>
      <ul className="space-y-2">
        {alertas.slice(0, ALERTAS_NO_INICIO).map(a => <li key={a.id}><ItemAlerta alerta={a} compacto /></li>)}
      </ul>
      {resto > 0 && <p className="text-xs text-muted-foreground">E mais {plural(resto, 'alerta', 'alertas')} na central.</p>}
    </div>
  )
}

function Painel({ titulo, acao, icone: Icone, children }: { titulo: string; acao?: ReactNode; icone?: LucideIcon; children: ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-card shadow-card" aria-label={titulo}>
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-5">
        <h2 className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
          {Icone && (
            <span aria-hidden="true" className="inline-flex size-7 items-center justify-center rounded-lg bg-brand-soft text-emerald-800">
              <Icone className="size-4" />
            </span>
          )}
          {titulo}
        </h2>
        {acao && <div className="shrink-0 text-sm font-semibold">{acao}</div>}
      </header>
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  )
}

function Vazio({ icon: Icon, titulo, texto, children }: { icon: LucideIcon; titulo: string; texto?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center py-6 text-center">
      <span aria-hidden="true" className="mb-3 inline-flex size-12 items-center justify-center rounded-full bg-brand-soft text-emerald-800">
        <Icon className="size-6" />
      </span>
      <p className="text-sm font-medium text-foreground">{titulo}</p>
      {texto && <p className="mt-1 max-w-sm text-xs text-muted-foreground">{texto}</p>}
      {children}
    </div>
  )
}

function Falha({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <div role="alert" className="flex flex-col items-center py-6 text-center">
      <span aria-hidden="true" className="mb-3 inline-flex size-12 items-center justify-center rounded-full bg-orange-50 text-orange-700">
        <TriangleAlert className="size-6" />
      </span>
      <p className="text-sm font-medium text-foreground">{titulo}</p>
      <p className="mt-1 text-xs text-muted-foreground">{texto}</p>
    </div>
  )
}

function Carregando() {
  return (
    <div className="space-y-3" aria-hidden="true">
      {[0, 1, 2].map(i => <Skeleton key={i} className="h-12 w-full" />)}
    </div>
  )
}

/** Próximas pendências como linha do tempo: hora, origem colorida e o "agora". */
function LinhaDoTempo({ carga, nomes }: { carga: Carga<PlantaoItem[]>; nomes: Map<string, string> }) {
  if (carga.status === 'carregando') return <Carregando />
  if (carga.status === 'erro') {
    return <Falha titulo="Não foi possível carregar as pendências" texto="Isso não significa que não há pendências." />
  }
  if (carga.dados.length === 0) {
    return <Vazio icon={ClipboardList} titulo="Nenhuma pendência no período" texto="Cuidados, doses e intercorrências abertas aparecem aqui." />
  }
  const agora = Date.now()
  const itens = carga.dados.slice(0, 6)
  // O marcador "agora" entra antes do primeiro item futuro (ou sem horário).
  const indiceAgora = itens.findIndex(i => !i.previsto_em || Date.parse(i.previsto_em) >= agora)
  return (
    <ol className="relative">
      <span aria-hidden="true" className="absolute bottom-5 left-[4.6rem] top-5 w-px bg-border" />
      {itens.map((item, indice) => {
        const origem = ORIGEM[item.origem]
        const atrasada = !!item.previsto_em && Date.parse(item.previsto_em) < agora
        return (
          <li key={`${item.origem}:${item.registro_id}`} className="relative">
            {indice === indiceAgora && indice > 0 && (
              <div className="flex items-center gap-2 py-1 pl-[3.6rem]">
                <span className="rounded-full bg-emerald-800 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white">Agora</span>
                <span aria-hidden="true" className="h-px flex-1 bg-emerald-200" />
              </div>
            )}
            <div className="flex items-start gap-3 py-2.5">
              <span className={item.previsto_em ? 'w-12 shrink-0 pt-1.5 text-right text-sm font-semibold tabular-nums text-foreground' : 'w-12 shrink-0 pt-1.5 text-right text-xs font-semibold text-alerta-forte'}>
                {horaPrevista(item.previsto_em)}
              </span>
              <span aria-hidden="true" className={cn('relative z-10 inline-flex size-8 shrink-0 items-center justify-center rounded-full ring-4 ring-card', origem.bolha)}>
                <origem.icone className="size-4" />
              </span>
              <div className="min-w-0 flex-1 pt-0.5">
                <p className="text-sm font-medium text-foreground">{rotuloDoItem(item)}</p>
                <p className="truncate text-xs text-muted-foreground">{nomes.get(item.residente_id) || 'Residente'}</p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
                <Badge variant={item.origem === 'intercorrencia' ? 'warning' : 'neutral'}>{origem.rotulo}</Badge>
                {atrasada && <Badge variant="warning">Atrasada</Badge>}
                {item.prioridade && <Badge variant={item.prioridade === 'alta' ? 'danger' : 'neutral'}>Prioridade {item.prioridade}</Badge>}
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

const AVATAR = ['bg-emerald-50 text-emerald-800', 'bg-sky-50 text-sky-800', 'bg-violet-50 text-violet-800', 'bg-orange-50 text-orange-800', 'bg-rose-50 text-rose-800']

function ListaResidentes({ carga, podeCriar }: { carga: Carga<ResidenteResumo[]>; podeCriar: boolean }) {
  if (carga.status === 'carregando') return <Carregando />
  if (carga.status === 'erro') {
    return <Falha titulo="Não foi possível carregar os residentes" texto="Isso não significa que não há residentes cadastrados." />
  }
  if (carga.dados.length === 0) {
    return (
      <Vazio icon={Users} titulo="Nenhum residente cadastrado">
        {podeCriar && <Link to="/residentes?novo=1" className="btn-primary mt-4 inline-flex">Cadastrar residente</Link>}
      </Vazio>
    )
  }
  return (
    <ul className="grid gap-1 sm:grid-cols-2">
      {carga.dados.slice(0, 6).map(r => (
        <li key={r.id}>
          <Link to={`/residentes/${r.id}`} className="flex min-h-[52px] items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-muted">
            <span aria-hidden="true" className={cn('flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold', AVATAR[(r.nome.charCodeAt(0) || 0) % AVATAR.length])}>
              {r.nome[0]}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-foreground">{r.nome}</span>
              {/* PH02-03 (#71): a situação exibida é a real; nenhum selo "Ativo" inventado. */}
              <span className="block truncate text-xs text-muted-foreground">{r.situacao ? rotuloSituacaoResidente(r.situacao) : 'Situação não informada'} • {r.grau_dependencia || 'Sem grau'}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

/**
 * Espelho da instituição (gestão): leitos por situação em rosca e os processos
 * em andamento em barras — só com as contagens do resumo oficial.
 */
function VisaoDaInstituicao({ resumo }: { resumo: Carga<DashboardResumo> }) {
  if (resumo.status === 'carregando') {
    return <Painel titulo="Processos em andamento" icone={NotebookPen}><Carregando /></Painel>
  }
  if (resumo.status === 'erro') {
    return (
      <Painel titulo="Processos em andamento" icone={NotebookPen}>
        <Falha titulo="Não foi possível carregar os processos" texto="Isso não significa que não há processos em andamento." />
      </Painel>
    )
  }
  const { ocupacao, admissoes_em_andamento: admissoes, planos, equipe } = resumo.dados
  const temProcessos = admissoes !== null || planos !== null || equipe !== null
  if (!ocupacao && !temProcessos) return null
  const Titulo = ({ children }: { children: ReactNode }) => <p className="pb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">{children}</p>
  return (
    <div className={cn('grid gap-6', ocupacao && temProcessos && '2xl:grid-cols-2')}>
      {ocupacao && (
        <Painel titulo="Leitos por situação" icone={BedDouble} acao={<Link to="/quartos" className={LINK}>Ver leitos</Link>}>
          {ocupacao.leitos_ativos === 0 ? (
            <Vazio icon={BedDouble} titulo="Nenhum leito ativo cadastrado" />
          ) : (
            <div className="flex flex-col items-center gap-5 sm:flex-row">
              <Rosca titulo="Leitos por situação" segmentos={segmentosLeitos(ocupacao)}
                centro={`${percentual(ocupacao.ocupados, ocupacao.leitos_ativos)}%`} subcentro="ocupados" />
              <Legenda className="w-full" segmentos={segmentosLeitos(ocupacao)} />
            </div>
          )}
        </Painel>
      )}
      {temProcessos && (
        <Painel titulo="Processos em andamento" icone={NotebookPen}>
          <div className="space-y-5">
            {admissoes !== null && (
              <div>
                <Titulo>Admissões</Titulo>
                <Legenda segmentos={[{ rotulo: 'Em andamento', valor: admissoes, fundo: 'bg-sky-500', traco: 'stroke-sky-500' }]} />
              </div>
            )}
            {planos !== null && (() => {
              const segmentos: Segmento[] = [
                { rotulo: 'Vigentes', valor: planos.vigentes, fundo: 'bg-primary', traco: 'stroke-primary' },
                { rotulo: 'Aguardando vigência', valor: planos.aprovados_aguardando_vigencia, fundo: 'bg-emerald-300', traco: 'stroke-emerald-300' },
                { rotulo: 'Em revisão', valor: planos.em_revisao, fundo: 'bg-alerta', traco: 'stroke-alerta' },
                { rotulo: 'Em elaboração', valor: planos.em_elaboracao, fundo: 'bg-sky-400', traco: 'stroke-sky-400' },
              ]
              return (
                <div className="space-y-2.5">
                  <Titulo>Plano de cuidados (PAIS)</Titulo>
                  <BarraSegmentada titulo="Planos de cuidados por situação" segmentos={segmentos} />
                  <Legenda segmentos={segmentos} />
                </div>
              )
            })()}
            {equipe !== null && (() => {
              const segmentos: Segmento[] = [
                { rotulo: 'Ativos', valor: equipe.ativos, fundo: 'bg-primary', traco: 'stroke-primary' },
                { rotulo: 'Afastados', valor: equipe.afastados, fundo: 'bg-slate-300', traco: 'stroke-slate-300' },
              ]
              return (
                <div className="space-y-2.5">
                  <Titulo>Equipe</Titulo>
                  <BarraSegmentada titulo="Equipe por situação" segmentos={segmentos} />
                  <Legenda segmentos={segmentos} />
                  <Link to="/equipe" className={`${LINK} text-sm font-semibold`}><UsersRound className="mr-1.5 size-4" aria-hidden="true" />Ver equipe</Link>
                </div>
              )
            })()}
          </div>
        </Painel>
      )}
    </div>
  )
}
