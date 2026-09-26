import { useState } from 'react'
import { Modal } from '../Modal'

/**
 * Exibe a senha temporária UMA única vez.
 *
 * O valor chega por prop e vive apenas no estado da tela que o recebeu da
 * resposta HTTP. Este componente não escreve em localStorage, sessionStorage,
 * URL, console nem em qualquer telemetria — e não deve passar a escrever.
 *
 * Não há reenvio. O único mecanismo de redefinição existente
 * (PATCH /api/usuarios/{id}/reset-password) e institucional e exige contexto de
 * ILPI, portanto e inalcancavel pelo operador global. Prometer recuperacao aqui
 * seria mentira; a entrega por canal proprio pertence ao PLATFORM-2.
 */
export function CredencialTemporariaDialog({
  open,
  onClose,
  email,
  senha,
}: {
  open: boolean
  onClose: () => void
  email: string
  senha: string
}) {
  const [copiado, setCopiado] = useState(false)

  async function copiar() {
    try {
      await navigator.clipboard.writeText(senha)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 2000)
    } catch {
      // Sem permissão de área de transferência: a senha continua visível na tela
      // para cópia manual, que é o que importa.
      setCopiado(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Senha temporária do gestor">
      <div className="space-y-4">
        <p className="text-sm text-textMain">
          Entregue estas credenciais ao gestor de <strong>{email}</strong>. Ele será obrigado a
          definir uma nova senha no primeiro acesso.
        </p>

        <div className="p-3 rounded-xl bg-slate-50 border border-slate-200">
          <div className="text-xs text-textMuted mb-1">Senha temporária</div>
          <code data-testid="senha-temporaria" className="font-mono text-base break-all">
            {senha}
          </code>
        </div>

        <button onClick={copiar} className="btn-secondary w-full min-h-[44px]">
          {copiado ? 'Copiado' : 'Copiar senha'}
        </button>

        <div
          role="alert"
          className="text-sm p-3 rounded-xl bg-orange-50 text-orange-800 border border-orange-200"
        >
          <strong>Esta senha será exibida somente agora.</strong> Ela não fica guardada e não pode
          ser consultada novamente por esta tela. Se for perdida, não há reenvio disponível neste
          fluxo.
        </div>

        <button onClick={onClose} className="btn-primary w-full min-h-[44px]">
          Já anotei, fechar
        </button>
      </div>
    </Modal>
  )
}
