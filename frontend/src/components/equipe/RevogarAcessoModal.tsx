import { useState } from 'react'
import { Modal } from '../Modal'
import type { Funcionario, User } from '../../types/equipe'

interface RevogarAcessoModalProps {
  open: boolean
  onClose: () => void
  funcionario: Funcionario | null
  usuario: User | null
  onConfirm: (usuarioId: string) => Promise<void>
}

export function RevogarAcessoModal({ open, onClose, funcionario, usuario, onConfirm }: RevogarAcessoModalProps) {
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)

  function handleClose() {
    setMsg('')
    onClose()
  }

  async function handleConfirm() {
    if (!usuario) return
    setMsg('')
    setSaving(true)
    try {
      await onConfirm(usuario.id)
      handleClose()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao revogar acesso')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Revogar acesso">
      <div className="space-y-4">
        <div className="p-4 rounded-xl bg-red-50 border border-red-200">
          <div className="flex items-start gap-3">
            <span className="text-xl mt-0.5">⚠️</span>
            <div>
              <p className="text-sm font-medium text-danger">Atenção: esta ação é irreversível imediata</p>
              <p className="text-sm text-textMuted mt-1">
                O acesso de <strong>{usuario?.nome}</strong> ({usuario?.email}) será revogado.
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-2 text-sm text-textMuted">
          <p>O que acontece quando o acesso é revogado:</p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>O usuário não poderá mais fazer login nesta ILPI</li>
            <li>As sessões atuais serão encerradas</li>
            <li>O registro do funcionário ({funcionario?.nome}) <strong>será preservado</strong></li>
            <li>O histórico não será perdido</li>
          </ul>
          <p className="text-xs text-textMuted mt-2">
            Esta ação não exclui o funcionário — apenas remove o acesso ao sistema.
          </p>
        </div>

        {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}

        <div className="flex gap-3">
          <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancelar</button>
          <button
            onClick={handleConfirm}
            className="flex-1 px-5 py-3 rounded-xl font-semibold text-white bg-danger hover:bg-red-700 transition min-h-[44px] flex items-center justify-center gap-2"
            disabled={saving}
          >
            {saving ? 'Revogando...' : 'Revogar acesso'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
