import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, BedDouble, ClipboardList, Pill, RefreshCw, TriangleAlert } from 'lucide-react'
import { formatDateTime } from '../services/api'
import { getPlantao, getResidentesResumo, type PlantaoItem } from '../services/plantao'
import { GRAVIDADES, getIntercorrencias, INTERCORRENCIAS_LIMIT_PADRAO, type Intercorrencia } from '../services/intercorrencias'
import { ausenciasApi, ROTULO_AUSENCIA, type Ausencia } from '../services/leitos'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { EmptyState, ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

/**
 * Passagem de Plantão (UX-09 / #82). LEITURA das fontes governadas — nada aqui
 * cria, copia ou consolida registro (sem dual-write):
 *  - /plantao/ (projeção): cuidados e doses previstos sem registro e
 *    intercorrências abertas;
 *  - /intercorrencias/: detalhes, e as registradas no período;
 *  - /ausencias/: quem está fora e quem voltou no período.
 * A janela é escolhida pela pessoa: a ILPI não tem turnos cadastrados, então a
 * tela não inventa horário de troca. Registrar continua no Meu Plantão.
 */
const JANELAS = [6, 12, 24] as const
type Janela = (typeof JANELAS)[number]
const LIMITE_PLANTAO = 1000
const ROTULO_GRAVIDADE = Object.fromEntries(GRAVIDADES.map(g => [g.value, g.label])) as Record<string, string>

/** Compara instantes, não textos: o backend mistura "Z", "+00:00" e frações. */
const ms = (iso?: string | null) => (iso ? Date.parse(iso) : NaN)

type Fonte<T> = { dados: T; falhou: false } | { dados: null; falhou: 'proibido' | 'erro' | 'sem_permissao' }

interface PorResidente {
  residenteId: string
  pendentes: PlantaoItem[]
  proximas: number
  abertas: { item: PlantaoItem; detalhe?: Intercorrencia }[]
  encerradasNoPeriodo: Intercorrencia[]
  ausencia?: Ausencia
  retorno?: Ausencia
}

export function PassagemPlantao() {
  const { pode, status } = usePermissoesOuPadrao()
  const [janela, setJanela] = useState<Janela>(12)
  const [instante, setInstante] = useState(() => Date.now())
  const [plantao, setPlantao] = useState<Fonte<PlantaoItem[]> | null>(null)
  const [intercorrencias, setIntercorrencias] = useState<Fonte<Intercorrencia[]> | null>(null)
  const [ausencias, setAusencias] = useState<Fonte<Ausencia[]> | null>(null)
  const [nomes, setNomes] = useState<Record<string, string>>({})
  // Trocar a janela (ou as permissões chegarem) refaz as consultas; resposta de
  // consulta superada é descartada para não mostrar um período com o rótulo de outro.
  const pedido = useRef(0)

  const inicio = useMemo(() => new Date(instante - janela * 3600_000).toISOString(), [instante, janela])
  const fim = useMemo(() => new Date(instante + janela * 3600_000).toISOString(), [instante, janela])

  const carregar = useCallback(() => {
    const id = ++pedido.current
    setPlantao(null)
    setIntercorrencias(null)
    setAusencias(null)
    const falha = (e: any): 'proibido' | 'erro' => (e?.response?.status === 403 ? 'proibido' : 'erro')
    function consultar<T>(fn: () => Promise<T>, set: (f: Fonte<T>) => void) {
      fn().then(d => { if (id === pedido.current) set({ dados: d, falhou: false }) })
        .catch(e => { if (id === pedido.current) set({ dados: null, falhou: falha(e) }) })
    }
    consultar(() => getPlantao({ a_partir_de: inicio, ate: fim, limit: LIMITE_PLANTAO }), setPlantao)
    if (pode('intercorrencias:ler')) consultar(() => getIntercorrencias({ limit: INTERCORRENCIAS_LIMIT_PADRAO }), setIntercorrencias)
    else setIntercorrencias({ dados: null, falhou: 'sem_permissao' })
    if (pode('ausencias:ler')) consultar(() => ausenciasApi.listar(), setAusencias)
    else setAusencias({ dados: null, falhou: 'sem_permissao' })
  }, [inicio, fim, pode])

  // Espera as permissões da sessão: consultar antes mostraria uma visão parcial
  // (como se faltasse permissão) e a refaria segundos depois.
  useEffect(() => { if (status !== 'carregando') carregar() }, [carregar, status])
  useEffect(() => {
    getResidentesResumo().then(l => setNomes(Object.fromEntries(l.map(r => [r.id, r.nome])))).catch(() => setNomes({}))
  }, [])

  const visao = useMemo(() => {
    // Só monta quando as três fontes responderam: sem números provisórios nem reordenação.
    if (!plantao?.dados || !intercorrencias || !ausencias) return null
    const desde = instante - janela * 3600_000
    const detalhes = new Map((intercorrencias?.dados || []).map(i => [i.id, i]))
    const mapa = new Map<string, PorResidente>()
    const de = (rid: string) => {
      if (!mapa.has(rid)) mapa.set(rid, { residenteId: rid, pendentes: [], proximas: 0, abertas: [], encerradasNoPeriodo: [] })
      return mapa.get(rid)!
    }
    for (const item of plantao.dados) {
      if (item.origem === 'intercorrencia') de(item.residente_id).abertas.push({ item, detalhe: detalhes.get(item.registro_id) })
      else if (ms(item.previsto_em) < instante) de(item.residente_id).pendentes.push(item)
      else de(item.residente_id).proximas += 1
    }
    for (const i of intercorrencias?.dados || []) {
      if (i.situacao === 'encerrada' && ms(i.ocorrido_em) >= desde) de(i.residente_id).encerradasNoPeriodo.push(i)
    }
    for (const a of ausencias?.dados || []) {
      if (!a.data_fim) de(a.residente_id).ausencia = a
      else if (ms(a.data_fim) >= desde) de(a.residente_id).retorno = a
    }
    const todos = [...mapa.values()]
    const atencao = todos
      .filter(r => r.pendentes.length || r.abertas.length || r.encerradasNoPeriodo.length || r.ausencia || r.retorno)
      .sort((a, b) => Number(b.abertas.length > 0) - Number(a.abertas.length > 0)
        || Number(b.pendentes.length > 0) - Number(a.pendentes.length > 0)
        || (nomes[a.residenteId] || '').localeCompare(nomes[b.residenteId] || ''))
    const intercorrenciasNoPeriodo = (intercorrencias?.dados || []).filter(i => ms(i.ocorrido_em) >= desde)
    const lista = intercorrencias?.dados || []
    return {
      atencao,
      totais: {
        pendentes: todos.reduce((n, r) => n + r.pendentes.length, 0),
        abertas: todos.reduce((n, r) => n + r.abertas.length, 0),
        noPeriodo: intercorrenciasNoPeriodo.length,
        ausentes: todos.filter(r => r.ausencia).length,
        proximas: todos.reduce((n, r) => n + r.proximas, 0),
      },
      plantaoTruncado: plantao.dados.length >= LIMITE_PLANTAO,
      // Lista vem por ocorrido_em desc com teto de 100: se a mais antiga ainda
      // está dentro do período, pode haver outras fora da resposta.
      intercorrenciasTruncadas: lista.length >= INTERCORRENCIAS_LIMIT_PADRAO && ms(lista[lista.length - 1]?.ocorrido_em) >= desde,
    }
  }, [plantao, intercorrencias, ausencias, instante, janela, nomes])

  if (plantao?.falhou === 'proibido') return <ErrorState title="Sem acesso à passagem de plantão" description="Seu perfil não permite consultar o plantão nesta ILPI." />
  if (plantao?.falhou === 'erro') return <ErrorState title="Não foi possível montar a passagem de plantão" description="A consulta ao plantão falhou. Isso não significa que não há pendências." onRetry={carregar} />

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Passagem de plantão</h1>
          <p className="text-sm text-muted-foreground">O que ficou do período e o que vem a seguir, direto dos registros. Nada aqui cria registro novo.</p>
        </div>
        <Button variant="outline" onClick={() => setInstante(Date.now())}><RefreshCw aria-hidden="true" /> Atualizar</Button>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Período do plantão">
          {JANELAS.map(h => (
            <button key={h} type="button" aria-pressed={janela === h} onClick={() => setJanela(h)}
              className={cn('min-h-[40px] rounded-full border px-4 text-sm font-medium',
                janela === h ? 'border-brand bg-accent text-accent-foreground' : 'border-border bg-card text-muted-foreground hover:text-foreground')}>
              Últimas {h} h
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">De {formatDateTime(inicio)} até agora; “a seguir” cobre as próximas {janela} h.</p>
      </div>

      {!visao ? (
        <div className="space-y-3" aria-label="Carregando passagem">{[0, 1, 2].map(i => <Skeleton key={i} className="h-24" />)}</div>
      ) : (
        <>
          <section aria-label="Resumo do período"><dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Numero rotulo="Sem registro no período" valor={visao.totais.pendentes} destaque={visao.totais.pendentes > 0} />
            <Numero rotulo="Intercorrências abertas" valor={visao.totais.abertas} destaque={visao.totais.abertas > 0} />
            <Numero rotulo="Intercorrências no período" valor={intercorrencias?.dados ? visao.totais.noPeriodo : null} />
            <Numero rotulo="Ausentes agora" valor={ausencias?.dados ? visao.totais.ausentes : null} />
            <Numero rotulo={`Previstos nas próximas ${janela} h`} valor={visao.totais.proximas} />
          </dl></section>

          <Avisos intercorrencias={intercorrencias} ausencias={ausencias} plantaoTruncado={visao.plantaoTruncado} intercorrenciasTruncadas={visao.intercorrenciasTruncadas} />

          {visao.totais.pendentes > 0 && (pode('execucoes:criar') || pode('administracoes:criar')) && (
            <Alert variant="warning" title={`${visao.totais.pendentes} ${visao.totais.pendentes === 1 ? 'item previsto ficou' : 'itens previstos ficaram'} sem registro`}>
              Se foram feitos, registre com o horário real; se não, registre como recusado ou omitido.{' '}
              <Link to={`/plantao?desde=${encodeURIComponent(inicio)}`} className="inline-flex items-center gap-1 font-semibold underline">
                Registrar no Meu Plantão <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            </Alert>
          )}

          {visao.atencao.length === 0 ? (
            <EmptyState icon={ClipboardList} title="Nenhum ponto de atenção registrado no período"
              description="Sem itens previstos pendentes, intercorrências ou ausências nas fontes consultadas." />
          ) : (
            <section aria-label="Residentes com pontos de atenção" className="space-y-3">
              <h2 className="font-display text-base font-semibold text-foreground">Por residente ({visao.atencao.length})</h2>
              <ul className="space-y-3">
                {visao.atencao.map(r => <CartaoResidente key={r.residenteId} r={r} nome={nomes[r.residenteId] || 'Residente'} janela={janela} />)}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Numero({ rotulo, valor, destaque }: { rotulo: string; valor: number | null; destaque?: boolean }) {
  return (
    <div className={cn('rounded-card border bg-card p-4 shadow-card', destaque ? 'border-amber-300' : 'border-border')}>
      <dt className="text-xs text-muted-foreground">{rotulo}</dt>
      <dd className={cn('mt-1 font-display text-2xl font-bold', destaque ? 'text-amber-800' : 'text-foreground')}>{valor ?? '—'}</dd>
    </div>
  )
}

function Avisos({ intercorrencias, ausencias, plantaoTruncado, intercorrenciasTruncadas }: {
  intercorrencias: Fonte<Intercorrencia[]> | null; ausencias: Fonte<Ausencia[]> | null; plantaoTruncado: boolean; intercorrenciasTruncadas: boolean
}) {
  const avisos: string[] = []
  if (intercorrencias?.falhou === 'erro' || intercorrencias?.falhou === 'proibido') avisos.push('Não foi possível consultar as intercorrências: as abertas aparecem só pelo resumo do plantão, e as do período não estão incluídas.')
  if (ausencias?.falhou === 'erro' || ausencias?.falhou === 'proibido') avisos.push('Não foi possível consultar as ausências: elas não estão incluídas.')
  if (plantaoTruncado) avisos.push(`O plantão devolveu o máximo de ${LIMITE_PLANTAO} itens; escolha um período menor para ver tudo.`)
  if (intercorrenciasTruncadas) avisos.push(`Só as ${INTERCORRENCIAS_LIMIT_PADRAO} intercorrências mais recentes foram consultadas; pode haver outras no período.`)
  if (avisos.length === 0) return null
  return <Alert variant="warning" title="Visão parcial">{avisos.map(a => <p key={a}>{a}</p>)}</Alert>
}

function CartaoResidente({ r, nome, janela }: { r: PorResidente; nome: string; janela: number }) {
  return (
    <li className="space-y-3 rounded-card border border-border bg-card p-4 shadow-card sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to={`/residentes/${r.residenteId}`} className="font-medium text-foreground hover:text-primary hover:underline">{nome}</Link>
        <div className="flex flex-wrap gap-1.5">
          {r.abertas.length > 0 && <Badge variant="warning">{r.abertas.length} {r.abertas.length === 1 ? 'intercorrência aberta' : 'intercorrências abertas'}</Badge>}
          {r.ausencia && <Badge variant="neutral">{ROTULO_AUSENCIA[r.ausencia.tipo]}</Badge>}
        </div>
      </div>

      {r.ausencia && (
        <p className="flex items-start gap-2 text-sm text-foreground"><BedDouble className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          {ROTULO_AUSENCIA[r.ausencia.tipo]} desde {formatDateTime(r.ausencia.data_inicio)} — {r.ausencia.motivo}</p>
      )}
      {r.retorno && (
        <p className="flex items-start gap-2 text-sm text-foreground"><BedDouble className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          Retornou em {formatDateTime(r.retorno.data_fim)} ({ROTULO_AUSENCIA[r.retorno.tipo].toLowerCase()}: {r.retorno.motivo})</p>
      )}

      {r.abertas.map(({ item, detalhe }) => (
        <div key={item.registro_id} className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm">
          <p className="flex items-center gap-2 font-medium text-amber-900"><TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
            {detalhe ? <>{detalhe.tipo}{detalhe.gravidade ? ` · ${ROTULO_GRAVIDADE[detalhe.gravidade] || detalhe.gravidade}` : ''}</> : item.descricao}
          </p>
          {detalhe?.ocorrido_em && <p className="text-xs text-amber-900/80">Aberta desde {formatDateTime(detalhe.ocorrido_em)}{detalhe.responsavel ? ` · ${detalhe.responsavel}` : ''}</p>}
          {detalhe?.sbar_recomendacao && <p className="mt-1 text-foreground"><strong className="font-semibold">Recomendação:</strong> {detalhe.sbar_recomendacao}</p>}
          {detalhe?.providencia && <p className="text-foreground"><strong className="font-semibold">Providência:</strong> {detalhe.providencia}</p>}
        </div>
      ))}

      {r.encerradasNoPeriodo.map(i => (
        <p key={i.id} className="text-sm text-muted-foreground">
          Intercorrência encerrada no período: <span className="text-foreground">{i.tipo}</span>{i.desfecho ? ` — ${i.desfecho}` : ''}
        </p>
      ))}

      {r.pendentes.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Previsto e sem registro</p>
          <ul className="space-y-1">
            {r.pendentes.map(p => (
              <li key={p.registro_id} className="flex items-center gap-2 text-sm">
                {p.origem === 'medicacao' ? <Pill className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" /> : <ClipboardList className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
                <span className="tabular-nums text-muted-foreground">{formatDateTime(p.previsto_em)}</span>
                <span className="text-foreground">{p.origem === 'medicacao' ? 'Dose prevista de medicação' : p.descricao}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.proximas > 0 && <p className="text-xs text-muted-foreground">{r.proximas} {r.proximas === 1 ? 'item previsto' : 'itens previstos'} nas próximas {janela} h.</p>}
    </li>
  )
}
