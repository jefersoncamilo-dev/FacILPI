import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronDown, CircleDot, ClipboardSignature, FileText,
  HeartPulse, History, Loader2, RotateCcw, TriangleAlert, XCircle,
} from 'lucide-react'
import { api, formatDate, formatDateTime } from '../services/api'
import {
  admissoesApi, descreverPendencia, emAndamento, erroDeAdmissao, ETAPA_DA_PENDENCIA, ETAPAS,
  PENDENCIA_QUE_BLOQUEIA, proximaEtapa, ROTULO_SITUACAO,
  type Admissao, type Etapa, type HistoricoAdmissao, type Pendencia, type VerificacaoPendencias,
} from '../services/admissoes'
import { usePermissoes } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Label } from '../components/ui/input'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

/** Onde cada pendência é resolvida — o processo não duplica as fontes oficiais. */
const ONDE_RESOLVER: Partial<Record<Etapa, { rotulo: string; to?: string; emBreve?: boolean }>> = {
  pre_cadastro: { rotulo: 'Cadastro do residente', to: '/residentes' },
  documentacao: { rotulo: 'Documentos', to: '/documentos' },
  avaliacoes: { rotulo: 'Avaliações', to: '/avaliacoes' },
  quarto_leito: { rotulo: 'Quartos e leitos', to: '/quartos' },
  pais: { rotulo: 'Plano de cuidados (PAIS)', to: '/plano' },
}

type Acao = 'cancelar' | 'desistir' | 'reabrir' | 'contrato'
const DIALOGO: Record<Acao, { titulo: string; descricao: string; botao: string; destrutiva?: boolean }> = {
  cancelar: { titulo: 'Cancelar admissão', descricao: 'O processo é encerrado e todo o histórico é preservado.', botao: 'Cancelar admissão', destrutiva: true },
  desistir: { titulo: 'Registrar desistência', descricao: 'Use quando a família ou o residente desistirem. O histórico é preservado.', botao: 'Registrar desistência', destrutiva: true },
  reabrir: { titulo: 'Reabrir admissão', descricao: 'O processo volta para o pré-cadastro, com todo o histórico preservado.', botao: 'Reabrir' },
  contrato: { titulo: 'Registrar contrato', descricao: 'Informe como o contrato foi formalizado. Se ele estiver em Documentos, vincule-o.', botao: 'Registrar contrato' },
}

export function AdmissaoDetalhe() {
  const { id = '' } = useParams()
  const { pode } = usePermissoes()
  const [admissao, setAdmissao] = useState<Admissao | null>(null)
  const [verificacao, setVerificacao] = useState<VerificacaoPendencias | null>(null)
  const [nome, setNome] = useState<string | null>(null)
  const [falha, setFalha] = useState<'nao_encontrada' | 'erro' | null>(null)
  const [aviso, setAviso] = useState<{ tipo: 'error' | 'success' | 'warning'; texto: string; pendencias?: Pendencia[] } | null>(null)
  const [executando, setExecutando] = useState(false)
  const [dialogo, setDialogo] = useState<Acao | null>(null)

  const carregar = useCallback(async () => {
    try {
      const [a, v] = await Promise.all([admissoesApi.obter(id), admissoesApi.pendencias(id)])
      setAdmissao(a)
      setVerificacao(v)
      setFalha(null)
      api.get<{ nome: string }>(`/residentes/${a.residente_id}`).then(r => setNome(r.data?.nome || null)).catch(() => setNome(null))
    } catch (e: any) {
      setFalha(e?.response?.status === 404 ? 'nao_encontrada' : 'erro')
    }
  }, [id])

  useEffect(() => { carregar() }, [carregar])

  async function executar(fn: () => Promise<Admissao>, sucesso: string) {
    setExecutando(true)
    setAviso(null)
    try {
      await fn()
      await carregar()
      setAviso({ tipo: 'success', texto: sucesso })
      return true
    } catch (e) {
      const erro = erroDeAdmissao(e)
      if (erro.conflitoDeVersao) await carregar()
      setAviso({ tipo: erro.conflitoDeVersao ? 'warning' : 'error', texto: erro.mensagem, pendencias: erro.pendencias })
      return false
    } finally {
      setExecutando(false)
    }
  }

  if (falha === 'nao_encontrada') {
    return <ErrorState title="Admissão não encontrada" description={<>Ela pode ter sido removida ou pertence a outra instituição. <Link to="/admissoes" className="font-semibold text-primary underline">Voltar às admissões</Link></>} />
  }
  if (falha === 'erro') {
    return <ErrorState title="Não foi possível carregar a admissão" description="Tente novamente em instantes." onRetry={carregar} />
  }
  if (!admissao || !verificacao) {
    return (
      <div className="space-y-4" aria-label="Carregando admissão">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  const a = admissao
  const andamento = emAndamento(a.situacao)
  const proxima = proximaEtapa(a.situacao)
  const nomeResidente = nome || 'Residente'
  const bloqueio = andamento ? PENDENCIA_QUE_BLOQUEIA[a.situacao as Etapa] : undefined
  const pendenciasDaEtapa = verificacao.pendencias.filter(p => ETAPA_DA_PENDENCIA[p.codigo] === a.situacao)
  const bloqueadaAqui = !!bloqueio && verificacao.pendencias.some(p => p.codigo === bloqueio)

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Link to="/admissoes" className="inline-flex min-h-[32px] items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" aria-hidden="true" /> Admissões
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">{nomeResidente}</h1>
            <p className="text-sm text-muted-foreground">Admissão iniciada em {formatDate(a.iniciada_em)}</p>
          </div>
          <Badge variant={a.situacao === 'concluida' ? 'success' : andamento ? 'brand' : 'neutral'} className="text-sm">
            {ROTULO_SITUACAO[a.situacao]}
          </Badge>
        </div>
      </div>

      <Stepper admissao={a} verificacao={verificacao} />

      {aviso && (
        <Alert variant={aviso.tipo} title={aviso.tipo === 'success' ? undefined : aviso.texto}>
          {aviso.tipo === 'success' ? aviso.texto : aviso.pendencias?.length ? (
            <ul className="mt-1 list-disc space-y-0.5 pl-4">{aviso.pendencias.map((p, i) => <li key={i}>{descreverPendencia(p)}</li>)}</ul>
          ) : null}
        </Alert>
      )}

      {a.situacao === 'concluida' && <Conclusao admissao={a} nome={nomeResidente} />}

      {(a.situacao === 'cancelada' || a.situacao === 'desistencia') && (
        <section className="rounded-card border border-border bg-card p-5 shadow-card" aria-label="Processo encerrado">
          <h2 className="font-display text-base font-semibold text-foreground">
            {a.situacao === 'cancelada' ? 'Admissão cancelada' : 'Desistência registrada'} em {formatDate(a.cancelada_em || a.desistencia_em)}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">Motivo: {a.motivo_cancelamento || a.motivo_desistencia}</p>
          {pode('admissoes:reabrir') && (
            <Button variant="outline" className="mt-4" onClick={() => setDialogo('reabrir')}>
              <RotateCcw aria-hidden="true" /> Reabrir admissão
            </Button>
          )}
        </section>
      )}

      {andamento && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="space-y-4 rounded-card border border-border bg-card p-5 shadow-card lg:col-span-2" aria-label="Etapa atual">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Etapa atual</p>
              <h2 className="font-display text-lg font-semibold text-foreground">{ROTULO_SITUACAO[a.situacao]}</h2>
            </div>

            {a.situacao === 'contrato' && (
              <div className="rounded-lg border border-border p-4">
                {a.contrato_registrado_em ? (
                  <p className="flex items-center gap-2 text-sm text-foreground">
                    <CheckCircle2 className="size-4 text-emerald-700" aria-hidden="true" /> Contrato registrado em {formatDateTime(a.contrato_registrado_em)}
                  </p>
                ) : (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm text-muted-foreground">O contrato ainda não foi registrado neste processo.</p>
                    {pode('admissoes:atualizar') && (
                      <Button variant="outline" onClick={() => setDialogo('contrato')}>
                        <ClipboardSignature aria-hidden="true" /> Registrar contrato
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}

            {pendenciasDaEtapa.length > 0 ? (
              <ListaPendencias pendencias={pendenciasDaEtapa} residenteId={a.residente_id} />
            ) : (
              <p className="flex items-center gap-2 text-sm text-emerald-800">
                <Check className="size-4" aria-hidden="true" /> Nenhuma pendência nesta etapa.
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
              {proxima && pode('admissoes:avancar') && (
                <Button
                  disabled={executando || bloqueadaAqui}
                  onClick={() => executar(() => admissoesApi.avancar(a, proxima), `Admissão avançou para ${ROTULO_SITUACAO[proxima]}.`)}
                >
                  {executando ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
                  Avançar para {ROTULO_SITUACAO[proxima]} <ArrowRight aria-hidden="true" />
                </Button>
              )}
              {a.situacao === 'pais' && pode('admissoes:concluir') && (
                <Button
                  disabled={executando || !verificacao.requisitos_cumpridos}
                  onClick={() => executar(() => admissoesApi.concluir(a), 'Admissão concluída.')}
                >
                  {executando ? <Loader2 className="animate-spin" aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
                  Concluir admissão
                </Button>
              )}
              {bloqueadaAqui && <p className="text-sm text-muted-foreground">Resolva a pendência desta etapa para avançar.</p>}
              {a.situacao === 'pais' && !verificacao.requisitos_cumpridos && (
                <p className="text-sm text-muted-foreground">A conclusão exige todas as pendências resolvidas.</p>
              )}
            </div>
          </section>

          <aside className="space-y-6">
            <section className="rounded-card border border-border bg-card p-5 shadow-card" aria-label="Situação geral">
              <h2 className="font-display text-base font-semibold text-foreground">Para concluir</h2>
              {verificacao.requisitos_cumpridos ? (
                <p className="mt-2 flex items-center gap-2 text-sm text-emerald-800"><Check className="size-4" aria-hidden="true" /> Todos os requisitos cumpridos.</p>
              ) : (
                <ListaPendencias pendencias={verificacao.pendencias} compacta />
              )}
              <p className="mt-3 text-xs text-muted-foreground">Verificado em {formatDate(verificacao.data_verificacao)}.</p>
            </section>
            {pode('admissoes:cancelar') && (
              <section className="rounded-card border border-border bg-card p-5 shadow-card" aria-label="Encerrar processo">
                <h2 className="font-display text-base font-semibold text-foreground">Encerrar processo</h2>
                <p className="mt-1 text-xs text-muted-foreground">O histórico é sempre preservado.</p>
                <div className="mt-3 grid gap-2">
                  <Button variant="outline" onClick={() => setDialogo('desistir')}>Registrar desistência</Button>
                  <Button variant="ghost" className="text-red-700 hover:bg-red-50" onClick={() => setDialogo('cancelar')}>
                    <XCircle aria-hidden="true" /> Cancelar admissão
                  </Button>
                </div>
              </section>
            )}
          </aside>
        </div>
      )}

      <Historico id={a.id} versao={a.lock_version} />

      {dialogo && (
        <DialogoMotivo
          acao={dialogo}
          documentos={verificacao.documentos}
          aoFechar={() => setDialogo(null)}
          aoConfirmar={async (motivo, documentoId) => {
            const mapa = {
              cancelar: () => admissoesApi.cancelar(a, motivo),
              desistir: () => admissoesApi.desistir(a, motivo),
              reabrir: () => admissoesApi.reabrir(a, motivo),
              contrato: () => admissoesApi.registrarContrato(a, motivo, documentoId),
            }
            const textos = { cancelar: 'Admissão cancelada.', desistir: 'Desistência registrada.', reabrir: 'Admissão reaberta no pré-cadastro.', contrato: 'Contrato registrado.' }
            // Fecha sempre: sucesso ou erro aparecem na página, fora do overlay.
            setDialogo(null)
            await executar(mapa[dialogo], textos[dialogo])
          }}
        />
      )}
    </div>
  )
}

function Stepper({ admissao: a, verificacao }: { admissao: Admissao; verificacao: VerificacaoPendencias }) {
  const atual = ETAPAS.indexOf(a.situacao as Etapa)
  const concluida = a.situacao === 'concluida'
  const etapasComPendencia = new Set(verificacao.pendencias.map(p => ETAPA_DA_PENDENCIA[p.codigo]))
  const passos = [...ETAPAS, 'concluida' as const]
  return (
    <nav aria-label="Etapas da admissão">
      <ol className="grid grid-cols-4 gap-x-2 gap-y-4 sm:grid-cols-8">
        {passos.map((etapa, i) => {
          const feito = concluida || (atual >= 0 && i < atual)
          const corrente = etapa === a.situacao
          const pendente = etapa !== 'concluida' && !feito && etapasComPendencia.has(etapa)
          return (
            <li key={etapa} aria-current={corrente ? 'step' : undefined} className="flex flex-col items-center gap-1.5 text-center">
              <span
                className={cn(
                  'flex size-8 items-center justify-center rounded-full border-2 text-xs font-semibold',
                  feito && 'border-brand bg-brand text-white',
                  corrente && !feito && 'border-brand bg-brand-soft text-primary ring-4 ring-brand/15',
                  !feito && !corrente && 'border-border bg-card text-muted-foreground',
                )}
              >
                {feito ? <Check className="size-4" aria-hidden="true" /> : i + 1}
              </span>
              <span className={cn('text-[11px] leading-tight', corrente ? 'font-semibold text-foreground' : 'text-muted-foreground')}>
                {ROTULO_SITUACAO[etapa]}
              </span>
              <span className="sr-only">{feito ? 'concluída' : corrente ? 'etapa atual' : 'pendente'}</span>
              {pendente && (
                <span className="inline-flex items-center gap-0.5 text-[10px] font-medium text-orange-800">
                  <CircleDot className="size-3" aria-hidden="true" /> pendência
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** Avaliação requerida casa por tipo/instrumento exatos: o link já leva o formulário preenchido. */
function destino(p: Pendencia, to: string, residenteId?: string) {
  if (p.codigo !== 'avaliacao_requerida_pendente' || !residenteId) return to
  const q = new URLSearchParams({ residente: residenteId, novo: '1', tipo: p.tipo || '' })
  if (p.instrumento) q.set('instrumento', p.instrumento)
  return `${to}?${q}`
}

function ListaPendencias({ pendencias, compacta = false, residenteId }: { pendencias: Pendencia[]; compacta?: boolean; residenteId?: string }) {
  return (
    <ul className={cn('space-y-2', compacta && 'mt-2')}>
      {pendencias.map((p, i) => {
        const etapa = ETAPA_DA_PENDENCIA[p.codigo]
        const onde = ONDE_RESOLVER[etapa]
        return (
          <li key={`${p.codigo}-${p.referencia_id ?? i}`} className="flex items-start gap-2.5 rounded-lg bg-orange-50/60 px-3 py-2 text-sm">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-orange-700" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="text-foreground">{descreverPendencia(p)}</p>
              {compacta ? (
                <p className="text-xs text-muted-foreground">Etapa: {ROTULO_SITUACAO[etapa]}</p>
              ) : onde ? (
                onde.to ? (
                  <Link to={destino(p, onde.to, residenteId)} className="inline-flex min-h-[28px] items-center text-xs font-semibold text-primary hover:underline">Resolver em {onde.rotulo}</Link>
                ) : (
                  <p className="text-xs text-muted-foreground">Resolvido em {onde.rotulo} — tela em construção.</p>
                )
              ) : null}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function Conclusao({ admissao: a, nome }: { admissao: Admissao; nome: string }) {
  const { pode } = usePermissoes()
  const acoes = [
    { to: `/residentes/${a.residente_id}`, label: 'Abrir prontuário', icon: FileText, permissao: 'residentes:ler' },
    { to: '/sinais', label: 'Registrar sinais vitais', icon: HeartPulse, permissao: 'sinais_vitais:criar' },
    { to: '/intercorrencias', label: 'Registrar intercorrência', icon: TriangleAlert, permissao: 'intercorrencias:criar' },
  ].filter(x => pode(x.permissao))
  return (
    <section className="rounded-card border border-emerald-200 bg-emerald-50/50 p-5 shadow-card" aria-label="Admissão concluída">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="mt-0.5 size-6 shrink-0 text-emerald-700" aria-hidden="true" />
        <div>
          <h2 className="font-display text-lg font-semibold text-foreground">Admissão concluída</h2>
          <p className="text-sm text-muted-foreground">
            {nome} foi admitido(a) em {formatDate(a.concluida_em)} e agora aparece como residente ativo.
          </p>
        </div>
      </div>
      {acoes.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {acoes.map(x => (
            <Button key={x.label} asChild variant="outline">
              <Link to={x.to}><x.icon aria-hidden="true" /> {x.label}</Link>
            </Button>
          ))}
        </div>
      )}
    </section>
  )
}

function Historico({ id, versao }: { id: string; versao: number }) {
  const [aberto, setAberto] = useState(false)
  const [itens, setItens] = useState<HistoricoAdmissao[] | null | 'erro'>(null)

  useEffect(() => {
    if (!aberto) return
    admissoesApi.historico(id).then(setItens).catch(() => setItens('erro'))
  }, [aberto, id, versao])

  return (
    <section className="rounded-card border border-border bg-card shadow-card" aria-label="Histórico">
      <button
        type="button"
        onClick={() => setAberto(v => !v)}
        aria-expanded={aberto}
        className="flex min-h-[52px] w-full items-center justify-between gap-3 px-5 text-left"
      >
        <span className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
          <History className="size-4 text-muted-foreground" aria-hidden="true" /> Histórico do processo
        </span>
        <ChevronDown className={cn('size-4 text-muted-foreground transition-transform', aberto && 'rotate-180')} aria-hidden="true" />
      </button>
      {aberto && (
        <div className="border-t border-border px-5 py-4">
          {itens === null && <Skeleton className="h-16 w-full" />}
          {itens === 'erro' && <p className="text-sm text-muted-foreground">Não foi possível carregar o histórico.</p>}
          {Array.isArray(itens) && (
            <ol className="space-y-3">
              {itens.map(h => (
                <li key={h.id ?? h.lock_version} className="text-sm">
                  <p className="text-foreground">
                    {h.etapa_origem ? `${ROTULO_SITUACAO[h.etapa_origem]} → ` : ''}{ROTULO_SITUACAO[h.etapa_destino] ?? h.etapa_destino}
                    <span className="text-muted-foreground"> · {h.acao}</span>
                  </p>
                  {h.motivo && <p className="text-xs text-muted-foreground">Motivo: {h.motivo}</p>}
                  {h.created_at && <p className="text-xs text-muted-foreground">{formatDateTime(h.created_at)}</p>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  )
}

function DialogoMotivo({
  acao,
  documentos,
  aoFechar,
  aoConfirmar,
}: {
  acao: Acao
  documentos: VerificacaoPendencias['documentos']
  aoFechar: () => void
  aoConfirmar: (motivo: string, documentoId?: string) => Promise<void>
}) {
  const [motivo, setMotivo] = useState('')
  const [documentoId, setDocumentoId] = useState('')
  const [enviando, setEnviando] = useState(false)
  const cfg = DIALOGO[acao]

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    await aoConfirmar(motivo.trim(), documentoId || undefined)
    setEnviando(false)
  }

  return (
    <Dialog open onOpenChange={aberto => { if (!aberto) aoFechar() }}>
      <DialogContent title={cfg.titulo} description={cfg.descricao}>
        <form onSubmit={enviar} className="space-y-4">
          {acao === 'contrato' && documentos.length > 0 && (
            <div className="space-y-2">
              <Label htmlFor="contrato-documento">Documento do contrato (opcional)</Label>
              <select
                id="contrato-documento"
                value={documentoId}
                onChange={e => setDocumentoId(e.target.value)}
                className="flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              >
                <option value="">Sem documento vinculado</option>
                {documentos.map(d => <option key={d.id} value={d.id}>{d.tipo} · {d.situacao}</option>)}
              </select>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="acao-motivo">{acao === 'contrato' ? 'Como foi formalizado' : 'Motivo'}</Label>
            <textarea
              id="acao-motivo"
              required
              rows={3}
              maxLength={2000}
              value={motivo}
              onChange={e => setMotivo(e.target.value)}
              className="w-full rounded-lg border border-input bg-card px-3 py-2 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            />
          </div>
          <Button type="submit" variant={cfg.destrutiva ? 'destructive' : 'default'} className="w-full" disabled={!motivo.trim() || enviando}>
            {enviando ? <><Loader2 className="animate-spin" aria-hidden="true" /> Salvando…</> : cfg.botao}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
