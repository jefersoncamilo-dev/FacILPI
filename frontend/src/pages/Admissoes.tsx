import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronRight, ClipboardList, Loader2, Plus, Search, UserPlus } from 'lucide-react'
import { api, formatDate, mensagemDeErro } from '../services/api'
import {
  admissoesApi, emAndamento, ETAPAS, ROTULO_SITUACAO, type Admissao, type Etapa,
} from '../services/admissoes'
import { usePermissoes } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Badge, Skeleton } from '../components/ui/feedback'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { EmptyState, ErrorState } from '../components/ui/states'
import { cn } from '../lib/utils'

type ResidenteRef = { id: string; nome: string; situacao?: string | null }
type Aba = 'andamento' | 'concluidas' | 'encerradas' | 'todas'

const ABAS: { id: Aba; label: string; filtro: (a: Admissao) => boolean }[] = [
  { id: 'andamento', label: 'Em andamento', filtro: a => emAndamento(a.situacao) },
  { id: 'concluidas', label: 'Concluídas', filtro: a => a.situacao === 'concluida' },
  { id: 'encerradas', label: 'Canceladas', filtro: a => a.situacao === 'cancelada' || a.situacao === 'desistencia' },
  { id: 'todas', label: 'Todas', filtro: () => true },
]

type Carga = { status: 'carregando' } | { status: 'ok'; admissoes: Admissao[] } | { status: 'proibido' } | { status: 'erro'; mensagem: string }

/** Lista de admissões (UX-03 / #76). Substitui o placeholder de /admissoes. */
export function Admissoes() {
  const { pode } = usePermissoes()
  const [carga, setCarga] = useState<Carga>({ status: 'carregando' })
  const [residentes, setResidentes] = useState<ResidenteRef[]>([])
  const [aba, setAba] = useState<Aba>('andamento')
  const [busca, setBusca] = useState('')
  const [novaAberta, setNovaAberta] = useState(false)

  const carregar = useCallback(async () => {
    setCarga({ status: 'carregando' })
    try {
      const admissoes = await admissoesApi.listar()
      setCarga({ status: 'ok', admissoes })
    } catch (e: any) {
      if (e?.response?.status === 403) setCarga({ status: 'proibido' })
      else setCarga({ status: 'erro', mensagem: mensagemDeErro(e, 'Não foi possível carregar as admissões.') })
    }
  }, [])

  useEffect(() => { carregar() }, [carregar])

  useEffect(() => {
    // Nomes vêm do cadastro de residentes; sem acesso a ele, a lista mostra
    // "Residente" em vez de inventar nome.
    api.get<ResidenteRef[]>('/residentes/').then(r => setResidentes(r.data || [])).catch(() => setResidentes([]))
  }, [])

  const nomes = useMemo(() => new Map(residentes.map(r => [r.id, r.nome])), [residentes])
  const admissoes = carga.status === 'ok' ? carga.admissoes : []
  const contagem = (id: Aba) => admissoes.filter(ABAS.find(a => a.id === id)!.filtro).length
  const termo = busca.trim().toLowerCase()
  const visiveis = admissoes
    .filter(ABAS.find(a => a.id === aba)!.filtro)
    .filter(a => !termo || (nomes.get(a.residente_id) || '').toLowerCase().includes(termo))
    .sort((x, y) => y.iniciada_em.localeCompare(x.iniciada_em))

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Admissões</h1>
          <p className="text-sm text-muted-foreground">Da chegada do residente até a conclusão, etapa por etapa.</p>
        </div>
        {pode('admissoes:criar') && carga.status === 'ok' && (
          <Button onClick={() => setNovaAberta(true)}>
            <Plus aria-hidden="true" /> Nova admissão
          </Button>
        )}
      </div>

      {carga.status === 'carregando' && (
        <div className="space-y-3" aria-label="Carregando admissões">
          {[0, 1, 2].map(i => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      )}
      {carga.status === 'proibido' && (
        <ErrorState title="Sem acesso às admissões" description="Seu perfil não permite consultar admissões nesta ILPI. Se precisar, fale com o administrador." />
      )}
      {carga.status === 'erro' && (
        <ErrorState title="Não foi possível carregar as admissões" description={`${carga.mensagem} Isso não significa que não há admissões.`} onRetry={carregar} />
      )}

      {carga.status === 'ok' && (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div role="tablist" aria-label="Situação" className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1 sm:flex">
              {ABAS.map(a => (
                <button
                  key={a.id}
                  role="tab"
                  aria-selected={aba === a.id}
                  onClick={() => setAba(a.id)}
                  className={cn(
                    'min-h-[40px] shrink-0 rounded-md px-3 text-sm font-medium transition-colors',
                    aba === a.id ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {a.label} <span className="text-xs text-muted-foreground">({contagem(a.id)})</span>
                </button>
              ))}
            </div>
            <div className="relative sm:w-72">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input
                aria-label="Buscar por nome do residente"
                placeholder="Buscar residente"
                className="h-11 pl-9"
                value={busca}
                onChange={e => setBusca(e.target.value)}
              />
            </div>
          </div>

          {visiveis.length === 0 ? (
            termo ? (
              <EmptyState icon={Search} title="Nenhuma admissão encontrada" description="Confira o nome digitado ou troque a aba." />
            ) : (
              <EmptyState
                icon={ClipboardList}
                title={aba === 'andamento' ? 'Nenhuma admissão em andamento' : 'Nada por aqui'}
                description={aba === 'andamento' ? 'Quando um residente começar a ser admitido, o processo aparece aqui.' : undefined}
                action={aba === 'andamento' && pode('admissoes:criar')
                  ? <Button onClick={() => setNovaAberta(true)}><Plus aria-hidden="true" /> Nova admissão</Button>
                  : undefined}
              />
            )
          ) : (
            <ul className="space-y-2">
              {visiveis.map(a => (
                <li key={a.id}>
                  <ItemAdmissao admissao={a} nome={nomes.get(a.residente_id)} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {pode('admissoes:criar') && (
        <NovaAdmissaoDialog
          aberta={novaAberta}
          aoFechar={() => setNovaAberta(false)}
          residentes={residentes}
          admissoes={admissoes}
        />
      )}
    </div>
  )
}

function ItemAdmissao({ admissao: a, nome }: { admissao: Admissao; nome?: string }) {
  const indice = ETAPAS.indexOf(a.situacao as Etapa)
  const andamento = indice >= 0
  return (
    <Link
      to={`/admissoes/${a.id}`}
      className="flex min-h-[72px] items-center gap-4 rounded-card border border-border bg-card px-4 py-3 shadow-card transition-colors hover:border-brand/50 sm:px-5"
    >
      <span aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft font-semibold text-primary">
        {(nome || 'R')[0]}
      </span>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate font-medium text-foreground">{nome || 'Residente'}</p>
          <Badge variant={a.situacao === 'concluida' ? 'success' : andamento ? 'brand' : 'neutral'}>{ROTULO_SITUACAO[a.situacao]}</Badge>
        </div>
        {andamento ? (
          <div className="flex items-center gap-3">
            <div className="h-1.5 w-full max-w-[220px] overflow-hidden rounded-full bg-muted" aria-hidden="true">
              <div className="h-full rounded-full bg-brand" style={{ width: `${((indice + 1) / ETAPAS.length) * 100}%` }} />
            </div>
            <span className="shrink-0 text-xs text-muted-foreground">Etapa {indice + 1} de {ETAPAS.length}</span>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            {a.situacao === 'concluida' && a.concluida_em ? `Concluída em ${formatDate(a.concluida_em)}` : null}
            {a.situacao === 'cancelada' && a.cancelada_em ? `Cancelada em ${formatDate(a.cancelada_em)}` : null}
            {a.situacao === 'desistencia' && a.desistencia_em ? `Desistência em ${formatDate(a.desistencia_em)}` : null}
          </p>
        )}
        <p className="text-xs text-muted-foreground">Iniciada em {formatDate(a.iniciada_em)}</p>
      </div>
      <ChevronRight className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
    </Link>
  )
}

function NovaAdmissaoDialog({
  aberta,
  aoFechar,
  residentes,
  admissoes,
}: {
  aberta: boolean
  aoFechar: () => void
  residentes: ResidenteRef[]
  admissoes: Admissao[]
}) {
  const navigate = useNavigate()
  const { pode } = usePermissoes()
  const [residenteId, setResidenteId] = useState('')
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)

  // Elegível: sem processo aberto (o backend recusa duplicidade com 409; aqui
  // só evitamos oferecer a escolha que certamente falharia).
  const comProcessoAberto = new Set(admissoes.filter(a => a.situacao !== 'cancelada' && a.situacao !== 'desistencia').map(a => a.residente_id))
  const elegiveis = residentes.filter(r => !comProcessoAberto.has(r.id)).sort((a, b) => a.nome.localeCompare(b.nome))

  function fechar(abrir: boolean) {
    if (!abrir) { setResidenteId(''); setErro(''); aoFechar() }
  }

  async function criar(e: React.FormEvent) {
    e.preventDefault()
    setErro('')
    setSalvando(true)
    try {
      const nova = await admissoesApi.criar(residenteId)
      navigate(`/admissoes/${nova.id}`)
    } catch (err: any) {
      setErro(err?.response?.status === 409
        ? 'Este residente já tem uma admissão aberta ou concluída. Abra o processo existente na lista.'
        : mensagemDeErro(err, 'Não foi possível abrir a admissão.'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open={aberta} onOpenChange={fechar}>
      <DialogContent title="Nova admissão" description="Escolha o residente. As etapas seguintes acontecem no próprio processo.">
        {elegiveis.length === 0 ? (
          <div className="space-y-4">
            <Alert variant="info">Nenhum residente disponível para uma nova admissão. Todos já têm processo aberto ou concluído, ou ainda não há cadastro.</Alert>
            {pode('residentes:criar') && (
              <Button asChild variant="outline" className="w-full">
                <Link to="/residentes"><UserPlus aria-hidden="true" /> Cadastrar residente</Link>
              </Button>
            )}
          </div>
        ) : (
          <form onSubmit={criar} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="nova-admissao-residente">Residente</Label>
              <select
                id="nova-admissao-residente"
                required
                value={residenteId}
                onChange={e => setResidenteId(e.target.value)}
                className="flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              >
                <option value="" disabled>Selecione…</option>
                {elegiveis.map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
              </select>
            </div>
            {erro && <Alert variant="error">{erro}</Alert>}
            <Button type="submit" className="w-full" disabled={!residenteId || salvando}>
              {salvando ? <><Loader2 className="animate-spin" aria-hidden="true" /> Abrindo…</> : 'Abrir admissão'}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
