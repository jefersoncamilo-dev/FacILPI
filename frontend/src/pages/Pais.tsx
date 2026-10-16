import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAberturaPorParametro } from '../hooks/useAberturaPorParametro'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronRight, Loader2, NotebookPen, Plus } from 'lucide-react'
import { api, formatDate, mensagemDeErro } from '../services/api'
import { paisApi, ROTULO_PAIS, TERMINAIS_PAIS, type Plano } from '../services/pais'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { EmptyState, ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

type ResidenteRef = { id: string; nome: string }
type Filtro = 'todos' | 'vigentes' | 'andamento' | 'encerrados'
const SELECT = 'flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40'

/** Plano atual de um residente: o vigente, senão a versão mais recente. */
function planoAtual(planos: Plano[]): Plano {
  return planos.find(p => p.situacao === 'vigente')
    ?? [...planos].sort((a, b) => b.versao - a.versao || (b.created_at || '').localeCompare(a.created_at || ''))[0]
}

const contagem = (itens: { situacao: string }[], um: string, varios: string) => {
  const n = itens.filter(i => i.situacao === 'ativa').length
  return `${n} ${n === 1 ? um : varios}`
}

export function variantePais(s: Plano['situacao']): 'success' | 'brand' | 'warning' | 'neutral' {
  if (s === 'vigente') return 'success'
  if (s === 'em_revisao' || s === 'aprovado') return 'warning'
  if (TERMINAIS_PAIS.includes(s)) return 'neutral'
  return 'brand'
}

/** Plano de cuidados / PAIS (UX-07 / #80). Substitui o placeholder de /plano. */
export function Pais() {
  const { pode } = usePermissoesOuPadrao()
  const [params] = useSearchParams()
  const residenteFiltro = params.get('residente')
  const [planos, setPlanos] = useState<Plano[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [residentes, setResidentes] = useState<ResidenteRef[]>([])
  const [filtro, setFiltro] = useState<Filtro>('todos')
  const [novo, setNovo] = useAberturaPorParametro('novo', pode('planos_cuidados:criar'))

  const carregar = useCallback(async () => {
    try {
      setPlanos(await paisApi.listar())
      setErro(null)
    } catch (e: any) {
      setPlanos(null)
      setErro(e?.response?.status === 403 ? 'proibido' : mensagemDeErro(e, 'Não foi possível carregar os planos.'))
    }
  }, [])

  useEffect(() => { carregar() }, [carregar])
  useEffect(() => {
    api.get<ResidenteRef[]>('/residentes/').then(r => setResidentes(r.data || [])).catch(() => setResidentes([]))
  }, [])

  const nomes = useMemo(() => new Map(residentes.map(r => [r.id, r.nome])), [residentes])
  const porResidente = useMemo(() => {
    const mapa = new Map<string, Plano[]>()
    for (const p of planos || []) mapa.set(p.residente_id, [...(mapa.get(p.residente_id) || []), p])
    return [...mapa.entries()]
      .filter(([rid]) => !residenteFiltro || rid === residenteFiltro)
      .map(([rid, lista]) => ({ residenteId: rid, atual: planoAtual(lista), versoes: lista.length }))
      .sort((a, b) => (nomes.get(a.residenteId) || '').localeCompare(nomes.get(b.residenteId) || ''))
  }, [planos, nomes, residenteFiltro])

  if (erro === 'proibido') return <ErrorState title="Sem acesso aos planos de cuidados" description="Seu perfil não permite consultar o PAIS nesta ILPI." />
  if (erro) return <ErrorState title="Não foi possível carregar os planos" description={`${erro} Isso não significa que não há planos.`} onRetry={carregar} />

  const passa = (p: Plano) =>
    filtro === 'todos' || (filtro === 'vigentes' && p.situacao === 'vigente')
    || (filtro === 'encerrados' && TERMINAIS_PAIS.includes(p.situacao))
    || (filtro === 'andamento' && !TERMINAIS_PAIS.includes(p.situacao) && p.situacao !== 'vigente')
  const visiveis = porResidente.filter(g => passa(g.atual))

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Plano de cuidados (PAIS)</h1>
          <p className="text-sm text-muted-foreground">
            {residenteFiltro ? <>Planos de {nomes.get(residenteFiltro) || 'um residente'} · <Link to="/plano" className="font-medium text-primary hover:underline">ver todos</Link></> : 'O plano vigente de cada residente e o que está em construção.'}
          </p>
        </div>
        {pode('planos_cuidados:criar') && planos !== null && (
          <Button onClick={() => setNovo(true)}><Plus aria-hidden="true" /> Novo PAIS</Button>
        )}
      </div>

      {planos === null ? (
        <div className="space-y-3" aria-label="Carregando planos">{[0, 1, 2].map(i => <Skeleton key={i} className="h-20" />)}</div>
      ) : (
        <>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar planos">
            {([['todos', 'Todos'], ['vigentes', 'Vigentes'], ['andamento', 'Em andamento'], ['encerrados', 'Encerrados']] as [Filtro, string][]).map(([f, rotulo]) => (
              <button key={f} type="button" aria-pressed={filtro === f} onClick={() => setFiltro(f)}
                className={cn('min-h-[36px] rounded-full border px-3 text-sm font-medium',
                  filtro === f ? 'border-brand bg-accent text-accent-foreground' : 'border-border bg-card text-muted-foreground hover:text-foreground')}>
                {rotulo}
              </button>
            ))}
          </div>

          {visiveis.length === 0 ? (
            <EmptyState icon={NotebookPen} title={porResidente.length === 0 ? 'Nenhum plano de cuidados ainda' : 'Nenhum plano neste filtro'}
              description={porResidente.length === 0 ? 'O PAIS organiza necessidades, metas e intervenções de cada residente.' : undefined}
              action={porResidente.length === 0 && pode('planos_cuidados:criar') ? <Button onClick={() => setNovo(true)}><Plus aria-hidden="true" /> Novo PAIS</Button> : undefined} />
          ) : (
            <ul className="space-y-2">
              {visiveis.map(({ residenteId, atual, versoes }) => (
                <li key={residenteId}>
                  <Link to={`/plano/${atual.id}`} className="flex min-h-[72px] items-center gap-4 rounded-card border border-border bg-card px-4 py-3 shadow-card transition-colors hover:border-brand/50 sm:px-5">
                    <span aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft font-semibold text-primary">
                      {(nomes.get(residenteId) || 'R')[0]}
                    </span>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate font-medium text-foreground">{nomes.get(residenteId) || 'Residente'}</p>
                        <Badge variant={variantePais(atual.situacao)}>{ROTULO_PAIS[atual.situacao]}</Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Versão {atual.versao}{versoes > 1 ? ` · ${versoes} versões` : ''} · desde {formatDate(atual.data_inicial)}
                        {' · '}{contagem(atual.necessidades, 'necessidade', 'necessidades')}, {contagem(atual.metas, 'meta', 'metas')}, {contagem(atual.intervencoes, 'intervenção', 'intervenções')}
                      </p>
                    </div>
                    <ChevronRight className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {novo && <NovoPais residentes={residentes} residenteInicial={residenteFiltro || ''} aoFechar={() => setNovo(false)} />}
    </div>
  )
}

function NovoPais({ residentes, residenteInicial, aoFechar }: { residentes: ResidenteRef[]; residenteInicial: string; aoFechar: () => void }) {
  const navigate = useNavigate()
  const [residenteId, setResidenteId] = useState(residenteInicial)
  const [inicio, setInicio] = useState(new Date().toISOString().slice(0, 10))
  const [objetivos, setObjetivos] = useState('')
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)

  async function criar(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    setSalvando(true)
    try {
      const plano = await paisApi.criar({ residente_id: residenteId, data_inicial: inicio, ...(objetivos.trim() ? { objetivos: objetivos.trim() } : {}) })
      navigate(`/plano/${plano.id}`)
    } catch (err) {
      setErro(mensagemDeErro(err, 'Não foi possível criar o plano.'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open onOpenChange={a => { if (!a) aoFechar() }}>
      <DialogContent title="Novo PAIS" description="O plano nasce como rascunho. Necessidades, metas e intervenções são incluídas em seguida.">
        <form onSubmit={criar} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="np-residente">Residente</Label>
            <select id="np-residente" required className={SELECT} value={residenteId} onChange={e => setResidenteId(e.target.value)}>
              <option value="">Selecione…</option>
              {[...residentes].sort((a, b) => a.nome.localeCompare(b.nome)).map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="np-inicio">Início</Label>
            <Input id="np-inicio" type="date" required value={inicio} onChange={e => setInicio(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="np-objetivos">Objetivos (opcional)</Label>
            <textarea id="np-objetivos" rows={3} value={objetivos} onChange={e => setObjetivos(e.target.value)}
              className="w-full rounded-lg border border-input bg-card px-3 py-2 text-[16px] focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40" />
          </div>
          {erro && <Alert variant="error">{erro}</Alert>}
          <Button type="submit" className="w-full" disabled={!residenteId || salvando}>
            {salvando ? <><Loader2 className="animate-spin" aria-hidden="true" /> Criando…</> : 'Criar rascunho'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
