import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { CircleCheck, Clock, HeartPulse, ListTodo, TriangleAlert, type LucideIcon } from 'lucide-react'
import { getPlantao, type PlantaoItem } from '../../services/plantao'
import { getSinaisVitais, sinaisMedidos, type SinalVital } from '../../services/sinaisVitais'
import { formatDateTime } from '../../services/api'
import { MetricCard } from '../ui/metric-card'
import { ErrorState, LoadingState } from '../ui/states'
import { cn } from '../../lib/utils'

/**
 * UX-NAV-3: painel do dia do residente (aba Hoje). Só fontes que já existem:
 * GET /plantao/?residente_id= (cuidados, doses e intercorrências abertas) e
 * GET /sinais-vitais/?residente_id= (última aferição). Dose só aparece com
 * administracoes:ler. Registrar é no Meu Plantão, a fonte oficial da execução.
 */
type Carga<T> = { status: 'carregando' } | { status: 'ok'; dados: T } | { status: 'erro' } | { status: 'sem_acesso' }

type Situacao = { texto: string; icone: LucideIcon; classe: string }

export function situacaoDoItem(item: PlantaoItem, agora = Date.now()): Situacao {
  if (item.origem === 'intercorrencia') return { texto: 'Em aberto', icone: TriangleAlert, classe: 'bg-alerta-soft text-alerta-forte' }
  if (!item.previsto_em) return { texto: 'Sem horário', icone: Clock, classe: 'bg-muted text-muted-foreground' }
  return new Date(item.previsto_em).getTime() < agora
    ? { texto: 'Atrasado', icone: TriangleAlert, classe: 'bg-critico-soft text-critico-texto' }
    : { texto: 'Previsto', icone: Clock, classe: 'bg-info-soft text-foreground' }
}

const ROTULO_ORIGEM: Record<PlantaoItem['origem'], string> = { cuidado: 'Cuidado', medicacao: 'Dose', intercorrencia: 'Intercorrência' }

function hora(iso?: string | null) {
  return iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '—'
}

export function PainelHoje({ residenteId, pode, versao = 0 }: { residenteId: string; pode: (chave?: string) => boolean; versao?: number }) {
  const podePlantao = pode('plantao:ler')
  const podeDoses = pode('administracoes:ler')
  const podeSinais = pode('sinais_vitais:ler')
  const [itens, setItens] = useState<Carga<PlantaoItem[]>>({ status: podePlantao ? 'carregando' : 'sem_acesso' })
  const [ultimo, setUltimo] = useState<Carga<SinalVital | null>>({ status: podeSinais ? 'carregando' : 'sem_acesso' })

  const carregar = useCallback(() => {
    if (podePlantao) {
      setItens({ status: 'carregando' })
      getPlantao({ residente_id: residenteId })
        .then(d => setItens({ status: 'ok', dados: (d || []).filter(i => i.residente_id === residenteId && (podeDoses || i.origem !== 'medicacao')) }))
        .catch(() => setItens({ status: 'erro' }))
    }
    if (podeSinais) {
      setUltimo({ status: 'carregando' })
      getSinaisVitais({ residente_id: residenteId })
        .then(d => {
          const recente = [...(d || [])].filter(r => r.data).sort((a, b) => new Date(b.data!).getTime() - new Date(a.data!).getTime())[0] ?? null
          setUltimo({ status: 'ok', dados: recente })
        })
        .catch(() => setUltimo({ status: 'erro' }))
    }
  }, [residenteId, podePlantao, podeDoses, podeSinais])

  useEffect(() => { carregar() }, [carregar, versao])

  const lista = itens.status === 'ok' ? itens.dados : []
  const atrasados = lista.filter(i => situacaoDoItem(i).texto === 'Atrasado').length
  const abertas = lista.filter(i => i.origem === 'intercorrencia').length
  const pendentes = lista.filter(i => i.origem !== 'intercorrencia').length

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        {podePlantao && (
          <MetricCard
            icon={ListTodo}
            titulo={podeDoses ? 'Cuidados e doses pendentes' : 'Cuidados pendentes'}
            valor={itens.status === 'ok' ? pendentes : '—'}
            carregando={itens.status === 'carregando'}
            tom={atrasados > 0 ? 'critico' : 'normal'}
            estado={itens.status === 'ok' ? (atrasados > 0
              ? { texto: `${atrasados} ${atrasados === 1 ? 'atrasado' : 'atrasados'}`, icone: TriangleAlert }
              : { texto: 'Nada atrasado', icone: CircleCheck }) : undefined}
          />
        )}
        {podePlantao && (
          <MetricCard
            icon={TriangleAlert}
            titulo="Intercorrências abertas"
            valor={itens.status === 'ok' ? abertas : '—'}
            carregando={itens.status === 'carregando'}
            tom={abertas > 0 ? 'alerta' : 'normal'}
            estado={itens.status === 'ok' ? (abertas > 0
              ? { texto: 'Acompanhar', icone: TriangleAlert }
              : { texto: 'Nenhuma aberta', icone: CircleCheck }) : undefined}
          />
        )}
        {podeSinais && (
          <MetricCard
            icon={HeartPulse}
            titulo="Última aferição"
            valor={ultimo.status === 'ok' ? (ultimo.dados ? formatDateTime(ultimo.dados.data) : 'Nenhuma') : '—'}
            carregando={ultimo.status === 'carregando'}
            tom="neutro"
            detalhe={ultimo.status === 'ok' && ultimo.dados
              ? sinaisMedidos(ultimo.dados).map(m => `${m.label}: ${m.texto}`).join(' · ')
              : ultimo.status === 'erro' ? 'Não foi possível carregar.' : undefined}
          />
        )}
      </div>

      {podePlantao && (
        <section aria-labelledby="hoje-lista" className="card space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="hoje-lista" className="text-base font-semibold text-foreground">O que está previsto</h2>
            <Link to="/plantao" className="inline-flex min-h-[44px] items-center text-sm font-semibold text-primary hover:underline">Registrar no Meu Plantão</Link>
          </div>
          {itens.status === 'carregando' ? (
            <LoadingState label="Carregando o dia do residente…" />
          ) : itens.status === 'erro' ? (
            <ErrorState title="Não foi possível carregar o dia" description="Tente de novo em instantes." onRetry={carregar} />
          ) : lista.length === 0 ? (
            <p className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <CircleCheck className="size-5 text-brand" aria-hidden="true" /> Nada pendente para este residente agora.
            </p>
          ) : (
            <ul className="space-y-2">
              {lista.map(item => {
                const s = situacaoDoItem(item)
                return (
                  <li key={`${item.origem}-${item.registro_id}`} className="flex min-h-[52px] items-center gap-3 rounded-lg bg-muted px-3">
                    <span className="w-12 shrink-0 text-sm font-semibold">{hora(item.previsto_em)}</span>
                    <span className="min-w-0 flex-1 text-sm">
                      <span className="text-muted-foreground">{ROTULO_ORIGEM[item.origem]} · </span>{item.descricao}
                    </span>
                    <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold', s.classe)}>
                      <s.icone className="size-3.5" aria-hidden="true" />{s.texto}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      )}
    </div>
  )
}
