import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useParams } from 'react-router'
import { Lock } from 'lucide-react'
import { api, formatDate, formatDateTime, mensagemDeErro } from '../services/api'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { EmptyState } from '../components/ui/states'

const SELECT = 'flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground'
const AREA_TEXTO = 'min-h-24 w-full rounded-lg border border-input bg-card p-3 text-[16px] text-foreground'
type Ref = { id: string; nome: string }

function useResidentes() {
  const [lista, setLista] = useState<Ref[]>([])
  useEffect(() => { api.get<Ref[]>('/residentes/').then(r => setLista(r.data || [])).catch(() => setLista([])) }, [])
  return lista
}

/** Carrega uma lista e padroniza 403, erro e recarga depois de uma ação. */
function useLista<T>(url: string | null) {
  const [itens, setItens] = useState<T[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [proibido, setProibido] = useState(false)
  const carregar = useCallback(async () => {
    if (!url) return
    try {
      setItens((await api.get<T[]>(url)).data)
      setErro(null); setProibido(false)
    } catch (e: any) {
      if (e?.response?.status === 403) setProibido(true)
      else setErro(mensagemDeErro(e, 'Não foi possível carregar.'))
    }
  }, [url])
  useEffect(() => { carregar() }, [carregar])
  const agir = useCallback(async (acao: () => Promise<unknown>) => {
    setErro(null)
    try { await acao(); await carregar(); return true }
    catch (e) { setErro(mensagemDeErro(e, 'Não foi possível concluir.')); return false }
  }, [carregar])
  return { itens, erro, proibido, agir }
}

function Tela({ titulo, apoio, proibido, erro, children }: { titulo: string; apoio: string; proibido?: boolean; erro?: string | null; children: ReactNode }) {
  if (proibido) return <EmptyState icon={Lock} title="Sem acesso" description="Peça acesso ao administrador da instituição." />
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-titulo-tela text-brand-ink">{titulo}</h1>
        <p className="mt-1 text-apoio text-muted-foreground">{apoio}</p>
      </header>
      {erro && <Alert variant="error">{erro}</Alert>}
      {children}
    </div>
  )
}

function Campo({ id, rotulo, children }: { id: string; rotulo: string; children: ReactNode }) {
  return <div className="space-y-1"><Label htmlFor={id}>{rotulo}</Label>{children}</div>
}

function EscolheResidente({ residentes, valor, onChange }: { residentes: Ref[]; valor: string; onChange: (v: string) => void }) {
  return (
    <Campo id="residente" rotulo="Residente">
      <select id="residente" className={SELECT} value={valor} onChange={e => onChange(e.target.value)} required>
        <option value="">Selecione</option>
        {residentes.map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
      </select>
    </Campo>
  )
}

const Cartao = ({ children }: { children: ReactNode }) => <li className="rounded-card border border-border bg-card p-4">{children}</li>
const Vazio = ({ itens }: { itens: unknown[] | null }) => (itens === null ? <Skeleton className="h-32 w-full rounded-card" /> : itens.length === 0 ? <p className="text-apoio text-muted-foreground">Nenhum registro ainda.</p> : null)

/* ---------- Agenda ---------- */
interface Evento { id: string; residente_id: string; motivo: string; especialidade: string | null; profissional: string | null; local: string | null; inicio_em: string; situacao: string; resultado: string | null; motivo_cancelamento: string | null }

export function Agenda() {
  const { pode } = usePermissoesOuPadrao()
  const residentes = useResidentes()
  const nomes = new Map(residentes.map(r => [r.id, r.nome]))
  const { itens, erro, proibido, agir } = useLista<Evento>('/agenda/')
  const [f, setF] = useState({ residente_id: '', motivo: '', especialidade: '', profissional: '', local: '', inicio_em: '' })
  const gerencia = pode('agenda:gerenciar')

  function encerrar(ev: Evento, acao: 'concluir' | 'cancelar', pergunta: string) {
    const texto = window.prompt(pergunta)?.trim()
    if (texto) agir(() => api.post(`/agenda/${ev.id}/${acao}`, { texto }))
  }

  async function criar(e: FormEvent) {
    e.preventDefault()
    const ok = await agir(() => api.post('/agenda/', { ...f, inicio_em: new Date(f.inicio_em).toISOString() }))
    if (ok) setF({ residente_id: '', motivo: '', especialidade: '', profissional: '', local: '', inicio_em: '' })
  }

  return (
    <Tela titulo="Agenda" apoio="Consultas e compromissos dos residentes." proibido={proibido} erro={erro}>
      {gerencia && (
        <form onSubmit={criar} className="grid gap-4 md:grid-cols-2">
          <EscolheResidente residentes={residentes} valor={f.residente_id} onChange={v => setF({ ...f, residente_id: v })} />
          <Campo id="motivo" rotulo="Motivo"><Input id="motivo" required value={f.motivo} onChange={e => setF({ ...f, motivo: e.target.value })} /></Campo>
          <Campo id="inicio" rotulo="Data e hora"><Input id="inicio" type="datetime-local" required value={f.inicio_em} onChange={e => setF({ ...f, inicio_em: e.target.value })} /></Campo>
          <Campo id="profissional" rotulo="Profissional"><Input id="profissional" value={f.profissional} onChange={e => setF({ ...f, profissional: e.target.value })} /></Campo>
          <Campo id="especialidade" rotulo="Especialidade"><Input id="especialidade" value={f.especialidade} onChange={e => setF({ ...f, especialidade: e.target.value })} /></Campo>
          <Campo id="local" rotulo="Local"><Input id="local" value={f.local} onChange={e => setF({ ...f, local: e.target.value })} /></Campo>
          <div className="md:col-span-2"><Button type="submit">Agendar</Button></div>
        </form>
      )}
      <Vazio itens={itens} />
      <ul className="space-y-3">
        {itens?.map(ev => (
          <Cartao key={ev.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold text-foreground">{ev.motivo}</p>
              <Badge>{ev.situacao}</Badge>
            </div>
            <p className="text-apoio text-muted-foreground">{formatDateTime(ev.inicio_em)} · {nomes.get(ev.residente_id) || 'Residente'}{ev.profissional ? ` · ${ev.profissional}` : ''}{ev.local ? ` · ${ev.local}` : ''}</p>
            {(ev.resultado || ev.motivo_cancelamento) && <p className="mt-1 text-apoio">{ev.resultado || ev.motivo_cancelamento}</p>}
            {gerencia && ev.situacao === 'agendado' && (
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => encerrar(ev, 'concluir', 'Qual foi o resultado?')}>Concluir</Button>
                <Button variant="outline" onClick={() => encerrar(ev, 'cancelar', 'Por que foi cancelado?')}>Cancelar</Button>
              </div>
            )}
          </Cartao>
        ))}
      </ul>
    </Tela>
  )
}

/* ---------- Multidisciplinar ---------- */
const AREAS: Record<string, string> = { fisioterapia: 'Fisioterapia', nutricao: 'Nutrição', psicologia: 'Psicologia', servico_social: 'Serviço Social', enfermagem: 'Enfermagem' }
interface Atendimento { id: string; residente_id: string; ocorrido_em: string; evolucao: string; autor_nome: string; estornado_em: string | null; motivo_estorno: string | null }

export function Multidisciplinar() {
  const { area = '' } = useParams()
  const { pode } = usePermissoesOuPadrao()
  const residentes = useResidentes()
  const nomes = new Map(residentes.map(r => [r.id, r.nome]))
  const { itens, erro, proibido, agir } = useLista<Atendimento>(AREAS[area] ? `/multidisciplinar/${area}` : null)
  const [f, setF] = useState({ residente_id: '', ocorrido_em: '', evolucao: '' })
  const registra = pode(`multidisciplinar.${area}:registrar`)
  if (!AREAS[area]) return <EmptyState icon={Lock} title="Área não encontrada" description="Volte ao módulo Multidisciplinar." />

  async function criar(e: FormEvent) {
    e.preventDefault()
    const ok = await agir(() => api.post(`/multidisciplinar/${area}`, { ...f, ocorrido_em: new Date(f.ocorrido_em).toISOString() }))
    if (ok) setF({ residente_id: '', ocorrido_em: '', evolucao: '' })
  }
  function estornar(a: Atendimento) {
    const texto = window.prompt('Motivo do estorno')?.trim()
    if (texto) agir(() => api.post(`/multidisciplinar/${area}/${a.id}/estornar`, { texto }))
  }

  return (
    <Tela titulo={AREAS[area]} apoio="Atendimentos e evoluções desta área." proibido={proibido} erro={erro}>
      {registra && (
        <form onSubmit={criar} className="grid gap-4 md:grid-cols-2">
          <EscolheResidente residentes={residentes} valor={f.residente_id} onChange={v => setF({ ...f, residente_id: v })} />
          <Campo id="quando" rotulo="Data e hora"><Input id="quando" type="datetime-local" required value={f.ocorrido_em} onChange={e => setF({ ...f, ocorrido_em: e.target.value })} /></Campo>
          <div className="md:col-span-2"><Campo id="evolucao" rotulo="Evolução"><textarea id="evolucao" className={AREA_TEXTO} required value={f.evolucao} onChange={e => setF({ ...f, evolucao: e.target.value })} /></Campo></div>
          <div className="md:col-span-2"><Button type="submit">Registrar atendimento</Button></div>
        </form>
      )}
      <Vazio itens={itens} />
      <ul className="space-y-3">
        {itens?.map(a => (
          <Cartao key={a.id}>
            <p className="font-semibold text-foreground">{nomes.get(a.residente_id) || 'Residente'}</p>
            <p className="text-apoio text-muted-foreground">{formatDateTime(a.ocorrido_em)} · {a.autor_nome}</p>
            <p className={a.estornado_em ? 'mt-1 line-through' : 'mt-1'}>{a.evolucao}</p>
            {a.estornado_em && <p className="mt-1 text-apoio">Estornado: {a.motivo_estorno}</p>}
            {registra && !a.estornado_em && <Button className="mt-3" variant="outline" onClick={() => estornar(a)}>Estornar</Button>}
          </Cartao>
        ))}
      </ul>
    </Tela>
  )
}

/* ---------- PIA ---------- */
const SECOES_PIA = [
  ['informacoes_gerais', 'Informações gerais'], ['institucionalizacao', 'Institucionalização'],
  ['habitos_interesses', 'Hábitos e interesses'], ['apoio_social', 'Apoio social'], ['financas', 'Finanças'],
  ['historico_saude', 'Histórico de saúde'], ['planejamento_individual', 'Planejamento individual'],
] as const
type VersaoPia = Record<(typeof SECOES_PIA)[number][0], string | null> & { id: string; versao: number; autor_nome: string; created_at: string }

export function Pia() {
  const { pode } = usePermissoesOuPadrao()
  const residentes = useResidentes()
  const [residente, setResidente] = useState('')
  const { itens, erro, proibido, agir } = useLista<VersaoPia>(residente ? `/pia/${residente}` : null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [aviso, setAviso] = useState(false)
  const vigente = residente ? itens?.[0] : undefined

  useEffect(() => {
    setForm(Object.fromEntries(SECOES_PIA.map(([c]) => [c, vigente?.[c] || ''])))
  }, [vigente])

  async function salvar(e: FormEvent) {
    e.preventDefault()
    setAviso(false)
    setAviso(await agir(() => api.post(`/pia/${residente}`, form)))
  }

  return (
    <Tela titulo="PIA" apoio="Plano Individual de Atendimento: a vida do residente na instituição. Salvar cria uma nova versão." proibido={proibido} erro={erro}>
      <EscolheResidente residentes={residentes} valor={residente} onChange={setResidente} />
      {aviso && <Alert variant="success">Nova versão salva.</Alert>}
      {residente && (
        <form onSubmit={salvar} className="space-y-4">
          {vigente && <p className="text-apoio text-muted-foreground">Versão {vigente.versao} · {vigente.autor_nome} · {formatDateTime(vigente.created_at)}</p>}
          {SECOES_PIA.map(([c, rotulo]) => (
            <Campo key={c} id={c} rotulo={rotulo}>
              <textarea id={c} className={AREA_TEXTO} disabled={!pode('pia:registrar')} value={form[c] ?? ''} onChange={e => setForm({ ...form, [c]: e.target.value })} />
            </Campo>
          ))}
          {pode('pia:registrar') && <Button type="submit">Salvar nova versão</Button>}
        </form>
      )}
    </Tela>
  )
}

/* ---------- Estoque ---------- */
interface ItemEstoque { id: string; nome: string; unidade: string; categoria: string | null; localizacao: string | null; estoque_minimo: number; saldo: number; abaixo_do_minimo: boolean; lotes: { lote: string | null; validade: string | null; saldo: number }[] }

export function Estoque() {
  const { pode } = usePermissoesOuPadrao()
  const { itens, erro, proibido, agir } = useLista<ItemEstoque>('/estoque/itens')
  const [novo, setNovo] = useState({ nome: '', unidade: '', estoque_minimo: '0' })
  const [mov, setMov] = useState({ item: '', tipo: 'entrada', quantidade: '', lote: '', validade: '', motivo: '' })
  const movimenta = pode('estoque:movimentar')

  async function criar(e: FormEvent) {
    e.preventDefault()
    if (await agir(() => api.post('/estoque/itens', { ...novo, estoque_minimo: Number(novo.estoque_minimo) }))) setNovo({ nome: '', unidade: '', estoque_minimo: '0' })
  }
  async function movimentar(e: FormEvent) {
    e.preventDefault()
    const ok = await agir(() => api.post(`/estoque/itens/${mov.item}/movimentos`, {
      tipo: mov.tipo, quantidade: Number(mov.quantidade), lote: mov.lote || null, validade: mov.validade || null, motivo: mov.motivo || null,
    }))
    if (ok) setMov({ ...mov, quantidade: '', lote: '', validade: '', motivo: '' })
  }

  return (
    <Tela titulo="Farmácia e estoque" apoio="Saldo por lote e validade. As doses administradas não baixam o estoque sozinhas." proibido={proibido} erro={erro}>
      {movimenta && (
        <div className="grid gap-6 md:grid-cols-2">
          <form onSubmit={criar} className="space-y-3">
            <Campo id="item-nome" rotulo="Novo item"><Input id="item-nome" required value={novo.nome} onChange={e => setNovo({ ...novo, nome: e.target.value })} /></Campo>
            <Campo id="item-unidade" rotulo="Unidade"><Input id="item-unidade" required value={novo.unidade} onChange={e => setNovo({ ...novo, unidade: e.target.value })} /></Campo>
            <Campo id="item-minimo" rotulo="Estoque mínimo"><Input id="item-minimo" type="number" min="0" value={novo.estoque_minimo} onChange={e => setNovo({ ...novo, estoque_minimo: e.target.value })} /></Campo>
            <Button type="submit" variant="outline">Cadastrar item</Button>
          </form>
          <form onSubmit={movimentar} className="space-y-3">
            <Campo id="mov-item" rotulo="Item"><select id="mov-item" className={SELECT} required value={mov.item} onChange={e => setMov({ ...mov, item: e.target.value })}><option value="">Selecione</option>{itens?.map(i => <option key={i.id} value={i.id}>{i.nome}</option>)}</select></Campo>
            <Campo id="mov-tipo" rotulo="Tipo"><select id="mov-tipo" className={SELECT} value={mov.tipo} onChange={e => setMov({ ...mov, tipo: e.target.value })}><option value="entrada">Entrada</option><option value="saida">Saída</option></select></Campo>
            <Campo id="mov-qtd" rotulo="Quantidade"><Input id="mov-qtd" type="number" min="1" required value={mov.quantidade} onChange={e => setMov({ ...mov, quantidade: e.target.value })} /></Campo>
            <Campo id="mov-lote" rotulo="Lote"><Input id="mov-lote" value={mov.lote} onChange={e => setMov({ ...mov, lote: e.target.value })} /></Campo>
            {mov.tipo === 'entrada'
              ? <Campo id="mov-val" rotulo="Validade"><Input id="mov-val" type="date" value={mov.validade} onChange={e => setMov({ ...mov, validade: e.target.value })} /></Campo>
              : <Campo id="mov-mot" rotulo="Motivo"><Input id="mov-mot" required value={mov.motivo} onChange={e => setMov({ ...mov, motivo: e.target.value })} /></Campo>}
            <Button type="submit">Registrar movimento</Button>
          </form>
        </div>
      )}
      <Vazio itens={itens} />
      <ul className="space-y-3">
        {itens?.map(i => (
          <Cartao key={i.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold text-foreground">{i.nome}</p>
              <span className="flex items-center gap-2">{i.abaixo_do_minimo && <Badge>Abaixo do mínimo</Badge>}<strong>{i.saldo} {i.unidade}</strong></span>
            </div>
            {i.lotes.map(l => <p key={l.lote ?? 'sem-lote'} className="text-apoio text-muted-foreground">Lote {l.lote || 'sem número'}{l.validade ? ` · validade ${formatDate(l.validade)}` : ''} · {l.saldo}</p>)}
          </Cartao>
        ))}
      </ul>
    </Tela>
  )
}

/* ---------- Financeiro ---------- */
interface Mensalidade { id: string; residente_id: string; competencia: string; valor_centavos: number; vencimento: string; situacao: string; pago_em: string | null; observacao: string | null }
const reais = (c: number) => (c / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

export function Financeiro() {
  const { pode } = usePermissoesOuPadrao()
  const residentes = useResidentes()
  const nomes = new Map(residentes.map(r => [r.id, r.nome]))
  const { itens, erro, proibido, agir } = useLista<Mensalidade>('/financeiro/mensalidades')
  const [f, setF] = useState({ residente_id: '', competencia: '', valor: '', vencimento: '' })
  const gerencia = pode('financeiro:gerenciar')

  async function lancar(e: FormEvent) {
    e.preventDefault()
    const valor_centavos = Math.round(Number(f.valor.replace(',', '.')) * 100)
    const ok = await agir(() => api.post('/financeiro/mensalidades', { residente_id: f.residente_id, competencia: f.competencia, vencimento: f.vencimento, valor_centavos }))
    if (ok) setF({ residente_id: '', competencia: '', valor: '', vencimento: '' })
  }
  function pagar(x: Mensalidade) {
    const pago_em = window.prompt('Data do pagamento (AAAA-MM-DD)', new Date().toISOString().slice(0, 10))?.trim()
    if (pago_em) agir(() => api.post(`/financeiro/mensalidades/${x.id}/pagar`, { pago_em }))
  }
  function cancelar(x: Mensalidade) {
    const texto = window.prompt('Motivo do cancelamento')?.trim()
    if (texto) agir(() => api.post(`/financeiro/mensalidades/${x.id}/cancelar`, { texto }))
  }

  return (
    <Tela titulo="Mensalidades" apoio="Controle manual por residente. Nenhuma cobrança é enviada." proibido={proibido} erro={erro}>
      {gerencia && (
        <form onSubmit={lancar} className="grid gap-4 md:grid-cols-2">
          <EscolheResidente residentes={residentes} valor={f.residente_id} onChange={v => setF({ ...f, residente_id: v })} />
          <Campo id="competencia" rotulo="Competência"><Input id="competencia" type="month" required value={f.competencia} onChange={e => setF({ ...f, competencia: e.target.value })} /></Campo>
          <Campo id="valor" rotulo="Valor (R$)"><Input id="valor" inputMode="decimal" required value={f.valor} onChange={e => setF({ ...f, valor: e.target.value })} /></Campo>
          <Campo id="vencimento" rotulo="Vencimento"><Input id="vencimento" type="date" required value={f.vencimento} onChange={e => setF({ ...f, vencimento: e.target.value })} /></Campo>
          <div className="md:col-span-2"><Button type="submit">Lançar mensalidade</Button></div>
        </form>
      )}
      <Vazio itens={itens} />
      <ul className="space-y-3">
        {itens?.map(x => (
          <Cartao key={x.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold text-foreground">{nomes.get(x.residente_id) || 'Residente'} · {x.competencia}</p>
              <Badge>{x.situacao}</Badge>
            </div>
            <p className="text-apoio text-muted-foreground">{reais(x.valor_centavos)} · vence {formatDate(x.vencimento)}{x.pago_em ? ` · pago ${formatDate(x.pago_em)}` : ''}</p>
            {gerencia && x.situacao !== 'cancelada' && (
              <div className="mt-3 flex flex-wrap gap-2">
                {x.situacao === 'aberta' && <Button variant="outline" onClick={() => pagar(x)}>Registrar pagamento</Button>}
                <Button variant="outline" onClick={() => cancelar(x)}>Cancelar</Button>
              </div>
            )}
          </Cartao>
        ))}
      </ul>
    </Tela>
  )
}
