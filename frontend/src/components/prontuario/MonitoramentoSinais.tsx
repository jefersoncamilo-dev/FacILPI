import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity } from 'lucide-react'
import {
  getSinaisVitais,
  SINAIS_VITAIS_CAMPOS,
  type CampoSinal,
  type SinalVital,
} from '../../services/sinaisVitais'
import { formatDateTime, mensagemDeErro } from '../../services/api'
import { LinhaEvolucao, type SerieEvolucao } from '../ui/charts'
import { EmptyState, ErrorState, LoadingState } from '../ui/states'
import { useAbaUrl } from '../../hooks/useFiltrosUrl'
import { cn } from '../../lib/utils'

/**
 * UX-NAV-4 (#298): aba Monitoramento da ficha. Um cartão por medida que já
 * existe em `sinais_vitais`; o clique abre a evolução daquela medida num painel.
 * Só mostra o que foi registrado: nenhuma faixa "normal", meta ou julgamento
 * de valor (decisão clínica fora do escopo, como no #286).
 */
export type MedidaId = 'pressao' | 'temperatura' | 'saturacao' | 'frequencia_cardiaca' | 'frequencia_respiratoria' | 'glicemia' | 'peso'

export const MEDIDAS: { id: MedidaId; titulo: string; unidade: string; campos: CampoSinal[] }[] = [
  { id: 'pressao', titulo: 'Pressão arterial', unidade: 'mmHg', campos: ['pressao_sistolica', 'pressao_diastolica'] },
  { id: 'frequencia_cardiaca', titulo: 'Frequência cardíaca', unidade: 'bpm', campos: ['frequencia_cardiaca'] },
  { id: 'saturacao', titulo: 'Saturação', unidade: '%', campos: ['saturacao'] },
  { id: 'temperatura', titulo: 'Temperatura', unidade: '°C', campos: ['temperatura'] },
  { id: 'frequencia_respiratoria', titulo: 'Frequência respiratória', unidade: 'irpm', campos: ['frequencia_respiratoria'] },
  { id: 'glicemia', titulo: 'Glicemia', unidade: 'mg/dL', campos: ['glicemia'] },
  { id: 'peso', titulo: 'Peso', unidade: 'kg', campos: ['peso'] },
]

// Primeiro item = padrão (useAbaUrl tira o parâmetro da URL quando é o padrão).
const PERIODOS = ['14', '7', '30', '90'] as const
type Periodo = (typeof PERIODOS)[number]
const PERIODOS_EM_ORDEM: Periodo[] = ['7', '14', '30', '90']

// O endpoint não filtra por data: buscamos um lote maior e o período é
// aplicado aqui. A tela avisa quando o lote pode não cobrir o período.
export const MONITORAMENTO_LIMIT = 300

const ESTILOS = [
  { traco: 'stroke-brand', ponto: 'fill-brand', tracejado: false },
  { traco: 'stroke-info', ponto: 'fill-info', tracejado: true },
]

const rotuloDo = (campo: CampoSinal) => SINAIS_VITAIS_CAMPOS.find(c => c.campo === campo)?.label ?? campo
const fmt = (v: number) => String(Math.round(v * 10) / 10).replace('.', ',')

export function seriesDaMedida(registros: SinalVital[], campos: CampoSinal[]): SerieEvolucao[] {
  const ordenados = registros
    .filter(r => r.data)
    .map(r => ({ r, data: new Date(r.data as string) }))
    .sort((a, b) => a.data.getTime() - b.data.getTime())
  return campos
    .map((campo, n) => ({
      rotulo: campos.length > 1 ? rotuloDo(campo).replace('Pressão ', '') : rotuloDo(campo),
      ...ESTILOS[n],
      pontos: ordenados.flatMap(({ r, data }) => {
        const v = r[campo]
        return v === null || v === undefined ? [] : [{ data, valor: Number(v) }]
      }),
    }))
    .filter(s => s.pontos.length > 0)
}

/** Valor da medida num registro, como texto (pressão = "sistólica/diastólica"). */
export function valorDaMedida(r: SinalVital, campos: CampoSinal[]): string | null {
  const vs = campos.map(c => r[c])
  if (vs.every(v => v === null || v === undefined)) return null
  return vs.map(v => (v === null || v === undefined ? '—' : fmt(Number(v)))).join('/')
}

function registrosDaMedida(registros: SinalVital[], campos: CampoSinal[]) {
  return registros
    .filter(r => r.data && valorDaMedida(r, campos) !== null)
    .sort((a, b) => new Date(b.data as string).getTime() - new Date(a.data as string).getTime())
}

function Minilinha({ serie }: { serie?: SerieEvolucao }) {
  if (!serie || serie.pontos.length < 2) return <span className="h-6 w-16" aria-hidden="true" />
  const vs = serie.pontos.map(p => p.valor)
  const min = Math.min(...vs), max = Math.max(...vs)
  const pts = serie.pontos
    .map((p, i) => `${(i / (serie.pontos.length - 1)) * 64},${max === min ? 12 : 22 - ((p.valor - min) / (max - min)) * 20}`)
    .join(' ')
  return (
    <svg width="64" height="24" viewBox="0 0 64 24" aria-hidden="true" className="shrink-0 overflow-visible">
      <polyline points={pts} fill="none" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" className={serie.traco} />
    </svg>
  )
}

export function MonitoramentoSinais({ residenteId, versao = 0 }: { residenteId: string; versao?: number }) {
  const [registros, setRegistros] = useState<SinalVital[] | null>(null)
  const [erro, setErro] = useState('')

  const carregar = useCallback(() => {
    setRegistros(null)
    setErro('')
    getSinaisVitais({ residente_id: residenteId, limit: MONITORAMENTO_LIMIT })
      .then(setRegistros)
      .catch(e => setErro(mensagemDeErro(e, 'Não foi possível carregar os sinais vitais.')))
  }, [residenteId])

  useEffect(() => { carregar() }, [carregar, versao])

  const { ativa: periodo, trocar: trocarPeriodo } = useAbaUrl<Periodo>(PERIODOS, 'periodo', registros !== null)

  const noPeriodo = useMemo(() => {
    if (!registros) return []
    const corte = Date.now() - Number(periodo) * 24 * 60 * 60 * 1000
    return registros.filter(r => r.data && new Date(r.data).getTime() >= corte)
  }, [registros, periodo])

  // Cartões: medidas com pelo menos um registro em todo o histórico carregado.
  const cartoes = useMemo(
    () =>
      (registros ?? [])
        .length === 0
        ? []
        : MEDIDAS.map(m => {
            const todos = registrosDaMedida(registros ?? [], m.campos)
            return { ...m, ultimo: todos[0], series: seriesDaMedida(noPeriodo, m.campos), doPeriodo: registrosDaMedida(noPeriodo, m.campos) }
          }).filter(c => c.ultimo),
    [registros, noPeriodo],
  )

  const ids = useMemo(() => cartoes.map(c => c.id), [cartoes])
  const { ativa: medida, trocar: trocarMedida } = useAbaUrl<MedidaId>(ids, 'medida', registros !== null && ids.length > 0)
  const atual = cartoes.find(c => c.id === medida)

  if (erro) return <ErrorState title="Sinais vitais indisponíveis" description={erro} onRetry={carregar} />
  if (!registros) return <LoadingState label="Carregando o monitoramento…" />
  if (cartoes.length === 0) {
    return <EmptyState icon={Activity} title="Sem aferições ainda" description="O monitoramento aparece depois do primeiro registro de sinais vitais." />
  }

  const truncado = registros.length >= MONITORAMENTO_LIMIT

  return (
    <section aria-labelledby="monitoramento-titulo" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="monitoramento-titulo" className="text-base font-semibold text-foreground">Monitoramento dos sinais vitais</h2>
        <div role="group" aria-label="Período dos gráficos" className="flex gap-1 rounded-xl bg-muted p-1">
          {PERIODOS_EM_ORDEM.map(p => (
            <button
              key={p}
              type="button"
              aria-pressed={periodo === p}
              onClick={() => trocarPeriodo(p)}
              className={cn(
                'min-h-[44px] rounded-lg px-3 text-sm font-medium text-muted-foreground',
                periodo === p && 'bg-card font-semibold text-foreground shadow-sm',
              )}
            >
              {p} dias
            </button>
          ))}
        </div>
      </div>

      <ul className="grid grid-cols-1 gap-2 min-[360px]:grid-cols-2 lg:grid-cols-4" aria-label="Medidas">
        {cartoes.map(c => {
          const aberto = c.id === medida
          return (
            <li key={c.id} className="min-w-0">
              <button
                type="button"
                aria-pressed={aberto}
                aria-controls="monitoramento-detalhe"
                onClick={() => trocarMedida(c.id)}
                className={cn(
                  'animar-entrada flex h-full w-full min-w-0 flex-col gap-1 rounded-xl border-2 bg-card p-3 text-left transition-colors hover:bg-muted/50',
                  aberto ? 'border-brand bg-brand/5' : 'border-border',
                )}
              >
                <span className="text-sm font-semibold text-foreground">{c.titulo}</span>
                <span className="flex items-center justify-between gap-2">
                  <span className="min-w-0">
                    <span className="text-2xl font-bold text-foreground">{valorDaMedida(c.ultimo, c.campos)}</span>{' '}
                    <span className="text-sm text-muted-foreground">{c.unidade}</span>
                  </span>
                  <Minilinha serie={c.series[0]} />
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {formatDateTime(c.ultimo.data)}{c.ultimo.profissional ? ` · ${c.ultimo.profissional}` : ''}
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      <div id="monitoramento-detalhe" aria-live="polite" className="card min-w-0">
        {atual && (
          <div key={`${atual.id}-${periodo}`} className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="min-w-0">
              <h3 className="mb-2 text-sm font-semibold text-foreground">
                {atual.titulo} <span className="font-normal text-muted-foreground">({atual.unidade}) · últimos {periodo} dias</span>
              </h3>
              {atual.series.length > 0 ? (
                <LinhaEvolucao titulo={atual.titulo} unidade={atual.unidade} series={atual.series} animar />
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">Nenhum registro desta medida nos últimos {periodo} dias.</p>
              )}
              {truncado && (
                <p className="mt-2 text-xs text-muted-foreground">Mostrando os {MONITORAMENTO_LIMIT} registros mais recentes; o período pode estar incompleto.</p>
              )}
            </div>
            <div className="min-w-0">
              <table className="w-full text-left text-sm">
                <caption className="mb-1 text-left text-xs font-medium text-muted-foreground">Registros no período</caption>
                <thead className="sr-only">
                  <tr><th scope="col">Quando</th><th scope="col">Valor</th><th scope="col">Quem registrou</th></tr>
                </thead>
                <tbody>
                  {atual.doPeriodo.slice(0, 8).map(r => (
                    <tr key={r.id} className="border-t border-border align-top">
                      <td className="whitespace-nowrap py-1.5 pr-2 text-muted-foreground">{formatDateTime(r.data)}</td>
                      <td className="whitespace-nowrap py-1.5 pr-2 font-semibold text-foreground">{valorDaMedida(r, atual.campos)}</td>
                      <td className="py-1.5 text-muted-foreground">{r.profissional || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {atual.doPeriodo.length > 8 && (
                <p className="mt-1 text-xs text-muted-foreground">e mais {atual.doPeriodo.length - 8} registros no período.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
