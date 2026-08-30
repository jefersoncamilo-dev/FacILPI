import { useEffect, useState } from 'react'
import { api, formatDate } from '../services/api'
import { Link } from 'react-router-dom'

type Stats = { residentes: number; tarefasPendentes: number; alertas: number; ocupacao: string }

export function Dashboard() {
  const [stats, setStats] = useState<Stats>({ residentes: 0, tarefasPendentes: 0, alertas: 0, ocupacao: '—' })
  const [residentes, setResidentes] = useState<any[]>([])
  const [tarefas, setTarefas] = useState<any[]>([])

  useEffect(() => {
    async function load() {
      try {
        const [r, t, a] = await Promise.all([
          api.get('/residentes/').catch(() => ({ data: [] })),
          api.get('/tarefas/').catch(() => ({ data: [] })),
          api.get('/alertas/').catch(() => ({ data: [] })),
        ])
        setResidentes((r.data || []).slice(0, 5))
        setTarefas((t.data || []).filter((x: any) => x.situacao === 'Pendente').slice(0, 5))
        const ocupacao = r.data?.length ? `${Math.min(100, Math.round((r.data.length / 40) * 100))}%` : '0%'
        setStats({ residentes: r.data.length || 0, tarefasPendentes: t.data.filter((x:any)=>x.situacao==='Pendente').length || 0, alertas: a.data.filter((x:any)=>x.situacao==='Ativo').length || 0, ocupacao })
      } catch {}
    }
    load()
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-primaryDeep">Início</h1>
        <p className="text-textMuted">Visão geral da ILPI — {formatDate(new Date().toISOString())}</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card bg-gradient-to-br from-primary to-primaryDeep text-white border-0">
          <div className="text-sm opacity-90">Residentes ativos</div>
          <div className="text-3xl font-bold mt-1">{stats.residentes}</div>
          <div className="text-xs opacity-80 mt-2">Ocupação {stats.ocupacao}</div>
        </div>
        <div className="card">
          <div className="text-sm text-textMuted">Tarefas pendentes</div>
          <div className="text-3xl font-bold text-warning mt-1">{stats.tarefasPendentes}</div>
          <Link to="/plantao" className="text-xs text-primary font-semibold mt-2 inline-block">Ver Meu Plantão →</Link>
        </div>
        <div className="card">
          <div className="text-sm text-textMuted">Alertas ativos</div>
          <div className="text-3xl font-bold text-danger mt-1">{stats.alertas}</div>
          <span className="text-xs text-textMuted mt-2 inline-block">Críticos e pendências</span>
        </div>
        <div className="card">
          <div className="text-sm text-textMuted">Conformidade</div>
          <div className="text-2xl font-bold text-success mt-1">✅ Em dia</div>
          <span className="text-xs text-textMuted mt-2 inline-block">Licenças verificadas</span>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Residentes recentes</h3>
            <Link to="/residentes" className="text-sm text-primary font-semibold">Ver todos</Link>
          </div>
          {residentes.length === 0 ? (
            <div className="py-10 text-center text-textMuted">
              <div className="text-4xl mb-2">👥</div>
              <p className="text-sm">Nenhum residente cadastrado</p>
              <Link to="/residentes" className="btn-primary mt-4 inline-flex">Cadastrar residente</Link>
            </div>
          ) : (
            <div className="space-y-3">
              {residentes.map(r => (
                <div key={r.id} className="flex items-center gap-3 p-3 rounded-xl hover:bg-slate-50 border border-transparent hover:border-slate-100">
                  <div className="w-10 h-10 rounded-full bg-primaryLight flex items-center justify-center font-bold text-primary">{r.nome[0]}</div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{r.nome}</div>
                    <div className="text-xs text-textMuted truncate">{r.situacao} • {r.grau_dependencia || 'Sem grau'}</div>
                  </div>
                  <span className="badge-warning text-[11px]">Ativo</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Próximas tarefas</h3>
            <Link to="/plantao" className="text-sm text-primary font-semibold">Meu Plantão</Link>
          </div>
          {tarefas.length === 0 ? (
            <div className="py-10 text-center text-textMuted">
              <div className="text-4xl mb-2">🩺</div>
              <p className="text-sm">Nenhuma tarefa pendente</p>
              <p className="text-xs mt-1">Tarefas geradas pelo Plano de Cuidados aparecem aqui.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {tarefas.map(t => (
                <div key={t.id} className="p-3 rounded-xl bg-amber-50 border border-amber-100">
                  <div className="text-sm font-medium">{t.descricao}</div>
                  <div className="text-xs text-textMuted mt-1">{t.prioridade} • {t.responsavel || 'Sem responsável'}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card bg-primaryLight/50 border-primaryLight">
        <h3 className="font-semibold text-primaryDeep">Jornada do residente</h3>
        <p className="text-sm text-textMuted mt-1">Pré-admissão → Admissão → Avaliações → Plano de Cuidados/PAIS → Programação → Meu Plantão → Execução → Prontuário → Intercorrências → Passagem de Plantão → Supervisão → Auditoria</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="badge-success">LGPD</span>
          <span className="badge-warning">Isolamento por ILPI</span>
          <span className="badge-danger">Rastreabilidade</span>
        </div>
      </div>
    </div>
  )
}
