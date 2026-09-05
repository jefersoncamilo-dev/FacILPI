import { NavLink, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { Modal } from './Modal'
import { ContextSwitcher } from './ContextSwitcher'

const menu = [
  { to: '/', label: 'Início', icon: '🏠' },
  { to: '/plantao', label: 'Meu Plantão', icon: '🩺' },
  { to: '/residentes', label: 'Residentes', icon: '👥' },
  { to: '/admissoes', label: 'Admissões', icon: '📋' },
  { to: '/avaliacoes', label: 'Avaliações', icon: '📊' },
  { to: '/plano', label: 'Plano de Cuidados', icon: '📝' },
  { to: '/cuidados', label: 'Cuidados Diários', icon: '💧' },
  { to: '/medicacao', label: 'Medicação', icon: '💊' },
  { to: '/sinais', label: 'Sinais Vitais', icon: '❤️' },
  { to: '/intercorrencias', label: 'Intercorrências', icon: '⚠️' },
  { to: '/agenda', label: 'Agenda Clínica', icon: '📅' },
  { to: '/passagem', label: 'Passagem de Plantão', icon: '🔄' },
  { to: '/quartos', label: 'Quartos e Leitos', icon: '🛏️' },
  { to: '/equipe', label: 'Equipe e Escalas', icon: '👩‍⚕️' },
  { to: '/estoque', label: 'Estoque', icon: '📦' },
  { to: '/financeiro', label: 'Financeiro', icon: '💰' },
  { to: '/familia', label: 'Portal da Família', icon: '👨‍👩‍👧' },
  { to: '/relatorios', label: 'Relatórios', icon: '📈' },
  { to: '/supervisao', label: 'Supervisão', icon: '👁️' },
  { to: '/compliance', label: 'Compliance e Fiscalização', icon: '✅' },
  { to: '/auditoria', label: 'Auditoria', icon: '🔍' },
  { to: '/config', label: 'Configurações', icon: '⚙️' },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  const [nova, setNova] = useState('')
  const [confirmar, setConfirmar] = useState('')
  const [msg, setMsg] = useState('')
  const { user, logout, updatePassword } = useAuth()
  const navigate = useNavigate()

  async function handlePwd() {
    if (nova !== confirmar) { setMsg('Senhas não conferem'); return }
    try {
      await updatePassword(nova, confirmar)
      setMsg('Senha alterada com sucesso')
      setTimeout(() => { setPwdOpen(false); setMsg(''); setNova(''); setConfirmar('') }, 1200)
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Erro ao alterar senha')
    }
  }

  return (
    <div className="min-h-screen bg-bg flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex w-[280px] bg-white border-r border-slate-100 flex-col sticky top-0 h-screen overflow-auto">
        <div className="px-6 py-6 border-b">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primaryDeep flex items-center justify-center text-white font-bold">FL</div>
            <div>
              <div className="font-bold text-primaryDeep leading-none">FáciLPI</div>
              <div className="text-xs text-textMuted">Gestão & Cuidados</div>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {menu.map(m => (
            <NavLink key={m.to} to={m.to} className={({ isActive }) => `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium min-h-[44px] ${isActive ? 'bg-primary text-white shadow-sm' : 'text-textMuted hover:bg-slate-50 hover:text-textMain'}`}>
              <span>{m.icon}</span> {m.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t space-y-3">
          <ContextSwitcher />
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-primaryLight flex items-center justify-center text-primary font-semibold">{user?.nome?.[0]?.toUpperCase() || 'U'}</div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate">{user?.nome || 'Usuário'}</div>
              <div className="text-xs text-textMuted truncate">{user?.email}</div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 mt-3">
            <button onClick={() => setPwdOpen(true)} className="btn-secondary text-xs py-2">Alterar senha</button>
            <button onClick={logout} className="bg-slate-900 text-white rounded-xl py-2 text-xs font-medium hover:bg-black">Sair</button>
          </div>
        </div>
      </aside>

      {/* Mobile */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="lg:hidden sticky top-0 z-30 bg-white border-b px-4 h-[64px] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => setOpen(true)} className="w-11 h-11 rounded-xl bg-slate-900 text-white flex items-center justify-center">☰</button>
            <span className="font-bold text-primaryDeep">FáciLPI</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => navigate('/plantao')} className="w-11 h-11 rounded-xl bg-primary text-white">🩺</button>
            <button onClick={logout} className="w-11 h-11 rounded-full bg-primaryLight text-primary font-bold">{user?.nome?.[0] || 'U'}</button>
          </div>
        </header>

        {open && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
            <div className="absolute left-0 top-0 bottom-0 w-[85%] max-w-[320px] bg-white overflow-auto">
              <div className="p-4 border-b flex items-center justify-between">
                <span className="font-bold">Menu</span>
                <button onClick={() => setOpen(false)} className="w-10 h-10 rounded-full hover:bg-slate-100">×</button>
              </div>
              <div className="p-3 border-b">
                <ContextSwitcher />
              </div>
              <nav className="p-3 space-y-1">
                {menu.map(m => (
                  <NavLink key={m.to} to={m.to} onClick={() => setOpen(false)} className={({ isActive }) => `flex items-center gap-3 px-3 py-3 rounded-xl text-sm font-medium ${isActive ? 'bg-primary text-white' : 'text-textMuted hover:bg-slate-50'}`}>
                    <span>{m.icon}</span> {m.label}
                  </NavLink>
                ))}
              </nav>
            </div>
          </div>
        )}

        <main className="flex-1 p-4 lg:p-8 pb-20 lg:pb-8 max-w-[1400px] w-full mx-auto">
          {children}
        </main>

        {/* Bottom nav mobile */}
        <nav className="lg:hidden fixed bottom-0 inset-x-0 bg-white border-t flex justify-around py-2 pb-safe">
          {[
            { to: '/', label: 'Início', icon: '🏠' },
            { to: '/plantao', label: 'Plantão', icon: '🩺' },
            { to: '/residentes', label: 'Residentes', icon: '👥' },
            { to: '/alertas', label: 'Alertas', icon: '🔔' },
            { to: '/config', label: 'Mais', icon: '⋯' },
          ].map(m => (
            <NavLink key={m.to} to={m.to} className={({ isActive }) => `flex flex-col items-center gap-1 px-3 py-1 rounded-xl min-w-[56px] min-h-[44px] justify-center ${isActive ? 'text-primary' : 'text-textMuted'}`}>
              <span className="text-lg">{m.icon}</span>
              <span className="text-[11px] font-medium">{m.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      <Modal open={pwdOpen} onClose={() => setPwdOpen(false)} title="Alterar senha">
        <div className="space-y-4">
          <input className="input" type="password" placeholder="Nova senha (mín. 8, maiúscula, minúscula, número)" value={nova} onChange={e => setNova(e.target.value)} />
          <input className="input" type="password" placeholder="Confirmar nova senha" value={confirmar} onChange={e => setConfirmar(e.target.value)} />
          {msg && <div className="text-sm p-3 rounded-xl bg-amber-50 text-amber-800 border border-amber-200">{msg}</div>}
          <button onClick={handlePwd} className="btn-primary w-full">Salvar</button>
        </div>
      </Modal>
    </div>
  )
}
