import { useState } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Modal } from '../Modal'
import type { Funcionario } from '../../types/equipe'

interface InativarFuncionarioModalProps {
  open: boolean
  onClose: () => void
  funcionario: Funcionario | null
  onConfirm: (funcionarioId: string) => Promise<void>
}

export function InativarFuncionarioModal({ open, onClose, funcionario, onConfirm }: InativarFuncionarioModalProps) {
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)

  function handleClose() {
    setMsg('')
    onClose()
  }

  async function handleConfirm() {
    if (!funcionario) return
    setMsg('')
    setSaving(true)
    try {
      await onConfirm(funcionario.id)
      handleClose()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao inativar funcionário')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Inativar funcionário">
      <div className="space-y-4">
        <div className="p-4 rounded-xl bg-orange-50 border border-orange-200">
          <div className="flex items-start gap-3">
            <TriangleAlert className="mt-0.5 size-5 shrink-0 text-orange-700" aria-hidden="true" />
            <div>
              <p className="text-sm font-medium text-orange-700">Confirmar inativação</p>
              <p className="text-sm text-textMuted mt-1">
                Deseja inativar o funcionário <strong>{funcionario?.nome}</strong>?
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-2 text-sm text-textMuted">
          <p>O que acontece quando o funcionário é inativado:</p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>O histórico do funcionário será <strong>preservado</strong></li>
            <li>O acesso operacional será bloqueado conforme regras do sistema</li>
            <li>O registro <strong>não será excluído fisicamente</strong></li>
            <li>O funcionário não receberá novas tarefas ou escalas</li>
          </ul>
          <p className="text-xs text-textMuted mt-2">
            Esta ação altera a situação do funcionário — não confunda com revogação de acesso.
          </p>
        </div>

        {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}

        <div className="flex gap-3">
          <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancelar</button>
          <button
            onClick={handleConfirm}
            className="flex-1 px-5 py-3 rounded-xl font-semibold text-white bg-orange-500 hover:bg-orange-600 transition min-h-[44px] flex items-center justify-center gap-2"
            disabled={saving}
          >
            {saving ? 'Inativando...' : 'Inativar funcionário'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
