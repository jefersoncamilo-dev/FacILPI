import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity } from 'lucide-react'
import { getSinaisVitais, sinaisMedidos, SINAIS_VITAIS_CAMPOS, SINAIS_VITAIS_LIMIT_PADRAO, type CampoSinal, type SinalVital } from '../../services/sinaisVitais'
import { formatDateTime, mensagemDeErro } from '../../services/api'
import { LinhaEvolucao, type SerieEvolucao } from '../ui/charts'
import { EmptyState, ErrorState, LoadingState } from '../ui/states'

/**
 * UX-NAV-3: evolução dos sinais vitais do residente, a partir do histórico que
 * já existe (GET /sinais-vitais/?residente_id=). Um gráfico por medida, com
 * eixo próprio; pressão sistólica e diastólica dividem o gráfico (mesma
 * unidade). Nenhuma faixa "normal" e nenhum julgamento do valor: a tela só
 * mostra o que foi registrado.
 */
const GRAFICOS: { titulo: string; unidade: string; campos: CampoSinal[] }[] = [
  { titulo: 'Pressão arterial', unidade: 'mmHg', campos: ['pressao_sistolica', 'pressao_diastolica'] },
  { titulo: 'Temperatura', unidade: '°C', campos: ['temperatura'] },
  { titulo: 'Saturação', unidade: '%', campos: ['saturacao'] },
  { titulo: 'Frequência cardíaca', unidade: 'bpm', campos: ['frequencia_cardiaca'] },
  { titulo: 'Frequência respiratória', unidade: 'irpm', campos: ['frequencia_respiratoria'] },
  { titulo: 'Glicemia', unidade: 'mg/dL', campos: ['glicemia'] },
  { titulo: 'Peso', unidade: 'kg', campos: ['peso'] },
]

// Duas séries no máximo (pressão). Par validado no tema claro; a segunda é
// tracejada para a cor nunca ser a única diferença.
const ESTILOS = [
  { traco: 'stroke-brand', ponto: 'fill-brand', tracejado: false },
  { traco: 'stroke-info', ponto: 'fill-info', tracejado: true },
]

const rotuloDo = (campo: CampoSinal) => SINAIS_VITAIS_CAMPOS.find(c => c.campo === campo)?.label ?? campo

export function seriesDoGrafico(registros: SinalVital[], campos: CampoSinal[]): SerieEvolucao[] {
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

export function EvolucaoSinais({ residenteId, versao = 0 }: { residenteId: string; versao?: number }) {
  const [registros, setRegistros] = useState<SinalVital[] | null>(null)
  const [erro, setErro] = useState('')

  const carregar = useCallback(() => {
    setRegistros(null)
    setErro('')
    getSinaisVitais({ residente_id: residenteId })
      .then(setRegistros)
      .catch(e => setErro(mensagemDeErro(e, 'Não foi possível carregar os sinais vitais.')))
  }, [residenteId])

  useEffect(() => { carregar() }, [carregar, versao])

  const graficos = useMemo(
    () => (registros ? GRAFICOS.map(g => ({ ...g, series: seriesDoGrafico(registros, g.campos) })).filter(g => g.series.length > 0) : []),
    [registros],
  )

  if (erro) return <ErrorState title="Sinais vitais indisponíveis" description={erro} onRetry={carregar} />
  if (!registros) return <LoadingState label="Carregando evolução dos sinais vitais…" />
  if (graficos.length === 0) {
    return <EmptyState icon={Activity} title="Sem aferições ainda" description="Os gráficos aparecem depois do primeiro registro de sinais vitais." />
  }

  return (
    <section aria-labelledby="evolucao-titulo" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="evolucao-titulo" className="text-base font-semibold text-foreground">Evolução dos sinais vitais</h2>
        <p className="text-xs text-muted-foreground">
          {registros.length >= SINAIS_VITAIS_LIMIT_PADRAO ? `Últimos ${SINAIS_VITAIS_LIMIT_PADRAO} registros.` : `${registros.length} registros.`} Passe o dedo ou o mouse nos pontos para ver data e valor.
        </p>
      </div>
      <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {graficos.map(g => (
          <li key={g.titulo} className="card min-w-0">
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {g.titulo} <span className="font-normal text-muted-foreground">({g.unidade})</span>
            </h3>
            <LinhaEvolucao titulo={g.titulo} unidade={g.unidade} series={g.series} />
          </li>
        ))}
      </ul>
      {/* Mesma informação em tabela: leitura sem depender do gráfico. */}
      <details className="card">
        <summary className="min-h-[44px] cursor-pointer content-center text-sm font-semibold text-primary">Ver em tabela</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Sinais vitais registrados, do mais recente ao mais antigo</caption>
            <thead className="text-xs text-muted-foreground">
              <tr><th scope="col" className="py-2 pr-4">Quando</th><th scope="col" className="py-2 pr-4">Medidas</th><th scope="col" className="py-2">Quem registrou</th></tr>
            </thead>
            <tbody>
              {registros.map(r => (
                <tr key={r.id} className="border-t border-border align-top">
                  <td className="whitespace-nowrap py-2 pr-4">{formatDateTime(r.data)}</td>
                  <td className="py-2 pr-4">{sinaisMedidos(r).map(m => `${m.label}: ${m.texto}`).join(' · ')}</td>
                  <td className="py-2">{r.profissional || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}
