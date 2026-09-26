import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BedDouble, Loader2, Lock, Plus, Search, TriangleAlert } from 'lucide-react'
import { api, formatDate, mensagemDeErro } from '../services/api'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { idade, useLeitosPorResidente } from '../hooks/useContextoResidente'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert } from '../components/ui/feedback'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { LoadingState } from '../components/ui/states'
import { cn } from '../lib/utils'

const FORM_VAZIO = { nome: '', data_nascimento: '', cpf: '', cns: '', sexo: 'M', situacao: 'Em admissao' }

/** Lista de residentes (UX-04 / #89). Estrutura do card: Issue #34; estados: PH-01. */
export function Residentes() {
  const { pode } = usePermissoesOuPadrao()
  const leitos = useLeitosPorResidente()
  const [items, setItems] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<any>(FORM_VAZIO)
  const [msg, setMsg] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [q, setQ] = useState('')
  const [situacao, setSituacao] = useState<string | null>(null)
  // PH-01: antes `load()` não tinha catch. Um 403 (perfil sem `residentes:ler`,
  // ou ILPI ainda em configuração) virava promise rejeitada em silêncio, a lista
  // ficava vazia e a tela dizia "0 residentes" — afirmando como fato algo que
  // nunca foi consultado com sucesso. Carregando, vazio legítimo, acesso negado
  // e falha de consulta passam a ser quatro estados distintos.
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')
  const [semPermissao, setSemPermissao] = useState(false)

  const load = useCallback(async () => {
    setCarregando(true)
    try {
      const { data } = await api.get('/residentes/')
      setItems(data || [])
      setErro('')
      setSemPermissao(false)
    } catch (e) {
      // Zera a lista junto com o erro: dado obsoleto ao lado de uma mensagem de
      // falha é pior que nenhum dado.
      setItems([])
      const status = (e as { response?: { status?: number } })?.response?.status
      setSemPermissao(status === 403)
      setErro(mensagemDeErro(e, 'Não foi possível carregar os residentes.'))
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setMsg('')
    setSalvando(true)
    try {
      const payload: any = { ...form }
      // clean cpf/cns to digits
      if (payload.cpf) payload.cpf = payload.cpf.replace(/\D/g, '')
      if (payload.cns) payload.cns = payload.cns.replace(/\D/g, '')
      if (!payload.cpf) delete payload.cpf
      if (!payload.cns) delete payload.cns
      await api.post('/residentes/', payload)
      setOpen(false)
      setForm(FORM_VAZIO)
      load()
    } catch (e: any) {
      setMsg(mensagemDeErro(e, 'Erro ao salvar'))
    } finally {
      setSalvando(false)
    }
  }

  // Situações reais presentes nos dados — nenhuma é inventada pela tela.
  const situacoes = useMemo(() => {
    const contagem = new Map<string, number>()
    for (const r of items) {
      const s = r.situacao || 'Sem situação'
      contagem.set(s, (contagem.get(s) || 0) + 1)
    }
    return [...contagem.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [items])

  const termo = q.trim().toLowerCase()
  const filtered = items
    .filter(i => !situacao || (i.situacao || 'Sem situação') === situacao)
    .filter(i => !termo || i.nome.toLowerCase().includes(termo) || (i.cpf || '').includes(q.trim()))

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Residentes</h1>
          <p className="text-sm text-muted-foreground">Quem vive na instituição, com a história de cada pessoa no prontuário.</p>
        </div>
        {pode('residentes:criar') && (
          <Button onClick={() => setOpen(true)}>
            <Plus aria-hidden="true" /> Novo residente
          </Button>
        )}
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input
              aria-label="Buscar por nome ou CPF"
              placeholder="Buscar por nome ou CPF..."
              className="h-11 pl-9"
              value={q}
              onChange={e => setQ(e.target.value)}
            />
          </div>
          {/* A contagem só aparece quando houve consulta bem-sucedida. Enquanto
              carrega ou depois de falhar, "0 residentes" seria uma afirmação
              sobre dado que a tela não tem. */}
          {!carregando && !erro && (
            <span className="hidden whitespace-nowrap text-sm text-muted-foreground sm:inline-flex">{filtered.length} residentes</span>
          )}
        </div>
        {!carregando && !erro && situacoes.length > 1 && (
          <div className="flex flex-wrap gap-2" aria-label="Filtrar por situação">
            {[['Todas', items.length] as [string, number], ...situacoes].map(([nome, total]) => {
              const ativo = nome === 'Todas' ? situacao === null : situacao === nome
              return (
                <button
                  key={nome}
                  type="button"
                  aria-pressed={ativo}
                  onClick={() => setSituacao(nome === 'Todas' ? null : nome)}
                  className={cn(
                    'min-h-[36px] rounded-full border px-3 text-sm font-medium transition-colors',
                    ativo ? 'border-brand bg-accent text-accent-foreground' : 'border-border bg-card text-muted-foreground hover:text-foreground',
                  )}
                >
                  {nome} <span className="text-xs">({total})</span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {carregando ? (
        <div aria-live="polite" className="card">
          <LoadingState label="Carregando residentes…" />
        </div>
      ) : semPermissao ? (
        <div className="card py-10 text-center" role="alert">
          <Lock className="mx-auto mb-3 size-7 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">Você não tem permissão para ver os residentes</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Isso também acontece quando a instituição ainda está em configuração. Fale com o
            administrador da ILPI.
          </p>
        </div>
      ) : erro ? (
        <div className="card py-10 text-center" role="alert">
          <TriangleAlert className="mx-auto mb-3 size-7 text-amber-700" aria-hidden="true" />
          <p className="text-sm font-medium text-red-700">{erro}</p>
          <p className="mt-1 text-xs text-muted-foreground">Isso não significa que não há residentes cadastrados.</p>
          <Button onClick={load} className="mt-4">Tentar novamente</Button>
        </div>
      ) : (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map(r => {
          const anos = idade(r.data_nascimento)
          const leito = leitos?.get(r.id)
          return (
          // relative: é o bloco de contenção do overlay do link (after:inset-0). min-w-0 impede
          // que o `truncate` do nome (white-space: nowrap) eleve o min-content da coluna, estique
          // o card além do viewport e gere rolagem lateral na página.
          <div key={r.id} className="card relative min-w-0 transition hover:shadow-cardHover">
            {/* O link envolve só identificação e navegação: alergias, grau e CPF ficam fora dele
                para não inflar o nome acessível. O `after:inset-0` devolve ao card inteiro a área
                de toque que o link visível perdeu — sem ele, só ~30% da altura do card navegava,
                embora o card inteiro sinalizasse clique pela sombra de hover. O anel de foco vai
                no mesmo overlay, coincidindo com a área clicável real. Efeito colateral aceito:
                o texto do card deixa de ser selecionável. */}
            <Link
              to={`/residentes/${r.id}`}
              className="flex gap-3 after:absolute after:inset-0 after:rounded-card focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring/50"
            >
              {/* Decorativa: sem aria-hidden, o nome acessível começa com a inicial duplicada. */}
              <div aria-hidden="true" className="flex size-12 shrink-0 items-center justify-center rounded-full bg-brand-soft text-lg font-bold text-primary">{r.nome[0]}</div>
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold text-foreground">{r.nome}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {r.situacao} • {formatDate(r.data_nascimento)}{anos !== null ? ` (${anos} anos)` : ''}
                  {/* Sexo não identifica o residente e fica fora do nome acessível. */}
                  <span aria-hidden="true"> • {r.sexo || '—'}</span>
                </div>
              </div>
            </Link>
            {(r.alergias || r.restricoes) && (
              <div className="mt-3 flex gap-2 rounded-lg border border-red-100 bg-red-50 p-2 text-xs text-red-700">
                <TriangleAlert data-icone="alerta" className="size-4 shrink-0" aria-hidden="true" />
                <span className="truncate">{r.alergias || r.restricoes}</span>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              {/* Campo legado do cadastro (a fonte oficial do grau é GrauDependencia,
                  exibida no prontuário). Mantido aqui por compatibilidade (Issue #34). */}
              <span className="badge-success">{r.grau_dependencia || 'Sem grau'}</span>
              {leito && (
                <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-muted-foreground">
                  <BedDouble className="size-3.5" aria-hidden="true" /> {leito}
                </span>
              )}
              {r.cpf && <span className="rounded-full bg-muted px-2 py-1 text-muted-foreground">CPF {r.cpf}</span>}
            </div>
          </div>
          )
        })}
        {/* Vazio legítimo: a consulta teve sucesso e devolveu este resultado.
            Distingue "não há cadastro" de "a busca não achou". */}
        {filtered.length === 0 && (
          <div className="card col-span-full py-16 text-center text-muted-foreground">
            {items.length === 0 ? 'Nenhum residente cadastrado' : 'Nenhum residente encontrado para esta busca'}
          </div>
        )}
      </div>
      )}

      <Dialog open={open} onOpenChange={aberto => { setOpen(aberto); if (!aberto) setMsg('') }}>
        <DialogContent title="Novo residente" description="Os dados completos e a admissão seguem depois, no próprio processo.">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="res-nome">Nome completo</Label>
              <Input id="res-nome" placeholder="Nome completo *" value={form.nome} onChange={e => setForm({ ...form, nome: e.target.value })} required />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="res-nascimento">Nascimento</Label>
                <Input id="res-nascimento" type="date" value={form.data_nascimento} onChange={e => setForm({ ...form, data_nascimento: e.target.value })} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="res-sexo">Sexo</Label>
                <select
                  id="res-sexo"
                  className="flex h-12 w-full rounded-lg border border-input bg-card px-3 text-[16px] text-foreground focus-visible:border-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                  value={form.sexo}
                  onChange={e => setForm({ ...form, sexo: e.target.value })}
                >
                  <option value="M">Masculino</option>
                  <option value="F">Feminino</option>
                  <option value="Outro">Outro</option>
                </select>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="res-cpf">CPF (opcional)</Label>
              <Input id="res-cpf" inputMode="numeric" placeholder="CPF (000.000.000-00) — opcional validado" value={form.cpf} onChange={e => setForm({ ...form, cpf: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="res-cns">CNS (opcional)</Label>
              <Input id="res-cns" inputMode="numeric" placeholder="CNS 15 dígitos — opcional" value={form.cns} onChange={e => setForm({ ...form, cns: e.target.value })} />
            </div>
            {/* UX-03 (#76): a situação não é escolhida no cadastro. Todo residente
                entra "Em admissao" e só passa a "Ativo" ao concluir a admissão;
                hospitalização é governada por Ausências. */}
            <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
              O residente entra como <strong>Em admissão</strong>. Ele passa a <strong>Ativo</strong> quando a admissão é concluída, em Admissões.
            </p>
            {msg && <Alert variant="error">{msg}</Alert>}
            <Button type="submit" className="w-full" disabled={salvando}>
              {salvando ? <><Loader2 className="animate-spin" aria-hidden="true" /> Salvando…</> : 'Salvar'}
            </Button>
            <p className="text-center text-xs text-muted-foreground">CPF e CNS validados no backend. Duplicidade impede cadastro.</p>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
