import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, formatDate, mensagemDeErro } from '../services/api'
import { Modal } from '../components/Modal'

export function Residentes() {
  const [items, setItems] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<any>({ nome: '', data_nascimento: '', cpf: '', cns: '', sexo: 'M', situacao: 'Em admissao' })
  const [msg, setMsg] = useState('')
  const [q, setQ] = useState('')

  async function load() {
    const { data } = await api.get('/residentes/')
    setItems(data)
  }
  useEffect(() => { load() }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setMsg('')
    try {
      const payload: any = { ...form }
      // clean cpf/cns to digits
      if (payload.cpf) payload.cpf = payload.cpf.replace(/\D/g, '')
      if (payload.cns) payload.cns = payload.cns.replace(/\D/g, '')
      if (!payload.cpf) delete payload.cpf
      if (!payload.cns) delete payload.cns
      await api.post('/residentes/', payload)
      setOpen(false)
      setForm({ nome: '', data_nascimento: '', cpf: '', cns: '', sexo: 'M', situacao: 'Em admissao' })
      load()
    } catch (e: any) {
      setMsg(mensagemDeErro(e, 'Erro ao salvar'))
    }
  }

  const filtered = items.filter(i => !q || i.nome.toLowerCase().includes(q.toLowerCase()) || (i.cpf||'').includes(q))

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-primaryDeep">Residentes</h1>
          <p className="text-textMuted text-sm">Centro da operação — cadastro formal com validações</p>
        </div>
        <button onClick={() => setOpen(true)} className="btn-primary">+ Novo residente</button>
      </div>

      <div className="card p-3 flex gap-3">
        <input className="input flex-1" placeholder="Buscar por nome ou CPF..." value={q} onChange={e => setQ(e.target.value)} />
        <span className="hidden sm:inline-flex items-center text-sm text-textMuted whitespace-nowrap">{filtered.length} residentes</span>
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {filtered.map(r => (
          // relative: é o bloco de contenção do overlay do link (after:inset-0). min-w-0 impede
          // que o `truncate` do nome (white-space: nowrap) eleve o min-content da coluna, estique
          // o card além do viewport e gere rolagem lateral na página.
          <div key={r.id} className="card hover:shadow-cardHover transition min-w-0 relative">
            {/* O link envolve só identificação e navegação: alergias, grau e CPF ficam fora dele
                para não inflar o nome acessível. O `after:inset-0` devolve ao card inteiro a área
                de toque que o link visível perdeu — sem ele, só ~30% da altura do card navegava,
                embora o card inteiro sinalizasse clique pela sombra de hover. O anel de foco vai
                no mesmo overlay, coincidindo com a área clicável real. Efeito colateral aceito:
                o texto do card deixa de ser selecionável. */}
            <Link
              to={`/residentes/${r.id}`}
              className="flex gap-3 after:absolute after:inset-0 after:rounded-card focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-primary/40"
            >
              {/* Decorativa: sem aria-hidden, o nome acessível começa com a inicial duplicada. */}
              <div aria-hidden="true" className="w-12 h-12 rounded-full bg-primaryLight flex items-center justify-center font-bold text-primary text-lg shrink-0">{r.nome[0]}</div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold truncate">{r.nome}</div>
                <div className="text-xs text-textMuted truncate">
                  {r.situacao} • {formatDate(r.data_nascimento)}
                  {/* Sexo não identifica o residente e fica fora do nome acessível. */}
                  <span aria-hidden="true"> • {r.sexo || '—'}</span>
                </div>
              </div>
            </Link>
            {(r.alergias || r.restricoes) && (
              <div className="mt-3 p-2 rounded-xl bg-red-50 border border-red-100 text-xs text-danger flex gap-2">
                <span aria-hidden="true">⚠️</span> <span className="truncate">{r.alergias || r.restricoes}</span>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="badge-success">{r.grau_dependencia || 'Sem grau'}</span>
              {r.cpf && <span className="px-2 py-1 bg-slate-100 rounded-full">CPF {r.cpf}</span>}
            </div>
          </div>
        ))}
        {filtered.length===0 && <div className="col-span-full py-16 text-center text-textMuted card">Nenhum residente encontrado</div>}
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="Novo residente">
        <form onSubmit={handleSubmit} className="space-y-4">
          <input className="input" placeholder="Nome completo *" value={form.nome} onChange={e => setForm({...form, nome: e.target.value})} required />
          <div className="grid grid-cols-2 gap-3">
            <input className="input" type="date" value={form.data_nascimento} onChange={e => setForm({...form, data_nascimento: e.target.value})} required />
            <select className="input" value={form.sexo} onChange={e => setForm({...form, sexo: e.target.value})}>
              <option value="M">Masculino</option>
              <option value="F">Feminino</option>
              <option value="Outro">Outro</option>
            </select>
          </div>
          <input className="input" placeholder="CPF (000.000.000-00) — opcional validado" value={form.cpf} onChange={e => setForm({...form, cpf: e.target.value})} />
          <input className="input" placeholder="CNS 15 dígitos — opcional" value={form.cns} onChange={e => setForm({...form, cns: e.target.value})} />
          <select className="input" value={form.situacao} onChange={e => setForm({...form, situacao: e.target.value})}>
            <option>Pré-admissão</option>
            <option>Em admissao</option>
            <option>Ativo</option>
            <option>Hospitalizado</option>
            <option>Inativo</option>
          </select>
          {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}
          <button type="submit" className="btn-primary w-full">Salvar</button>
          <p className="text-xs text-textMuted text-center">CPF e CNS validados no backend. Duplicidade impede cadastro.</p>
        </form>
      </Modal>
    </div>
  )
}
