import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { HandHeart, Loader2, XCircle } from 'lucide-react'
import { api, formatDate, formatDateTime, mensagemDeErro } from '../services/api'
import { paisApi } from '../services/pais'
import { cuidadosApi, ROTULO_PRIORIDADE, type Ocorrencia, type Programacao } from '../services/cuidados'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Label } from '../components/ui/input'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { EmptyState, ErrorState } from '../components/ui/states'

type ResidenteRef = { id: string; nome: string }
const SELECT = 'flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40'
const AREA = 'w-full rounded-lg border border-input bg-card px-3 py-2 text-[16px] focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40'
const SEM_AREA = 'Sem área definida'

/**
 * Cuidados programados (M12 / #185): programações ativas por residente e área,
 * com as ocorrências previstas de hoje e amanhã. Programação não é execução:
 * o registro do cuidado continua no Meu Plantão; aqui só se cancela uma
 * ocorrência prevista, com motivo. A criação nasce no PAIS vigente.
 */
export function Cuidados() {
  const { pode } = usePermissoesOuPadrao()
  const [programacoes, setProgramacoes] = useState<Programacao[] | null>(null)
  const [ocorrencias, setOcorrencias] = useState<Ocorrencia[]>([])
  const [residentes, setResidentes] = useState<Map<string, string>>(new Map())
  const [intervencoes, setIntervencoes] = useState<Map<string, string>>(new Map())
  const [falha, setFalha] = useState(false)
  const [area, setArea] = useState('')
  const [cancelar, setCancelar] = useState<Ocorrencia | null>(null)
  const [aviso, setAviso] = useState<{ tipo: 'success' | 'error'; texto: string } | null>(null)

  const carregar = useCallback(async () => {
    const hoje = new Date()
    hoje.setHours(0, 0, 0, 0)
    const ate = new Date(hoje.getTime() + 2 * 86400000 - 1)
    try {
      const [progs, ocs] = await Promise.all([
        cuidadosApi.listar(),
        cuidadosApi.ocorrencias(hoje.toISOString(), ate.toISOString()).catch(() => [] as Ocorrencia[]),
      ])
      const ativas = progs.filter(p => p.situacao === 'ativa')
      setProgramacoes(ativas)
      setOcorrencias(ocs)
      setFalha(false)
      const planos = await Promise.all([...new Set(ativas.map(p => p.plano_id))].map(id => paisApi.obter(id).catch(() => null)))
      setIntervencoes(new Map(planos.flatMap(pl => (pl ? pl.intervencoes.map(i => [i.id, i.descricao] as [string, string]) : []))))
    } catch {
      setFalha(true)
    }
  }, [])

  useEffect(() => {
    carregar()
    api.get<ResidenteRef[]>('/residentes/').then(r => setResidentes(new Map((r.data || []).map(x => [x.id, x.nome])))).catch(() => setResidentes(new Map()))
  }, [carregar])

  const areas = useMemo(() => [...new Set((programacoes || []).map(p => p.perfil_responsavel || SEM_AREA))].sort(), [programacoes])
  const grupos = useMemo(() => {
    const porResidente = new Map<string, Programacao[]>()
    for (const p of programacoes || []) {
      if (area && (p.perfil_responsavel || SEM_AREA) !== area) continue
      porResidente.set(p.residente_id, [...(porResidente.get(p.residente_id) || []), p])
    }
    return [...porResidente.entries()].sort(([a], [b]) => (residentes.get(a) || a).localeCompare(residentes.get(b) || b))
  }, [programacoes, area, residentes])

  async function confirmarCancelamento(motivo: string) {
    if (!cancelar) return
    setAviso(null)
    try {
      await cuidadosApi.cancelarOcorrencia(cancelar.id, motivo)
      setAviso({ tipo: 'success', texto: 'Ocorrência cancelada. Ela sai do Meu Plantão e o motivo fica no histórico.' })
    } catch (e) {
      setAviso({ tipo: 'error', texto: mensagemDeErro(e, 'Não foi possível cancelar a ocorrência.') })
    } finally {
      setCancelar(null)
      await carregar()
    }
  }

  if (falha) return <ErrorState title="Não foi possível carregar os cuidados programados" onRetry={carregar} />
  if (!programacoes) return <div className="space-y-4" aria-label="Carregando cuidados"><Skeleton className="h-10 w-72" /><Skeleton className="h-40 w-full" /></div>

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Cuidados programados</h1>
        <p className="text-sm text-muted-foreground">
          Horários definidos a partir do <Link to="/plano" className="font-medium text-primary hover:underline">plano de cuidados (PAIS)</Link>.
          Os cuidados previstos aparecem no Meu Plantão; o registro do que foi feito é feito lá.
        </p>
      </div>

      {aviso && <Alert variant={aviso.tipo}>{aviso.texto}</Alert>}

      {programacoes.length === 0 ? (
        <EmptyState icon={HandHeart} title="Nenhum cuidado programado" description="Abra um PAIS vigente e use “Programar horários” em uma intervenção." />
      ) : (
        <>
          <div className="max-w-xs space-y-2">
            <Label htmlFor="cuidados-area">Área</Label>
            <select id="cuidados-area" className={SELECT} value={area} onChange={e => setArea(e.target.value)}>
              <option value="">Todas as áreas</option>
              {areas.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          {grupos.map(([residenteId, progs]) => (
            <section key={residenteId} aria-label={residentes.get(residenteId) || 'Residente'} className="space-y-3 rounded-card border border-border bg-card p-5 shadow-card">
              <h2 className="font-display text-base font-semibold text-foreground">
                <Link to={`/residentes/${residenteId}`} className="hover:underline">{residentes.get(residenteId) || 'Residente'}</Link>
              </h2>
              <ul className="space-y-3">
                {progs.map(p => {
                  const proximas = ocorrencias.filter(o => o.programacao_id === p.id && o.situacao === 'prevista' && o.pendente)
                  return (
                    <li key={p.id} className="space-y-2 rounded-lg bg-muted/60 px-3 py-2 text-sm">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <Link to={`/plano/${p.plano_id}`} className="font-medium text-foreground hover:underline">{intervencoes.get(p.intervencao_id) || 'Intervenção do PAIS'}</Link>
                        <Badge variant={p.prioridade === 'alta' ? 'warning' : 'neutral'}>Prioridade {ROTULO_PRIORIDADE[p.prioridade] || p.prioridade}</Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {p.horarios.join(', ')} · {p.perfil_responsavel || SEM_AREA} · desde {formatDate(p.vigencia_inicio)}{p.vigencia_fim ? ` até ${formatDate(p.vigencia_fim)}` : ''}
                      </p>
                      {proximas.length > 0 && (
                        <ul aria-label="Próximas ocorrências" className="space-y-1">
                          {proximas.map(o => (
                            <li key={o.id} className="flex items-center justify-between gap-2">
                              <span>{formatDateTime(o.previsto_em)}</span>
                              {pode('ocorrencias:cancelar') && (
                                <Button variant="ghost" size="sm" className="h-9 text-red-700 hover:bg-red-50"
                                  aria-label={`Cancelar ocorrência de ${formatDateTime(o.previsto_em)}`} onClick={() => setCancelar(o)}>
                                  <XCircle aria-hidden="true" /> Cancelar
                                </Button>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
        </>
      )}

      {cancelar && <DialogoCancelar ocorrencia={cancelar} aoFechar={() => setCancelar(null)} aoConfirmar={confirmarCancelamento} />}
    </div>
  )
}

function DialogoCancelar({ ocorrencia, aoFechar, aoConfirmar }: { ocorrencia: Ocorrencia; aoFechar: () => void; aoConfirmar: (motivo: string) => Promise<void> }) {
  const [motivo, setMotivo] = useState('')
  const [enviando, setEnviando] = useState(false)
  return (
    <Dialog open onOpenChange={a => { if (!a) aoFechar() }}>
      <DialogContent title="Cancelar ocorrência" description={`Cuidado previsto para ${formatDateTime(ocorrencia.previsto_em)}. A programação continua valendo para os demais horários.`}>
        <form onSubmit={async e => { e.preventDefault(); setEnviando(true); await aoConfirmar(motivo.trim()) }} className="space-y-4">
          <div className="space-y-2"><Label htmlFor="oc-motivo">Motivo do cancelamento</Label><textarea id="oc-motivo" required rows={3} className={AREA} value={motivo} onChange={e => setMotivo(e.target.value)} /></div>
          <Button type="submit" variant="destructive" className="w-full" disabled={!motivo.trim() || enviando}>
            {enviando && <Loader2 className="animate-spin" aria-hidden="true" />} Cancelar ocorrência
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
