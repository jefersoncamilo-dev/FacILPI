import { useState } from 'react'
import { Modal } from '../Modal'
import type { User, Funcionario, Perfil } from '../../types/equipe'

interface UsuariosSectionProps {
  usuarios: User[]
  funcionarios: Funcionario[]
  perfis: Perfil[]
  searchQuery: string
  onSearchChange: (q: string) => void
  loading: boolean
  onEditUser: (user: User) => void
  onResetPassword: (userId: string) => Promise<string>
  onRevogarAcesso: (user: User) => void
}

export function UsuariosSection({
  usuarios, funcionarios, perfis, searchQuery, onSearchChange,
  loading, onEditUser, onResetPassword, onRevogarAcesso,
}: UsuariosSectionProps) {
  const [resetModalOpen, setResetModalOpen] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [senhaTemp, setSenhaTemp] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const filtered = usuarios.filter(u => {
    if (!searchQuery) return true
    const q = searchQuery.toLowerCase()
    return u.nome.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
  })

  function getFuncionarioNome(usuarioId: string) {
    const f = funcionarios.find(f => f.usuario_id === usuarioId)
    return f?.nome || null
  }

  function getPerfilNome(usuarioId: string) {
    const f = funcionarios.find(f => f.usuario_id === usuarioId)
    return f ? (f.profissao || f.cargo || null) : null
  }

  function openReset(user: User) {
    setSelectedUser(user)
    setSenhaTemp(null)
    setMsg('')
    setResetModalOpen(true)
  }

  async function handleReset() {
    if (!selectedUser) return
    setSaving(true)
    setMsg('')
    try {
      const temp = await onResetPassword(selectedUser.id)
      setSenhaTemp(temp)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao redefinir senha')
    } finally {
      setSaving(false)
    }
  }

  function openEdit(user: User) {
    setSelectedUser(user)
    setEditName(user.nome)
    setMsg('')
    setEditModalOpen(true)
  }

  async function handleEditSave() {
    if (!selectedUser) return
    setSaving(true)
    setMsg('')
    try {
      await onEditUser({ ...selectedUser, nome: editName.trim() })
      setEditModalOpen(false)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao salvar')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map(i => (
          <div key={i} className="card animate-pulse">
            <div className="flex gap-3">
              <div className="w-11 h-11 rounded-full bg-slate-200" />
              <div className="flex-1 space-y-2">
                <div className="h-4 bg-slate-200 rounded w-1/3" />
                <div className="h-3 bg-slate-100 rounded w-1/2" />
              </div>
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map(u => (
          <div key={u.id} className="card hover:shadow-cardHover transition min-w-0">
            <div className="flex items-start gap-3">
              <div className="w-11 h-11 rounded-full bg-primaryLight flex items-center justify-center font-bold text-primary text-base shrink-0">
                {u.nome[0]?.toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-textMain truncate">{u.nome}</div>
                <div className="text-xs text-textMuted truncate">{u.email}</div>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <span className={u.ativo ? 'badge-success' : 'badge-danger'}>
                {u.ativo ? 'Ativo' : 'Inativo'}
              </span>
              {u.exige_troca_senha && (
                <span className="badge-warning">Primeiro acesso pendente</span>
              )}
              {getFuncionarioNome(u.id) && (
                <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-50 text-textMuted border border-slate-200">
                  Vínculo: {getFuncionarioNome(u.id)}
                </span>
              )}
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() => openEdit(u)}
                className="text-xs px-3 py-2 rounded-lg border border-slate-200 hover:bg-slate-50 text-textMuted min-h-[44px] min-w-[44px] flex items-center justify-center"
              >
                ✏️ Editar
              </button>
              <button
                onClick={() => openReset(u)}
                className="text-xs px-3 py-2 rounded-lg border border-slate-200 hover:bg-slate-50 text-textMuted min-h-[44px] min-w-[44px] flex items-center justify-center"
              >
                🔑 Resetar senha
              </button>
              {u.ativo && (
                <button
                  onClick={() => onRevogarAcesso(u)}
                  className="text-xs px-3 py-2 rounded-lg border border-red-200 hover:bg-red-50 text-danger min-h-[44px] min-w-[44px] flex items-center justify-center"
                >
                  🚫 Revogar acesso
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {filtered.length === 0 && !loading && (
        <div className="card py-16 text-center">
          <span className="text-4xl mb-3 block">👤</span>
          <p className="text-textMuted font-medium">Nenhum usuário encontrado</p>
          <p className="text-xs text-textMuted mt-1">Crie um usuário ou conceda acesso a um funcionário existente.</p>
        </div>
      )}

      {/* Edit user modal */}
      <Modal open={editModalOpen} onClose={() => setEditModalOpen(false)} title="Editar usuário">
        <div className="space-y-4">
          <div>
            <label className="text-xs text-textMuted font-medium">Nome</label>
            <input className="input mt-1" value={editName} onChange={e => setEditName(e.target.value)} minLength={2} maxLength={255} />
          </div>
          <div>
            <label className="text-xs text-textMuted font-medium">E-mail</label>
            <input className="input mt-1" value={selectedUser?.email || ''} disabled />
            <p className="text-xs text-textMuted mt-1">E-mail não pode ser alterado</p>
          </div>
          {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}
          <div className="flex gap-3">
            <button type="button" onClick={() => setEditModalOpen(false)} className="btn-secondary flex-1">Cancelar</button>
            <button onClick={handleEditSave} className="btn-primary flex-1" disabled={saving || !editName.trim()}>
              {saving ? 'Salvando...' : 'Salvar'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Reset password modal */}
      <Modal open={resetModalOpen} onClose={() => setResetModalOpen(false)} title="Resetar senha">
        {senhaTemp ? (
          <div className="space-y-4">
            <div className="text-center">
              <div className="w-14 h-14 rounded-full bg-emerald-50 flex items-center justify-center mx-auto mb-3">
                <span className="text-2xl">✅</span>
              </div>
              <h4 className="font-semibold text-textMain">Senha redefinida</h4>
              <p className="text-sm text-textMuted mt-1">Nova senha temporária para {selectedUser?.nome}:</p>
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
              <label className="text-xs text-textMuted font-medium">Senha temporária</label>
              <div className="mt-1 p-3 bg-white rounded-lg border border-slate-200 font-mono text-sm break-all select-all">
                {senhaTemp}
              </div>
            </div>
            <p className="text-xs text-textMuted text-center">
              O usuário deverá alterar esta senha no próximo login.
            </p>
            <button onClick={() => setResetModalOpen(false)} className="btn-primary w-full">Fechar</button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="p-3 rounded-xl bg-amber-50 border border-amber-200">
              <p className="text-sm text-textMuted">
                Uma nova senha temporária será gerada para <strong>{selectedUser?.nome}</strong>.
                As sessões atuais do usuário serão encerradas.
              </p>
            </div>
            {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}
            <div className="flex gap-3">
              <button type="button" onClick={() => setResetModalOpen(false)} className="btn-secondary flex-1">Cancelar</button>
              <button onClick={handleReset} className="btn-primary flex-1" disabled={saving}>
                {saving ? 'Redefinindo...' : 'Redefinir senha'}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
