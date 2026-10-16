import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ClipboardCheck, Loader2, Plus, Search, ShieldCheck } from 'lucide-react'
import { api, formatDate, formatDateTime, mensagemDeErro } from '../services/api'
import {
  avaliacoesApi, GRAUS, grausApi, lerRespostas, situacaoValidade,
  type Avaliacao, type Grau, type GrauDependencia, type NovaAvaliacao,
} from '../services/avaliacoes'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { EmptyState, ErrorState } from '../components/ui/states'

type ResidenteRef = { id: string; nome: string }
const SELECT = 'flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40'
const AREA = 'w-full rounded-lg border border-input bg-card px-3 py-2 text-[16px] focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40'

/** Avaliações (UX-06 / #79). Substitui o placeholder de /avaliacoes. */
export function Avaliacoes() {
  const { pode } = usePermissoesOuPadrao()
  const [params, setParams] = useSearchParams()
  const residenteFiltro = params.get('residente') || ''
  const [avaliacoes, setAvaliacoes] = useState<Avaliacao[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [residentes, setResidentes] = useState<ResidenteRef[]>([])
  const [busca, setBusca] = useState('')
  const [aberta, setAberta] = useState<Avaliacao | null>(null)
  // ?novo=1&tipo=&instrumento= chega da pendência da admissão: o requisito
  // casa por texto exato, então o formulário já vem com o tipo pedido.
  const [nova, setNova] = useState<Partial<NovaAvaliacao> | null>(() =>
    params.get('novo') ? { residente_id: residenteFiltro, tipo: params.get('tipo') || '', instrumento: params.get('instrumento') || '' } : null)
  const [aviso, setAviso] = useState('')

  const carregar = useCallback(async () => {
    try {
      setAvaliacoes(await avaliacoesApi.listar())
      setErro(null)
    } catch (e: any) {
      setAvaliacoes(null)
      setErro(e?.response?.status === 403 ? 'proibido' : mensagemDeErro(e, 'Não foi possível carregar as avaliações.'))
    }
  }, [])

  useEffect(() => { carregar() }, [carregar])
  useEffect(() => {
    api.get<ResidenteRef[]>('/residentes/').then(r => setResidentes(r.data || [])).catch(() => setResidentes([]))
  }, [])

  const nomes = useMemo(() => new Map(residentes.map(r => [r.id, r.nome])), [residentes])
  const usados = useMemo(() => ({
    tipos: [...new Set((avaliacoes || []).map(a => a.tipo))].sort(),
    instrumentos: [...new Set((avaliacoes || []).map(a => a.instrumento).filter(Boolean) as string[])].sort(),
  }), [avaliacoes])
  const visiveis = useMemo(() => {
    const termo = busca.trim().toLowerCase()
    return (avaliacoes || []).filter(a =>
      (!residenteFiltro || a.residente_id === residenteFiltro)
      && (!termo || [a.tipo, a.instrumento, a.classificacao, nomes.get(a.residente_id)].some(t => t?.toLowerCase().includes(termo))))
  }, [avaliacoes, residenteFiltro, busca, nomes])

  if (erro === 'proibido') return <ErrorState title="Sem acesso às avaliações" description="Seu perfil não permite consultar avaliações nesta ILPI." />
  if (erro) return <ErrorState title="Não foi possível carregar as avaliações" description={`${erro} Isso não significa que não há avaliações.`} onRetry={carregar} />

  function filtrarResidente(id: string) {
    const p = new URLSearchParams(params)
    if (id) p.set('residente', id)
    else p.delete('residente')
    p.delete('novo'); p.delete('tipo'); p.delete('instrumento')
    setParams(p, { replace: true })
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Avaliações</h1>
          <p className="text-sm text-muted-foreground">Instrumentos aplicados aos residentes, como foram registrados.</p>
        </div>
        {pode('avaliacoes:criar') && avaliacoes !== null && (
          <Button onClick={() => { setAviso(''); setNova({ residente_id: residenteFiltro }) }}><Plus aria-hidden="true" /> Nova avaliação</Button>
        )}
      </div>

      {aviso && <Alert variant="success">{aviso}</Alert>}

      {avaliacoes === null ? (
        <div className="space-y-3" aria-label="Carregando avaliações">{[0, 1, 2].map(i => <Skeleton key={i} className="h-20" />)}</div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="av-residente">Residente</Label>
              <select id="av-residente" className={SELECT} value={residenteFiltro} onChange={e => filtrarResidente(e.target.value)}>
                <option value="">Todos os residentes</option>
                {[...residentes].sort((a, b) => a.nome.localeCompare(b.nome)).map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="av-busca">Buscar</Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <Input id="av-busca" className="pl-9" placeholder="Tipo, instrumento, classificação…" value={busca} onChange={e => setBusca(e.target.value)} />
              </div>
            </div>
          </div>

          {visiveis.length === 0 ? (
            <EmptyState icon={ClipboardCheck}
              title={avaliacoes.length === 0 ? 'Nenhuma avaliação registrada' : 'Nenhuma avaliação neste filtro'}
              description={avaliacoes.length === 0 ? 'Registre aqui os instrumentos aplicados, com pontuação e classificação como constam no instrumento.' : undefined}
              action={avaliacoes.length === 0 && pode('avaliacoes:criar') ? <Button onClick={() => setNova({ residente_id: residenteFiltro })}><Plus aria-hidden="true" /> Nova avaliação</Button> : undefined} />
          ) : (
            <ul className="space-y-2">
              {visiveis.map(a => {
                const validade = situacaoValidade(a.validade)
                return (
                  <li key={a.id}>
                    <button type="button" onClick={() => { setAviso(''); setAberta(a) }}
                      className="flex min-h-[72px] w-full items-start gap-4 rounded-card border border-border bg-card px-4 py-3 text-left shadow-card transition-colors hover:border-brand/50 sm:px-5">
                      <span aria-hidden="true" className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-primary">
                        <ClipboardCheck className="size-5" />
                      </span>
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-medium text-foreground">{a.tipo}{a.instrumento ? ` · ${a.instrumento}` : ''}</p>
                          {validade === 'vencida' && <Badge variant="warning">Vencida em {formatDate(a.validade)}</Badge>}
                          {validade === 'vigente' && <Badge variant="success">Válida até {formatDate(a.validade)}</Badge>}
                        </div>
                        <p className="text-sm text-foreground">{nomes.get(a.residente_id) || 'Residente'}</p>
                        <p className="text-xs text-muted-foreground">
                          {[formatDateTime(a.data), a.profissional,
                            a.pontuacao !== null ? `pontuação ${a.pontuacao}` : null,
                            a.classificacao ? `classificação: ${a.classificacao}` : null].filter(Boolean).join(' · ')}
                        </p>
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}

      {nova && (
        <NovaAvaliacaoDialogo inicial={nova} residentes={residentes} usados={usados} aoFechar={() => setNova(null)}
          aoCriar={a => {
            setNova(null)
            setAviso(`Avaliação registrada para ${nomes.get(a.residente_id) || 'o residente'}.`)
            filtrarResidente(residenteFiltro)
            carregar()
          }} />
      )}
      {aberta && <DetalheAvaliacao avaliacao={aberta} nome={nomes.get(aberta.residente_id) || 'Residente'} aoFechar={() => setAberta(null)} />}
    </div>
  )
}

function NovaAvaliacaoDialogo({ inicial, residentes, usados, aoFechar, aoCriar }: {
  inicial: Partial<NovaAvaliacao>; residentes: ResidenteRef[]; usados: { tipos: string[]; instrumentos: string[] }
  aoFechar: () => void; aoCriar: (a: Avaliacao) => void
}) {
  const [f, setF] = useState({
    residente_id: inicial.residente_id || '', tipo: inicial.tipo || '', instrumento: inicial.instrumento || '',
    pontuacao: '', classificacao: '', data: '', validade: '', observacoes: '',
  })
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)
  const campo = (k: keyof typeof f) => ({ value: f[k], onChange: (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value }) })

  async function salvar(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    const dados: NovaAvaliacao = { residente_id: f.residente_id, tipo: f.tipo.trim() }
    for (const k of ['instrumento', 'classificacao', 'validade', 'observacoes'] as const) {
      if (f[k].trim()) dados[k] = f[k].trim()
    }
    if (f.pontuacao.trim()) {
      const n = Number(f.pontuacao.replace(',', '.'))
      if (!Number.isFinite(n)) { setErro('Pontuação deve ser um número.'); return }
      dados.pontuacao = n
    }
    // datetime-local é hora local; toISOString envia com fuso. Em branco, o backend usa agora.
    if (f.data) dados.data = new Date(f.data).toISOString()
    setSalvando(true)
    try {
      aoCriar(await avaliacoesApi.criar(dados))
    } catch (err) {
      setErro(mensagemDeErro(err, 'Não foi possível registrar a avaliação.'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open onOpenChange={a => { if (!a) aoFechar() }}>
      <DialogContent title="Nova avaliação" description="Registre o instrumento como foi aplicado. A tela não calcula pontuação nem classificação.">
        <form onSubmit={salvar} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="na-residente">Residente</Label>
            <select id="na-residente" required className={SELECT} {...campo('residente_id')}>
              <option value="">Selecione…</option>
              {[...residentes].sort((a, b) => a.nome.localeCompare(b.nome)).map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="na-tipo">Tipo</Label>
              <Input id="na-tipo" required list="na-tipos" {...campo('tipo')} />
              <datalist id="na-tipos">{usados.tipos.map(t => <option key={t} value={t} />)}</datalist>
            </div>
            <div className="space-y-2">
              <Label htmlFor="na-instrumento">Instrumento (opcional)</Label>
              <Input id="na-instrumento" list="na-instrumentos" {...campo('instrumento')} />
              <datalist id="na-instrumentos">{usados.instrumentos.map(t => <option key={t} value={t} />)}</datalist>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="na-pontuacao">Pontuação (opcional)</Label>
              <Input id="na-pontuacao" inputMode="decimal" {...campo('pontuacao')} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="na-classificacao">Classificação (opcional)</Label>
              <Input id="na-classificacao" {...campo('classificacao')} />
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="na-data">Aplicada em (em branco = agora)</Label>
              <Input id="na-data" type="datetime-local" {...campo('data')} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="na-validade">Válida até (opcional)</Label>
              <Input id="na-validade" type="date" {...campo('validade')} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="na-observacoes">Observações (opcional)</Label>
            <textarea id="na-observacoes" rows={3} className={AREA} {...campo('observacoes')} />
          </div>
          {erro && <Alert variant="error">{erro}</Alert>}
          <Button type="submit" className="w-full" disabled={!f.residente_id || !f.tipo.trim() || salvando}>
            {salvando ? <><Loader2 className="animate-spin" aria-hidden="true" /> Registrando…</> : 'Registrar avaliação'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DetalheAvaliacao({ avaliacao: a, nome, aoFechar }: { avaliacao: Avaliacao; nome: string; aoFechar: () => void }) {
  const { pode } = usePermissoesOuPadrao()
  const respostas = lerRespostas(a.respostas)
  const validade = situacaoValidade(a.validade)
  const [graus, setGraus] = useState<GrauDependencia[] | null | 'sem_acesso'>(null)
  const [confirmando, setConfirmando] = useState(false)
  const [resultado, setResultado] = useState<{ tipo: 'success' | 'error'; texto: string } | null>(null)

  const carregarGraus = useCallback(() => {
    if (!pode('grau_dependencia:ler')) { setGraus('sem_acesso'); return }
    grausApi.listar(a.residente_id).then(setGraus).catch(() => setGraus('sem_acesso'))
  }, [a.residente_id, pode])
  useEffect(() => { carregarGraus() }, [carregarGraus])

  const ativo = Array.isArray(graus) ? graus.find(g => g.situacao === 'ativo') || null : null
  const desta = ativo?.avaliacao_id === a.id

  const linhas: [string, string | null][] = [
    ['Residente', nome],
    ['Aplicada em', formatDateTime(a.data)],
    ['Profissional', a.profissional],
    ['Pontuação', a.pontuacao !== null ? String(a.pontuacao) : null],
    ['Classificação registrada', a.classificacao],
    ['Validade', a.validade ? `${formatDate(a.validade)}${validade === 'vencida' ? ' (vencida)' : ''}` : null],
  ]

  return (
    <Dialog open onOpenChange={o => { if (!o) aoFechar() }}>
      <DialogContent title={`${a.tipo}${a.instrumento ? ` · ${a.instrumento}` : ''}`}>
        <div className="space-y-4">
          <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
            {linhas.filter(([, v]) => v).map(([k, v]) => (
              <div key={k}><dt className="text-xs text-muted-foreground">{k}</dt><dd className="font-medium text-foreground">{v}</dd></div>
            ))}
          </dl>
          {respostas && (
            <section aria-label="Respostas" className="space-y-1.5">
              <h3 className="text-sm font-semibold text-foreground">Respostas</h3>
              {'pares' in respostas ? (
                <dl className="divide-y divide-border rounded-lg border border-border text-sm">
                  {respostas.pares.map(([k, v]) => <div key={k} className="flex justify-between gap-3 px-3 py-1.5"><dt className="text-muted-foreground">{k}</dt><dd className="text-right font-medium">{v}</dd></div>)}
                </dl>
              ) : <p className="whitespace-pre-wrap rounded-lg bg-muted px-3 py-2 text-sm">{respostas.texto}</p>}
            </section>
          )}
          {a.observacoes && <p className="whitespace-pre-wrap rounded-lg bg-muted px-3 py-2 text-sm"><strong className="font-semibold">Observações:</strong> {a.observacoes}</p>}

          {graus !== 'sem_acesso' && (
            <section aria-label="Grau de dependência" className="space-y-2 rounded-lg border border-border p-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground"><ShieldCheck className="size-4 text-primary" aria-hidden="true" /> Grau de dependência oficial</h3>
              {graus === null ? <Skeleton className="h-5 w-40" /> : (
                <p className="text-sm text-foreground">
                  {ativo ? <>{ativo.classificacao}{desta ? ', confirmado a partir desta avaliação' : ''}{ativo.confirmado_em ? ` · desde ${formatDate(ativo.confirmado_em)}` : ''}</> : 'Não definido'}
                </p>
              )}
              {resultado && <Alert variant={resultado.tipo}>{resultado.texto}</Alert>}
              {Array.isArray(graus) && !desta && pode('grau_dependencia:criar') && !confirmando && (
                <Button variant="outline" size="sm" className="h-10" onClick={() => { setResultado(null); setConfirmando(true) }}>Confirmar grau a partir desta avaliação</Button>
              )}
              {confirmando && (
                <ConfirmarGrau avaliacao={a} ativo={ativo} aoCancelar={() => setConfirmando(false)}
                  aoConfirmar={g => {
                    setConfirmando(false)
                    setResultado({ tipo: 'success', texto: `Grau de dependência confirmado: ${g.classificacao}.${ativo ? ` O anterior (${ativo.classificacao}) foi substituído e continua no histórico.` : ''}` })
                    carregarGraus()
                  }}
                  aoFalhar={texto => setResultado({ tipo: 'error', texto })} />
              )}
            </section>
          )}
          <Link to={`/residentes/${a.residente_id}`} className="inline-flex min-h-[32px] items-center text-sm font-medium text-primary hover:underline">Abrir prontuário de {nome}</Link>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ConfirmarGrau({ avaliacao: a, ativo, aoCancelar, aoConfirmar, aoFalhar }: {
  avaliacao: Avaliacao; ativo: GrauDependencia | null; aoCancelar: () => void
  aoConfirmar: (g: GrauDependencia) => void; aoFalhar: (texto: string) => void
}) {
  // A classificação da avaliação só pré-seleciona quando é literalmente um dos
  // graus oficiais; a decisão continua sendo da pessoa que confirma.
  const sugerido = (GRAUS as readonly string[]).includes(a.classificacao || '') ? (a.classificacao as Grau) : ''
  const [classificacao, setClassificacao] = useState<Grau | ''>(sugerido)
  const [justificativa, setJustificativa] = useState('')
  const [validade, setValidade] = useState('')
  const [salvando, setSalvando] = useState(false)

  async function confirmar(e: React.FormEvent) {
    e.preventDefault()
    if (!classificacao) return
    setSalvando(true)
    try {
      aoConfirmar(await grausApi.confirmarPorAvaliacao({
        residente_id: a.residente_id, avaliacao_id: a.id, classificacao, justificativa: justificativa.trim(),
        ...(validade ? { validade } : {}),
      }))
    } catch (err) {
      aoFalhar(mensagemDeErro(err, 'Não foi possível confirmar o grau.'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <form onSubmit={confirmar} className="space-y-3 border-t border-border pt-3">
      {a.classificacao && <p className="text-xs text-muted-foreground">Classificação registrada na avaliação: <strong>{a.classificacao}</strong> (sugestão; a confirmação é sua).</p>}
      {ativo && <Alert variant="warning">Ao confirmar, o grau atual ({ativo.classificacao}) passa a “substituído” e fica no histórico.</Alert>}
      <div className="space-y-2">
        <Label htmlFor="cg-classificacao">Grau confirmado</Label>
        <select id="cg-classificacao" required className={SELECT} value={classificacao} onChange={e => setClassificacao(e.target.value as Grau)}>
          <option value="">Selecione…</option>
          {GRAUS.map(g => <option key={g} value={g}>{g}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="cg-justificativa">Justificativa</Label>
        <textarea id="cg-justificativa" required rows={2} className={AREA} value={justificativa} onChange={e => setJustificativa(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="cg-validade">Válido até (opcional)</Label>
        <Input id="cg-validade" type="date" value={validade} onChange={e => setValidade(e.target.value)} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={!classificacao || !justificativa.trim() || salvando}>
          {salvando && <Loader2 className="animate-spin" aria-hidden="true" />} Confirmar grau
        </Button>
        <Button type="button" variant="ghost" onClick={aoCancelar}>Cancelar</Button>
      </div>
    </form>
  )
}
