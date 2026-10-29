import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api, formatDate, formatDateTime } from '../../services/api'
import { usePermissoesOuPadrao } from '../../context/PermissoesContext'
import { recarregarCentralAlertas, useCentralAlertas } from '../../hooks/useCentralAlertas'
import { destinoDoAlerta, ROTULO_GRAVIDADE } from '../../services/alertas'
import { ROTULO_PAIS, type Plano } from '../../services/pais'
import { sinaisMedidos, type SinalVital } from '../../services/sinaisVitais'
import { rotuloTipo, type Intercorrencia } from '../../services/intercorrencias'
import { Badge } from '../ui/feedback'
import { FamiliaresResidente } from './FamiliaresResidente'

/**
 * M4 (#186): Resumo do residente. Cada card lê a sua fonte oficial e só existe
 * (e só consulta) com a permissão de leitura dela — mesmo padrão de
 * useContextoResidente. Nada é agregado nem persistido aqui; falha de uma
 * fonte afeta só o seu card.
 */

// Só os campos que o card mostra (C5PrescricaoResponse).
type Prescricao = {
  id: string
  situacao: string
  dose: string
  unidade: string | null
  via: string | null
  frequencia: string | null
  medicamento_snapshot: { nome?: string | null } | null
}

type Fonte<T> = { status: 'carregando' } | { status: 'ok'; dados: T } | { status: 'erro' }

// Fora do provider (testes isolados) ou ainda carregando permissões, nada consulta.
function useFonte<T>(permissao: string, url: string, params: Record<string, unknown>, chave: string): Fonte<T> | null {
  const { pode, status } = usePermissoesOuPadrao()
  const pronto = status !== 'carregando' && status !== 'sem_provider' && pode(permissao)
  const [fonte, setFonte] = useState<Fonte<T>>({ status: 'carregando' })
  useEffect(() => {
    if (!pronto) return
    let vivo = true
    setFonte({ status: 'carregando' })
    Promise.resolve()
      .then(() => api.get<T>(url, { params }))
      .then(r => { if (vivo) setFonte({ status: 'ok', dados: r.data }) })
      .catch(() => { if (vivo) setFonte({ status: 'erro' }) })
    return () => { vivo = false }
    // `chave` identifica url+params; os objetos mudam a cada render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pronto, chave])
  return pronto ? fonte : null
}

function Card({ titulo, acao, children }: { titulo: string; acao?: ReactNode; children: ReactNode }) {
  return (
    <section className="card space-y-2 p-4" aria-label={titulo}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">{titulo}</h2>
        {acao}
      </div>
      {children}
    </section>
  )
}

function Corpo<T>({ fonte, vazio, children }: { fonte: Fonte<T>; vazio: string; children: (dados: T) => ReactNode | null }) {
  if (fonte.status === 'carregando') return <p className="text-sm text-muted-foreground">Carregando…</p>
  if (fonte.status === 'erro') return <p className="text-sm text-danger">Não foi possível carregar.</p>
  return <>{children(fonte.dados) ?? <p className="text-sm text-muted-foreground">{vazio}</p>}</>
}

const linkAcao = 'text-sm text-primary hover:underline inline-flex items-center min-h-[44px]'

function CardPais({ residenteId }: { residenteId: string }) {
  const fonte = useFonte<Plano[]>('planos_cuidados:ler', '/planos-cuidados/', { residente_id: residenteId }, `pais:${residenteId}`)
  if (!fonte) return null
  return (
    <Card titulo="PAIS vigente" acao={<Link to={`/plano?residente=${residenteId}`} className={linkAcao}>Abrir</Link>}>
      <Corpo fonte={fonte} vazio="Nenhum PAIS vigente.">
        {planos => {
          const p = planos.find(x => x.situacao === 'vigente')
          if (!p) return null
          return (
            <div className="space-y-1 text-sm">
              <p className="font-medium text-foreground">
                Versão {p.versao} · {ROTULO_PAIS[p.situacao]} desde {formatDate(p.data_inicial)}
                {p.data_final && <> · até {formatDate(p.data_final)}</>}
              </p>
              {p.objetivos && <p className="text-muted-foreground">{p.objetivos}</p>}
            </div>
          )
        }}
      </Corpo>
    </Card>
  )
}

function CardPrescricoes({ residenteId }: { residenteId: string }) {
  const fonte = useFonte<Prescricao[]>('prescricoes:ler', '/prescricoes/', { residente_id: residenteId, limit: 500 }, `presc:${residenteId}`)
  if (!fonte) return null
  return (
    <Card titulo="Prescrições ativas">
      <Corpo fonte={fonte} vazio="Nenhuma prescrição ativa.">
        {lista => {
          const ativas = lista.filter(x => x.situacao === 'ativa')
          if (ativas.length === 0) return null
          return (
            <ul className="space-y-1 text-sm">
              {ativas.map(p => (
                <li key={p.id}>
                  <span className="font-medium text-foreground">{p.medicamento_snapshot?.nome || 'Medicamento'}</span>{' '}
                  <span className="text-muted-foreground">
                    {[[p.dose, p.unidade].filter(Boolean).join(' '), p.via, p.frequencia].filter(Boolean).join(' · ')}
                  </span>
                </li>
              ))}
            </ul>
          )
        }}
      </Corpo>
    </Card>
  )
}

function CardSinais({ residenteId }: { residenteId: string }) {
  // O backend ordena por data decrescente: o primeiro é a última aferição.
  const fonte = useFonte<SinalVital[]>('sinais_vitais:ler', '/sinais-vitais/', { residente_id: residenteId, limit: 1 }, `sv:${residenteId}`)
  if (!fonte) return null
  return (
    <Card titulo="Última aferição">
      <Corpo fonte={fonte} vazio="Nenhuma aferição registrada.">
        {lista => {
          const s = lista[0]
          if (!s) return null
          const medidos = sinaisMedidos(s)
          return (
            <div className="space-y-1 text-sm">
              <p className="text-muted-foreground">{s.data ? formatDateTime(s.data) : 'Data não informada'}{s.profissional && <> · {s.profissional}</>}</p>
              {medidos.length > 0 && (
                <ul className="flex flex-wrap gap-x-4 gap-y-1">
                  {medidos.map(m => <li key={m.label}><span className="text-muted-foreground">{m.label}:</span> <span className="font-medium text-foreground">{m.texto}</span></li>)}
                </ul>
              )}
            </div>
          )
        }}
      </Corpo>
    </Card>
  )
}

function CardIntercorrencias({ residenteId }: { residenteId: string }) {
  const fonte = useFonte<Intercorrencia[]>('intercorrencias:ler', '/intercorrencias/', { residente_id: residenteId, limit: 100 }, `int:${residenteId}`)
  if (!fonte) return null
  return (
    <Card titulo="Intercorrências abertas" acao={<Link to={`/intercorrencias?residente=${residenteId}`} className={linkAcao}>Ver todas</Link>}>
      <Corpo fonte={fonte} vazio="Nenhuma intercorrência aberta.">
        {lista => {
          // Só `aberta` tem significado operacional de aberta (ver situacaoForaDoContrato).
          const abertas = lista.filter(x => x.situacao === 'aberta')
          if (abertas.length === 0) return null
          return (
            <ul className="space-y-1 text-sm">
              {abertas.map(i => (
                <li key={i.id}>
                  <span className="font-medium text-foreground">{rotuloTipo(i.tipo)}</span>
                  {i.gravidade && <> <Badge variant={i.gravidade === 'grave' ? 'danger' : 'warning'}>{i.gravidade}</Badge></>}
                  {i.ocorrido_em && <span className="text-muted-foreground"> · {formatDateTime(i.ocorrido_em)}</span>}
                </li>
              ))}
            </ul>
          )
        }}
      </Corpo>
    </Card>
  )
}

function CardAlertas({ residenteId }: { residenteId: string }) {
  const { pode, status } = usePermissoesOuPadrao()
  const pronto = status !== 'carregando' && status !== 'sem_provider' && pode('alertas:ler')
  const central = useCentralAlertas()
  // Mesmo retrato do sino e da Central (#117): não força recarga, respeita o intervalo mínimo.
  useEffect(() => { if (pronto) recarregarCentralAlertas() }, [pronto])
  if (!pronto) return null
  const fonte: Fonte<NonNullable<Extract<typeof central, { status: 'ok' }>['dados']>> =
    central.status === 'ok' ? { status: 'ok', dados: central.dados }
      : central.status === 'carregando' && central.dados ? { status: 'ok', dados: central.dados }
      : central.status === 'erro' || central.status === 'proibido' ? { status: 'erro' }
      : { status: 'carregando' }
  return (
    <Card titulo="Alertas do residente">
      <Corpo fonte={fonte} vazio="Nenhum alerta para este residente.">
        {dados => {
          const meus = dados.alertas.filter(a => a.residente_id === residenteId)
          if (meus.length === 0) return null
          return (
            <ul className="space-y-1 text-sm">
              {meus.map(a => {
                const destino = destinoDoAlerta(a)
                return (
                  <li key={a.id} className="flex flex-wrap items-center gap-x-2">
                    <Badge variant={a.gravidade === 'critico' ? 'danger' : 'warning'}>{ROTULO_GRAVIDADE[a.gravidade]}</Badge>
                    <span className="font-medium text-foreground">{a.titulo}</span>
                    <Link to={destino.to} className={linkAcao}>{destino.acao}</Link>
                  </li>
                )
              })}
            </ul>
          )
        }}
      </Corpo>
    </Card>
  )
}

export function ResumoResidente({ residenteId }: { residenteId: string }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <CardAlertas residenteId={residenteId} />
      <CardIntercorrencias residenteId={residenteId} />
      <CardPais residenteId={residenteId} />
      <CardPrescricoes residenteId={residenteId} />
      <CardSinais residenteId={residenteId} />
      <FamiliaresResidente residenteId={residenteId} />
    </div>
  )
}
