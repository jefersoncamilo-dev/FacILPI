import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  BedDouble,
  ClipboardList,
  DoorOpen,
  HeartPulse,
  TriangleAlert,
  UserPlus,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { api } from '../services/api'
import { getPlantao, PLANTAO_LIMIT_PADRAO, type PlantaoItem } from '../services/plantao'
import { getResumoDashboard, type DashboardResumo } from '../services/dashboard'
import { useAuth } from '../context/AuthContext'
import { usePermissoes } from '../context/PermissoesContext'
import { MetricCard } from '../components/ui/metric-card'
import { Badge, Skeleton } from '../components/ui/feedback'

/**
 * Início (UX-02 / #85). Responde à pergunta de quem abre:
 *  - gestão: "Como está minha instituição?" — indicadores do resumo oficial;
 *  - operação: "O que preciso fazer agora?" — pendências do turno primeiro.
 *
 * Todo número vem de fonte oficial: GET /dashboard/resumo (contagens no banco,
 * por permissão) e a projeção /plantao/. Indisponível nunca vira zero, e nada
 * sem fonte é exibido — alertas e conformidade não têm fonte oficial (GAP).
 */

// Indisponível não é zero: sem resposta da fonte, o valor é este traço.
// (Classes completas: o Tailwind não enxerga nomes montados em tempo de execução.)
// Links de texto com alvo de toque >= 24px (WCAG 2.5.8); 32px na prática.
const LINK = 'inline-flex min-h-[32px] items-center text-primary hover:underline'
const COLUNAS_INDICADORES: Record<number, string> = { 1: 'xl:grid-cols-1', 2: 'xl:grid-cols-2', 3: 'xl:grid-cols-3', 4: 'xl:grid-cols-4' }
const INDISPONIVEL = '—'

type Carga<T> = { status: 'carregando' } | { status: 'ok'; dados: T } | { status: 'erro' }

type ResidenteResumo = { id: string; nome: string; situacao?: string | null; grau_dependencia?: string | null }

const ORIGEM: Record<PlantaoItem['origem'], string> = {
  cuidado: 'Cuidado',
  medicacao: 'Medicação',
  intercorrencia: 'Intercorrência',
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

function horaPrevista(iso?: string | null): string {
  if (!iso) return 'sem hora'
  return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' }).format(new Date(iso))
}

export function Dashboard() {
  const { activeContext } = useAuth()
  const { pode, status: permissoes } = usePermissoes()
  const [resumo, setResumo] = useState<Carga<DashboardResumo>>({ status: 'carregando' })
  const [pendencias, setPendencias] = useState<Carga<PlantaoItem[]>>({ status: 'carregando' })
  const [residentes, setResidentes] = useState<Carga<ResidenteResumo[]>>({ status: 'carregando' })

  const podePlantao = pode('plantao:ler')
  const podeResidentes = pode('residentes:ler')
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

  const nomes = new Map((residentes.status === 'ok' ? residentes.dados : []).map(r => [r.id, r.nome]))
  const cards = montarIndicadores({ resumo, pendencias, gestao, pode, podePlantao })
  const acoes = [
    { to: '/sinais', label: 'Registrar sinal vital', icon: HeartPulse, permissao: 'sinais_vitais:criar' },
    { to: '/intercorrencias', label: 'Registrar intercorrência', icon: TriangleAlert, permissao: 'intercorrencias:criar' },
    { to: '/plantao', label: 'Abrir Meu Plantão', icon: ClipboardList, permissao: 'plantao:ler' },
    { to: '/residentes', label: 'Cadastrar residente', icon: UserPlus, permissao: 'residentes:criar' },
  ].filter(a => pode(a.permissao))

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Início</h1>
        <p className="text-sm text-muted-foreground">
          {saudacao()}
          {activeContext?.ilpiNome ? ` · ${activeContext.ilpiNome}` : ''} · {dataPorExtenso()}
        </p>
      </div>

      {cards.length > 0 && (
        <section aria-label="Indicadores" className={`grid grid-cols-2 gap-3 sm:gap-4 ${COLUNAS_INDICADORES[cards.length] ?? 'xl:grid-cols-4'}`}>
          {cards}
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {podePlantao && (
            <Painel
              titulo="Próximas pendências do turno"
              acao={<Link to="/plantao" className={LINK}>Abrir Meu Plantão</Link>}
            >
              <ListaPendencias carga={pendencias} nomes={nomes} />
            </Painel>
          )}
          {podeResidentes && (
            <Painel
              titulo="Residentes recentes"
              acao={<Link to="/residentes" className={LINK}>Ver todos</Link>}
            >
              <ListaResidentes carga={residentes} podeCriar={pode('residentes:criar')} />
            </Painel>
          )}
        </div>

        <div className="space-y-6">
          {acoes.length > 0 && (
            <Painel titulo="Ações rápidas">
              <ul className="space-y-1.5">
                {acoes.map(a => (
                  <li key={a.label}>
                    <Link
                      to={a.to}
                      className="group flex min-h-[48px] items-center gap-3 rounded-lg border border-border px-3 text-sm font-medium text-foreground transition-colors hover:border-brand/50 hover:bg-accent"
                    >
                      <a.icon className="size-[18px] shrink-0 text-primary" aria-hidden="true" />
                      <span className="flex-1">{a.label}</span>
                      <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                    </Link>
                  </li>
                ))}
              </ul>
            </Painel>
          )}
          {gestao && <ProcessosEmAndamento resumo={resumo} />}
        </div>
      </div>
    </div>
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
        atencao={pendencias.status === 'ok' && pendencias.dados.length > 0}
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
        valor={dados?.ocupacao ? `${dados.ocupacao.ocupados}/${dados.ocupacao.leitos_ativos}` : INDISPONIVEL}
        detalhe={!dados?.ocupacao
          ? indisponivel
          : dados.ocupacao.leitos_ativos === 0
            ? 'Nenhum leito ativo cadastrado'
            : `${Math.round((dados.ocupacao.ocupados / dados.ocupacao.leitos_ativos) * 100)}% ocupados · ${dados.ocupacao.livres} ${dados.ocupacao.livres === 1 ? 'livre' : 'livres'}`}
      />
    ) : null,
    ausencias: mostrar('ausencias_ativas', 'ausencias:ler') ? (
      <MetricCard
        key="ausencias"
        icon={DoorOpen}
        titulo="Ausentes agora"
        carregando={carregando}
        valor={dados?.ausencias_ativas?.total ?? INDISPONIVEL}
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
        atencao={(dados?.intercorrencias_abertas ?? 0) > 0}
        detalhe={dados ? undefined : indisponivel}
        acao={<Link to="/intercorrencias" className={LINK}>Ver intercorrências</Link>}
      />
    ) : null,
  }

  const ordem: (keyof typeof card)[] = gestao
    ? ['residentes', 'ocupacao', 'ausencias', 'intercorrencias', 'pendencias']
    : ['pendencias', 'intercorrencias', 'residentes', 'ausencias', 'ocupacao']
  return ordem.map(k => card[k]).filter(Boolean).slice(0, 4)
}

function Painel({ titulo, acao, children }: { titulo: string; acao?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-card shadow-card" aria-label={titulo}>
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-5">
        <h2 className="font-display text-base font-semibold text-foreground">{titulo}</h2>
        {acao && <div className="shrink-0 text-sm font-semibold">{acao}</div>}
      </header>
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  )
}

function Vazio({ icon: Icon, titulo, texto, children }: { icon: LucideIcon; titulo: string; texto?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center py-6 text-center">
      <Icon className="mb-2 size-7 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm font-medium text-foreground">{titulo}</p>
      {texto && <p className="mt-1 max-w-sm text-xs text-muted-foreground">{texto}</p>}
      {children}
    </div>
  )
}

function Falha({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <div role="alert" className="flex flex-col items-center py-6 text-center">
      <TriangleAlert className="mb-2 size-7 text-amber-700" aria-hidden="true" />
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

function ListaPendencias({ carga, nomes }: { carga: Carga<PlantaoItem[]>; nomes: Map<string, string> }) {
  if (carga.status === 'carregando') return <Carregando />
  if (carga.status === 'erro') {
    return <Falha titulo="Não foi possível carregar as pendências" texto="Isso não significa que não há pendências." />
  }
  if (carga.dados.length === 0) {
    return <Vazio icon={ClipboardList} titulo="Nenhuma pendência no período" texto="Cuidados, doses e intercorrências abertas aparecem aqui." />
  }
  return (
    <ul className="divide-y divide-border">
      {carga.dados.slice(0, 6).map(item => (
        <li key={`${item.origem}:${item.registro_id}`} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
          <span className={item.previsto_em ? 'w-12 shrink-0 pt-0.5 text-sm font-semibold tabular-nums text-foreground' : 'w-12 shrink-0 pt-1 text-[11px] leading-tight text-muted-foreground'}>
            {horaPrevista(item.previsto_em)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">{item.descricao}</p>
            <p className="truncate text-xs text-muted-foreground">{nomes.get(item.residente_id) || 'Residente'}</p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <Badge variant={item.origem === 'intercorrencia' ? 'warning' : 'neutral'}>{ORIGEM[item.origem]}</Badge>
            {item.prioridade && <Badge variant={item.prioridade === 'alta' ? 'danger' : 'neutral'}>Prioridade {item.prioridade}</Badge>}
          </div>
        </li>
      ))}
    </ul>
  )
}

function ListaResidentes({ carga, podeCriar }: { carga: Carga<ResidenteResumo[]>; podeCriar: boolean }) {
  if (carga.status === 'carregando') return <Carregando />
  if (carga.status === 'erro') {
    return <Falha titulo="Não foi possível carregar os residentes" texto="Isso não significa que não há residentes cadastrados." />
  }
  if (carga.dados.length === 0) {
    return (
      <Vazio icon={Users} titulo="Nenhum residente cadastrado">
        {podeCriar && <Link to="/residentes" className="btn-primary mt-4 inline-flex">Cadastrar residente</Link>}
      </Vazio>
    )
  }
  return (
    <ul className="space-y-1">
      {carga.dados.slice(0, 5).map(r => (
        <li key={r.id}>
          <Link to={`/residentes/${r.id}`} className="flex min-h-[48px] items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-muted">
            <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-sm font-semibold text-primary">
              {r.nome[0]}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-foreground">{r.nome}</span>
              {/* PH02-03 (#71): a situação exibida é a real; nenhum selo "Ativo" inventado. */}
              <span className="block truncate text-xs text-muted-foreground">{r.situacao || 'Situação não informada'} • {r.grau_dependencia || 'Sem grau'}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function ProcessosEmAndamento({ resumo }: { resumo: Carga<DashboardResumo> }) {
  if (resumo.status === 'carregando') {
    return <Painel titulo="Processos em andamento"><Carregando /></Painel>
  }
  if (resumo.status === 'erro') {
    return (
      <Painel titulo="Processos em andamento">
        <Falha titulo="Não foi possível carregar os processos" texto="Isso não significa que não há processos em andamento." />
      </Painel>
    )
  }
  const { admissoes_em_andamento: admissoes, planos, equipe } = resumo.dados
  if (admissoes === null && planos === null && equipe === null) return null
  const linha = (rotulo: string, valor: number, destaque = false) => (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <dt className="text-muted-foreground">{rotulo}</dt>
      <dd className={destaque && valor > 0 ? 'font-semibold text-amber-800' : 'font-semibold text-foreground'}>{valor}</dd>
    </div>
  )
  return (
    <Painel titulo="Processos em andamento">
      <div className="space-y-4">
        {admissoes !== null && (
          <div>
            <p className="pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Admissões</p>
            <dl>
            {linha('Em andamento', admissoes)}
            </dl>
          </div>
        )}
        {planos !== null && (
          <div>
            <p className="pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Plano de cuidados (PAIS)</p>
            <dl>
            {linha('Vigentes', planos.vigentes)}
            {linha('Em revisão', planos.em_revisao, true)}
            {linha('Em elaboração', planos.em_elaboracao)}
            {linha('Aprovados, aguardando vigência', planos.aprovados_aguardando_vigencia, true)}
            </dl>
          </div>
        )}
        {equipe !== null && (
          <div>
            <p className="pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Equipe</p>
            <dl>
            {linha('Ativos', equipe.ativos)}
            {linha('Afastados', equipe.afastados)}
            </dl>
            <Link to="/equipe" className={`${LINK} mt-1 text-sm font-semibold`}>Ver equipe</Link>
          </div>
        )}
      </div>
    </Painel>
  )
}
