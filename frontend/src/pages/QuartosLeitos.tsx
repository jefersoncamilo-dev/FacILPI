import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRightLeft, BedDouble, DoorOpen, History, Loader2, LogOut, Plus, UserPlus } from 'lucide-react'
import { api, formatDate, formatDateTime, mensagemDeErro } from '../services/api'
import {
  ausenciasApi, estadoDoLeito, leitosApi, nomeDoLeito, ROTULO_AUSENCIA, ROTULO_SITUACAO_LEITO, SITUACOES_EDITAVEIS,
  type Ausencia, type EstadoLeito, type Leito, type MovimentacaoLeito, type SituacaoLeito, type TipoAusencia,
} from '../services/leitos'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { EmptyState, ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

type ResidenteRef = { id: string; nome: string }
type Aba = 'leitos' | 'ausencias'
type FiltroLeito = 'todos' | EstadoLeito

const ROTULO_ESTADO: Record<EstadoLeito, string> = {
  ocupado: 'Ocupado', livre: 'Livre', indisponivel: 'Indisponível', inativo: 'Inativo',
}
const SELECT = 'flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40'

/** Quartos, leitos e ausências (UX-08 / #81). Substitui o placeholder de /quartos. */
export function QuartosLeitos() {
  const { pode } = usePermissoesOuPadrao()
  const [leitos, setLeitos] = useState<Leito[] | null>(null)
  const [erro, setErro] = useState<'proibido' | string | null>(null)
  const [ausencias, setAusencias] = useState<Ausencia[] | null>(null)
  const [residentes, setResidentes] = useState<ResidenteRef[]>([])
  const [aba, setAba] = useState<Aba>('leitos')
  const [filtro, setFiltro] = useState<FiltroLeito>('todos')
  const [aberto, setAberto] = useState<Leito | null>(null)
  const [novoLeito, setNovoLeito] = useState(false)
  const [novaAusencia, setNovaAusencia] = useState(false)
  const [aviso, setAviso] = useState<{ tipo: 'success' | 'error'; texto: string } | null>(null)

  const carregar = useCallback(async () => {
    try {
      setLeitos(await leitosApi.listar())
      setErro(null)
    } catch (e: any) {
      setLeitos(null)
      setErro(e?.response?.status === 403 ? 'proibido' : mensagemDeErro(e, 'Não foi possível carregar os leitos.'))
    }
    if (pode('ausencias:ler')) {
      ausenciasApi.listar().then(setAusencias).catch(() => setAusencias(null))
    }
  }, [pode])

  useEffect(() => { carregar() }, [carregar])
  useEffect(() => {
    api.get<ResidenteRef[]>('/residentes/').then(r => setResidentes(r.data || [])).catch(() => setResidentes([]))
  }, [])

  const nomes = useMemo(() => new Map(residentes.map(r => [r.id, r.nome])), [residentes])
  const ausenciaAtiva = useMemo(() => new Map((ausencias || []).filter(a => !a.data_fim).map(a => [a.residente_id, a])), [ausencias])

  async function executar(acao: () => Promise<unknown>, sucesso: string) {
    setAviso(null)
    try {
      await acao()
      setAberto(null)
      await carregar()
      setAviso({ tipo: 'success', texto: sucesso })
      return true
    } catch (e) {
      setAberto(null)
      await carregar()
      setAviso({ tipo: 'error', texto: mensagemDeErro(e, 'Não foi possível concluir a ação.') })
      return false
    }
  }

  if (erro === 'proibido') {
    return <ErrorState title="Sem acesso a quartos e leitos" description="Seu perfil não permite consultar os leitos desta ILPI." />
  }
  if (erro) {
    return <ErrorState title="Não foi possível carregar os leitos" description={`${erro} Isso não significa que não há leitos cadastrados.`} onRetry={carregar} />
  }

  const lista = leitos || []
  const contagem = (e: EstadoLeito) => lista.filter(l => estadoDoLeito(l) === e).length
  const ativos = lista.filter(l => estadoDoLeito(l) !== 'inativo').length
  const visiveis = lista.filter(l => filtro === 'todos' || estadoDoLeito(l) === filtro)
  const porQuarto = new Map<string, Leito[]>()
  for (const l of visiveis.sort((a, b) => `${a.unidade}${a.quarto}${a.leito}`.localeCompare(`${b.unidade}${b.quarto}${b.leito}`))) {
    const chave = [l.unidade, `Quarto ${l.quarto}`].filter(Boolean).join(' · ')
    porQuarto.set(chave, [...(porQuarto.get(chave) || []), l])
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Quartos e leitos</h1>
          <p className="text-sm text-muted-foreground">Ocupação, disponibilidade e ausências dos residentes.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {pode('ausencias:criar') && (
            <Button variant="outline" onClick={() => setNovaAusencia(true)}><DoorOpen aria-hidden="true" /> Registrar ausência</Button>
          )}
          {pode('quartos_leitos:criar') && (
            <Button onClick={() => setNovoLeito(true)}><Plus aria-hidden="true" /> Novo leito</Button>
          )}
        </div>
      </div>

      {aviso && <Alert variant={aviso.tipo}>{aviso.texto}</Alert>}

      {leitos === null ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Carregando leitos">
          {[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-20" />)}
        </div>
      ) : (
        <>
          <section aria-label="Resumo da ocupação" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Resumo titulo="Ocupados" valor={`${contagem('ocupado')}/${ativos}`} />
            <Resumo titulo="Livres" valor={contagem('livre')} />
            <Resumo titulo="Indisponíveis" valor={contagem('indisponivel')} />
            {ausencias !== null && <Resumo titulo="Ausentes agora" valor={ausenciaAtiva.size} />}
          </section>

          {ausencias !== null && (
            <div role="tablist" aria-label="Visão" className="flex w-fit gap-1 rounded-lg bg-muted p-1">
              {([['leitos', 'Leitos'], ['ausencias', 'Ausências']] as [Aba, string][]).map(([id, rotulo]) => (
                <button key={id} role="tab" aria-selected={aba === id} onClick={() => setAba(id)}
                  className={cn('min-h-[40px] rounded-md px-4 text-sm font-medium', aba === id ? 'bg-card text-foreground shadow-sm' : 'text-slate-600 hover:text-foreground')}>
                  {rotulo}
                </button>
              ))}
            </div>
          )}

          {aba === 'leitos' && (
            <>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar leitos">
                {(['todos', 'livre', 'ocupado', 'indisponivel', 'inativo'] as FiltroLeito[]).map(f => (
                  <button key={f} type="button" aria-pressed={filtro === f} onClick={() => setFiltro(f)}
                    className={cn('min-h-[36px] rounded-full border px-3 text-sm font-medium',
                      filtro === f ? 'border-brand bg-accent text-accent-foreground' : 'border-border bg-card text-muted-foreground hover:text-foreground')}>
                    {f === 'todos' ? `Todos (${lista.length})` : `${ROTULO_ESTADO[f]} (${contagem(f)})`}
                  </button>
                ))}
              </div>

              {lista.length === 0 ? (
                <EmptyState icon={BedDouble} title="Nenhum leito cadastrado"
                  description="Cadastre os quartos e leitos da instituição para acompanhar a ocupação."
                  action={pode('quartos_leitos:criar') ? <Button onClick={() => setNovoLeito(true)}><Plus aria-hidden="true" /> Novo leito</Button> : undefined} />
              ) : visiveis.length === 0 ? (
                <EmptyState icon={BedDouble} title="Nenhum leito neste filtro" />
              ) : (
                <div className="space-y-5">
                  {[...porQuarto.entries()].map(([quarto, itens]) => (
                    <section key={quarto} aria-label={quarto} className="space-y-2">
                      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{quarto}</h2>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                        {itens.map(l => (
                          <CartaoLeito key={l.id} leito={l} nome={l.residente_atual_id ? nomes.get(l.residente_atual_id) : undefined}
                            ausencia={l.residente_atual_id ? ausenciaAtiva.get(l.residente_atual_id) : undefined} aoAbrir={() => setAberto(l)} />
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              )}
            </>
          )}

          {aba === 'ausencias' && ausencias !== null && (
            <ListaAusencias ausencias={ausencias} nomes={nomes} podeEncerrar={pode('ausencias:atualizar')}
              aoEncerrar={a => executar(() => ausenciasApi.encerrar(a.id), `Retorno de ${nomes.get(a.residente_id) || 'residente'} registrado.`)} />
          )}
        </>
      )}

      {aberto && (
        <DetalheLeito leito={aberto} leitos={lista} residentes={residentes} nomes={nomes}
          ausencia={aberto.residente_atual_id ? ausenciaAtiva.get(aberto.residente_atual_id) : undefined}
          aoFechar={() => setAberto(null)} executar={executar} />
      )}
      {novoLeito && <NovoLeito aoFechar={() => setNovoLeito(false)} executar={executar} />}
      {novaAusencia && (
        <NovaAusencia residentes={residentes.filter(r => !ausenciaAtiva.has(r.id))} leitos={lista}
          aoFechar={() => setNovaAusencia(false)} executar={executar} />
      )}
    </div>
  )
}

function Resumo({ titulo, valor }: { titulo: string; valor: React.ReactNode }) {
  return (
    <div className="rounded-card border border-border bg-card p-4 shadow-card">
      <p className="text-sm text-muted-foreground">{titulo}</p>
      <p className="mt-1 font-display text-2xl font-bold text-foreground">{valor}</p>
    </div>
  )
}

function CartaoLeito({ leito: l, nome, ausencia, aoAbrir }: { leito: Leito; nome?: string; ausencia?: Ausencia; aoAbrir: () => void }) {
  const estado = estadoDoLeito(l)
  return (
    <button type="button" onClick={aoAbrir}
      className={cn('flex min-h-[88px] w-full flex-col items-start gap-1.5 rounded-card border bg-card p-4 text-left shadow-card transition-colors hover:border-brand/50',
        estado === 'inativo' ? 'border-dashed border-border opacity-70' : 'border-border')}>
      <div className="flex w-full items-center justify-between gap-2">
        <span className="font-medium text-foreground">Leito {l.leito}</span>
        <Badge variant={estado === 'ocupado' ? 'brand' : estado === 'livre' ? 'success' : estado === 'indisponivel' ? 'warning' : 'neutral'}>
          {estado === 'indisponivel' ? ROTULO_SITUACAO_LEITO[l.situacao] : ROTULO_ESTADO[estado]}
        </Badge>
      </div>
      {estado === 'ocupado' && <span className="truncate text-sm text-foreground">{nome || 'Residente'}</span>}
      {ausencia && (
        <span className="text-xs font-medium text-orange-800">
          {ROTULO_AUSENCIA[ausencia.tipo]} desde {formatDate(ausencia.data_inicio)}
        </span>
      )}
      {l.acessibilidade && <span className="text-xs text-muted-foreground">Acessibilidade: {l.acessibilidade}</span>}
    </button>
  )
}

function ListaAusencias({ ausencias, nomes, podeEncerrar, aoEncerrar }: {
  ausencias: Ausencia[]; nomes: Map<string, string>; podeEncerrar: boolean; aoEncerrar: (a: Ausencia) => void
}) {
  const ativas = ausencias.filter(a => !a.data_fim)
  const encerradas = ausencias.filter(a => a.data_fim).slice(0, 20)
  if (ausencias.length === 0) return <EmptyState icon={DoorOpen} title="Nenhuma ausência registrada" />
  const Linha = ({ a }: { a: Ausencia }) => (
    <li className="flex flex-wrap items-center gap-3 rounded-card border border-border bg-card p-4 shadow-card">
      <div className="min-w-0 flex-1">
        <p className="font-medium text-foreground">{nomes.get(a.residente_id) || 'Residente'}</p>
        <p className="text-xs text-muted-foreground">
          {ROTULO_AUSENCIA[a.tipo]} · desde {formatDateTime(a.data_inicio)}{a.data_fim ? ` · retorno ${formatDateTime(a.data_fim)}` : ''}
        </p>
        <p className="text-xs text-muted-foreground">Motivo: {a.motivo}</p>
      </div>
      {!a.data_fim && podeEncerrar && (
        <Button variant="outline" onClick={() => aoEncerrar(a)}><LogOut aria-hidden="true" /> Registrar retorno</Button>
      )}
    </li>
  )
  return (
    <div className="space-y-6">
      <section aria-label="Ausências ativas" className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Ativas ({ativas.length})</h2>
        {ativas.length === 0 ? <p className="text-sm text-muted-foreground">Nenhum residente ausente agora.</p> : <ul className="space-y-2">{ativas.map(a => <Linha key={a.id} a={a} />)}</ul>}
      </section>
      {encerradas.length > 0 && (
        <section aria-label="Ausências encerradas" className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Encerradas recentes</h2>
          <ul className="space-y-2">{encerradas.map(a => <Linha key={a.id} a={a} />)}</ul>
        </section>
      )}
    </div>
  )
}

type Executar = (acao: () => Promise<unknown>, sucesso: string) => Promise<boolean>

function DetalheLeito({ leito: l, leitos, residentes, nomes, ausencia, aoFechar, executar }: {
  leito: Leito; leitos: Leito[]; residentes: ResidenteRef[]; nomes: Map<string, string>; ausencia?: Ausencia
  aoFechar: () => void; executar: Executar
}) {
  const { pode } = usePermissoesOuPadrao()
  const estado = estadoDoLeito(l)
  const podeAtualizar = pode('quartos_leitos:atualizar')
  const [residenteId, setResidenteId] = useState('')
  const [destinoId, setDestinoId] = useState('')
  const [motivo, setMotivo] = useState('')
  const [historico, setHistorico] = useState<MovimentacaoLeito[] | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const comLeito = new Set(leitos.filter(x => x.residente_atual_id).map(x => x.residente_atual_id))
  const semLeito = residentes.filter(r => !comLeito.has(r.id)).sort((a, b) => a.nome.localeCompare(b.nome))
  const livres = leitos.filter(x => x.id !== l.id && estadoDoLeito(x) === 'livre')

  useEffect(() => {
    leitosApi.historico(l.id).then(setHistorico).catch(() => setHistorico([]))
  }, [l.id])

  async function acao(fn: () => Promise<unknown>, sucesso: string) {
    setOcupado(true)
    await executar(fn, sucesso)
    setOcupado(false)
  }

  return (
    <Dialog open onOpenChange={a => { if (!a) aoFechar() }}>
      <DialogContent title={nomeDoLeito(l)} description={[l.unidade, l.acessibilidade && `Acessibilidade: ${l.acessibilidade}`].filter(Boolean).join(' · ') || undefined}>
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={estado === 'ocupado' ? 'brand' : estado === 'livre' ? 'success' : estado === 'indisponivel' ? 'warning' : 'neutral'}>
              {estado === 'indisponivel' ? ROTULO_SITUACAO_LEITO[l.situacao] : ROTULO_ESTADO[estado]}
            </Badge>
            {estado === 'ocupado' && l.residente_atual_id && (
              <Link to={`/residentes/${l.residente_atual_id}`} className="inline-flex min-h-[32px] items-center text-sm font-semibold text-primary hover:underline">
                {nomes.get(l.residente_atual_id) || 'Residente'}
              </Link>
            )}
            {l.data_ocupacao && estado === 'ocupado' && <span className="text-xs text-muted-foreground">desde {formatDate(l.data_ocupacao)}</span>}
          </div>

          {ausencia && (
            <Alert variant="warning" title={`${ROTULO_AUSENCIA[ausencia.tipo]} desde ${formatDate(ausencia.data_inicio)}`}>
              O leito continua ocupado pelo residente durante a ausência.
            </Alert>
          )}

          {podeAtualizar && estado === 'livre' && (
            <div className="space-y-2">
              <Label htmlFor="alocar-residente">Alocar residente</Label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <select id="alocar-residente" className={SELECT} value={residenteId} onChange={e => setResidenteId(e.target.value)}>
                  <option value="">Selecione um residente sem leito…</option>
                  {semLeito.map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
                </select>
                <Button disabled={!residenteId || ocupado} onClick={() => acao(() => leitosApi.alocar(l.id, residenteId), `${nomes.get(residenteId) || 'Residente'} alocado(a) em ${nomeDoLeito(l)}.`)}>
                  <UserPlus aria-hidden="true" /> Alocar
                </Button>
              </div>
            </div>
          )}

          {podeAtualizar && estado === 'ocupado' && l.residente_atual_id && (
            <div className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="transferir-destino">Transferir para</Label>
                <select id="transferir-destino" className={SELECT} value={destinoId} onChange={e => setDestinoId(e.target.value)}>
                  <option value="">Selecione um leito livre…</option>
                  {livres.map(x => <option key={x.id} value={x.id}>{[x.unidade, nomeDoLeito(x)].filter(Boolean).join(' · ')}</option>)}
                </select>
                <Input aria-label="Motivo da transferência (opcional)" placeholder="Motivo da transferência (opcional)" value={motivo} onChange={e => setMotivo(e.target.value)} />
                <Button variant="outline" className="w-full" disabled={!destinoId || ocupado}
                  onClick={() => acao(() => leitosApi.transferir(l.residente_atual_id as string, destinoId, motivo.trim() || undefined), 'Transferência registrada.')}>
                  <ArrowRightLeft aria-hidden="true" /> Transferir
                </Button>
              </div>
              <Button variant="ghost" className="w-full text-red-700 hover:bg-red-50" disabled={ocupado}
                onClick={() => acao(() => leitosApi.liberar(l.id), `${nomeDoLeito(l)} liberado.`)}>
                <LogOut aria-hidden="true" /> Liberar leito
              </Button>
            </div>
          )}

          {podeAtualizar && (estado === 'livre' || estado === 'indisponivel') && (
            <div className="space-y-2">
              <Label htmlFor="situacao-leito">Situação do leito vazio</Label>
              <select id="situacao-leito" className={SELECT} value={l.situacao} disabled={ocupado}
                onChange={e => acao(() => leitosApi.alterarSituacao(l.id, e.target.value as SituacaoLeito), `${nomeDoLeito(l)}: ${ROTULO_SITUACAO_LEITO[e.target.value as SituacaoLeito]}.`)}>
                {SITUACOES_EDITAVEIS.map(s => <option key={s} value={s}>{ROTULO_SITUACAO_LEITO[s]}</option>)}
              </select>
            </div>
          )}

          {pode('quartos_leitos:inativar') && estado !== 'ocupado' && estado !== 'inativo' && (
            <Button variant="ghost" className="w-full text-muted-foreground" disabled={ocupado}
              onClick={() => acao(() => leitosApi.inativar(l.id), `${nomeDoLeito(l)} inativado.`)}>
              Inativar leito
            </Button>
          )}

          <section aria-label="Histórico de ocupação" className="space-y-2 border-t border-border pt-4">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground"><History className="size-4" aria-hidden="true" /> Histórico de ocupação</h3>
            {historico === null ? <Skeleton className="h-10 w-full" /> : historico.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sem movimentações registradas.</p>
            ) : (
              <ul className="space-y-1.5">
                {historico.slice(0, 8).map(h => (
                  <li key={h.id} className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{nomes.get(h.residente_id) || 'Residente'}</span> · {h.tipo_movimentacao} · {formatDate(h.data_entrada)}{h.data_saida ? ` → ${formatDate(h.data_saida)}` : ' → atual'}
                  </li>
                ))}
              </ul>
            )}
          </section>
          {ocupado && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden="true" /> Salvando…</p>}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function NovoLeito({ aoFechar, executar }: { aoFechar: () => void; executar: Executar }) {
  const [dados, setDados] = useState({ unidade: '', quarto: '', leito: '', acessibilidade: '' })
  const [salvando, setSalvando] = useState(false)
  async function salvar(e: React.FormEvent) {
    e.preventDefault()
    setSalvando(true)
    await executar(() => leitosApi.criar({
      quarto: dados.quarto.trim(), leito: dados.leito.trim(),
      ...(dados.unidade.trim() ? { unidade: dados.unidade.trim() } : {}),
      ...(dados.acessibilidade.trim() ? { acessibilidade: dados.acessibilidade.trim() } : {}),
    }), `Quarto ${dados.quarto} · Leito ${dados.leito} cadastrado.`)
    setSalvando(false)
    aoFechar()
  }
  return (
    <Dialog open onOpenChange={a => { if (!a) aoFechar() }}>
      <DialogContent title="Novo leito" description="O leito nasce livre. Quarto e leito não podem se repetir na instituição.">
        <form onSubmit={salvar} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2"><Label htmlFor="nl-quarto">Quarto</Label><Input id="nl-quarto" required value={dados.quarto} onChange={e => setDados({ ...dados, quarto: e.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="nl-leito">Leito</Label><Input id="nl-leito" required value={dados.leito} onChange={e => setDados({ ...dados, leito: e.target.value })} /></div>
          </div>
          <div className="space-y-2"><Label htmlFor="nl-unidade">Unidade ou ala (opcional)</Label><Input id="nl-unidade" value={dados.unidade} onChange={e => setDados({ ...dados, unidade: e.target.value })} /></div>
          <div className="space-y-2"><Label htmlFor="nl-acess">Acessibilidade (opcional)</Label><Input id="nl-acess" value={dados.acessibilidade} onChange={e => setDados({ ...dados, acessibilidade: e.target.value })} /></div>
          <Button type="submit" className="w-full" disabled={salvando || !dados.quarto.trim() || !dados.leito.trim()}>
            {salvando ? <><Loader2 className="animate-spin" aria-hidden="true" /> Salvando…</> : 'Cadastrar leito'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function NovaAusencia({ residentes, leitos, aoFechar, executar }: {
  residentes: ResidenteRef[]; leitos: Leito[]; aoFechar: () => void; executar: Executar
}) {
  const [residenteId, setResidenteId] = useState('')
  const [tipo, setTipo] = useState<TipoAusencia>('hospitalizacao')
  const [motivo, setMotivo] = useState('')
  const [observacoes, setObservacoes] = useState('')
  const [salvando, setSalvando] = useState(false)
  const leitoDoResidente = leitos.find(l => l.residente_atual_id === residenteId)
  async function salvar(e: React.FormEvent) {
    e.preventDefault()
    setSalvando(true)
    await executar(() => ausenciasApi.registrar({
      residente_id: residenteId, tipo, motivo: motivo.trim(),
      ...(observacoes.trim() ? { observacoes: observacoes.trim() } : {}),
      ...(leitoDoResidente ? { quarto_leito_id: leitoDoResidente.id } : {}),
    }), 'Ausência registrada.')
    setSalvando(false)
    aoFechar()
  }
  return (
    <Dialog open onOpenChange={a => { if (!a) aoFechar() }}>
      <DialogContent title="Registrar ausência" description="Hospitalização ou saída temporária. O retorno é registrado depois, na aba Ausências.">
        <form onSubmit={salvar} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="na-residente">Residente</Label>
            <select id="na-residente" required className={SELECT} value={residenteId} onChange={e => setResidenteId(e.target.value)}>
              <option value="">Selecione…</option>
              {residentes.sort((a, b) => a.nome.localeCompare(b.nome)).map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="na-tipo">Tipo</Label>
            <select id="na-tipo" className={SELECT} value={tipo} onChange={e => setTipo(e.target.value as TipoAusencia)}>
              <option value="hospitalizacao">Hospitalização</option>
              <option value="saida_temporaria">Saída temporária</option>
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="na-motivo">Motivo</Label>
            <Input id="na-motivo" required value={motivo} onChange={e => setMotivo(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="na-obs">Observações (opcional)</Label>
            <Input id="na-obs" value={observacoes} onChange={e => setObservacoes(e.target.value)} />
          </div>
          {leitoDoResidente && <p className="text-xs text-muted-foreground">Leito atual: {nomeDoLeito(leitoDoResidente)}.</p>}
          <Button type="submit" className="w-full" disabled={salvando || !residenteId || !motivo.trim()}>
            {salvando ? <><Loader2 className="animate-spin" aria-hidden="true" /> Salvando…</> : 'Registrar ausência'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
