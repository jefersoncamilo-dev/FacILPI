import { useEffect, useState } from 'react'
import { api, formatDateTime } from '../services/api'
import { Modal } from '../components/Modal'

export function MeuPlantao() {
  const [tarefas, setTarefas] = useState<any[]>([])
  const [filter, setFilter] = useState('Pendentes')
  const [msg, setMsg] = useState('')
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ residente_id: '', descricao: '' })

  async function load() {
    const { data } = await api.get('/tarefas/')
    setTarefas(data)
  }
  useEffect(() => { load() }, [])

  async function concluir(id: string) {
    await api.put(`/tarefas/${id}`, { situacao: 'Concluída', horario_realizado: new Date().toISOString(), executor: 'eu' })
    load()
  }
  async function create() {
    if (!form.residente_id || !form.descricao) { setMsg('Informe residente e descrição'); return }
    await api.post('/tarefas/', { residente_id: form.residente_id, descricao: form.descricao, prioridade: 'alta', situacao: 'Pendente', horario_previsto: new Date().toISOString() })
    setOpen(false); setForm({ residente_id: '', descricao: '' }); load()
  }

  const grupos: Record<string, any[]> = {
    'Pendentes': tarefas.filter(t => t.situacao === 'Pendente'),
    'Atrasadas': tarefas.filter(t => new Date(t.horario_previsto) < new Date() && t.situacao === 'Pendente'),
    'Concluídas': tarefas.filter(t => t.situacao === 'Concluída'),
  }
  const list = grupos[filter] || tarefas

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-primaryDeep">Meu Plantão</h1>
          <p className="text-textMuted text-sm">Tarefas ordenadas por prioridade e horário — mobile-first</p>
        </div>
        <button onClick={() => setOpen(true)} className="btn-primary">+ Nova tarefa</button>
      </div>

      <div className="card p-2 flex gap-2 overflow-auto">
        {['Pendentes','Atrasadas','Concluídas'].map(f => (
          <button key={f} onClick={() => setFilter(f)} className={`px-4 py-2 rounded-xl text-sm font-medium whitespace-nowrap min-h-[44px] ${filter===f ? 'bg-primary text-white' : 'bg-slate-100 text-textMuted hover:bg-slate-200'}`}>{f} ({grupos[f].length})</button>
        ))}
      </div>

      <div className="grid gap-3">
        {list.map(t => (
          <div key={t.id} className={`card flex gap-4 items-start border-l-4 ${t.prioridade==='alta' ? 'border-l-danger' : t.prioridade==='media' ? 'border-l-warning' : 'border-l-success'}`}>
            <div className="w-10 h-10 rounded-full bg-primaryLight flex items-center justify-center">🩺</div>
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate">{t.descricao}</div>
              <div className="text-xs text-textMuted mt-1">{formatDateTime(t.horario_previsto)} • {t.prioridade} • {t.responsavel || 'Sem responsável'}</div>
              {t.situacao==='Concluída' && <span className="badge-success mt-2">✅ Concluída {formatDateTime(t.horario_realizado)}</span>}
            </div>
            {t.situacao==='Pendente' && <button onClick={() => concluir(t.id)} className="btn-primary text-sm px-4 py-2">Concluir</button>}
          </div>
        ))}
        {list.length===0 && <div className="card py-16 text-center text-textMuted">{filter} — nenhuma tarefa</div>}
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="Nova tarefa">
        <div className="space-y-3">
          <input className="input" placeholder="ID do residente (copie de Residentes)" value={form.residente_id} onChange={e => setForm({...form, residente_id: e.target.value})} />
          <input className="input" placeholder="Descrição (ex: Banho, Medicação 08h)" value={form.descricao} onChange={e => setForm({...form, descricao: e.target.value})} />
          {msg && <div className="text-sm text-danger">{msg}</div>}
          <button onClick={create} className="btn-primary w-full">Criar</button>
        </div>
      </Modal>
    </div>
  )
}
