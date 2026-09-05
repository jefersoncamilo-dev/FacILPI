import { useState } from 'react'
import { Modal } from '../Modal'
import type { Funcionario, User } from '../../types/equipe'

interface VincularUsuarioModalProps {
  open: boolean
  onClose: () => void
  funcionario: Funcionario | null
  usuarios: User[]
  onConfirm: (funcionarioId: string, usuarioId: string) => Promise<void>
}

export function VincularUsuarioModal({ open, onClose, funcionario, usuarios, onConfirm }: VincularUsuarioModalProps) {
  const [selectedUserId, setSelectedUserId] = useState('')
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [search, setSearch] = useState('')

  const availableUsers = usuarios.filter(u => {
    if (!u.ativo) return false
    if (funcionario?.usuario_id === u.id) return false
    if (search) {
      const q = search.toLowerCase()
      return u.nome.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    }
    return true
  })

  function handleClose() {
    setSelectedUserId('')
    setMsg('')
    setSearch('')
    onClose()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!funcionario || !selectedUserId) return
    setMsg('')
    setSaving(true)
    try {
      await onConfirm(funcionario.id, selectedUserId)
      handleClose()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao vincular usuário')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Vincular usuário existente">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="p-3 rounded-xl bg-slate-50 border border-slate-200">
          <p className="text-xs text-textMuted">Vinculando usuário ao funcionário:</p>
          <p className="text-sm text-textMain font-semibold mt-0.5">{funcionario?.nome}</p>
        </div>

        <div>
          <label className="text-xs text-textMuted font-medium">Buscar usuário</label>
          <input
            className="input mt-1"
            placeholder="Nome ou e-mail..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div className="max-h-60 overflow-auto border border-slate-200 rounded-xl divide-y divide-slate-100">
          {availableUsers.length === 0 ? (
            <div className="p-4 text-center text-sm text-textMuted">
              Nenhum usuário disponível encontrado
            </div>
          ) : (
            availableUsers.map(u => (
              <label
                key={u.id}
                className={`flex items-center gap-3 p-3 cursor-pointer hover:bg-slate-50 transition min-h-[44px] ${selectedUserId === u.id ? 'bg-primaryLight/30' : ''}`}
              >
                <input
                  type="radio"
                  name="usuario"
                  value={u.id}
                  checked={selectedUserId === u.id}
                  onChange={() => setSelectedUserId(u.id)}
                  className="w-5 h-5 text-primary focus:ring-primary"
                />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-textMain truncate">{u.nome}</div>
                  <div className="text-xs text-textMuted truncate">{u.email}</div>
                </div>
              </label>
            ))
          )}
        </div>

        {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}

        <div className="flex gap-3">
          <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancelar</button>
          <button type="submit" className="btn-primary flex-1" disabled={saving || !selectedUserId}>
            {saving ? 'Vinculando...' : 'Vincular'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
