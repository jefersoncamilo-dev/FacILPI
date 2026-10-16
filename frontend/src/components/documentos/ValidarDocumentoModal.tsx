import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import { mensagemDeErro } from '../../services/api'
import { validarDocumento, type Documento } from '../../services/documentos'

interface Props {
  open: boolean
  onClose: () => void
  onValidado: () => void
  /** Documento a validar. `null` mantém o modal fechado. */
  documento: Documento | null
  /** Nome do residente, quando a lista de residentes carregou. */
  residenteNome?: string
  /** Chamado quando o backend recusa por permissão (403). */
  onPermissaoNegada?: () => void
  /**
   * Chamado no 409: outra pessoa validou antes. A mensagem fica no diálogo e a
   * tela recarrega para o cartão deixar de oferecer a ação.
   */
  onJaValidado?: () => void
}

export function ValidarDocumentoModal({
  open, onClose, onValidado, documento, residenteNome, onPermissaoNegada, onJaValidado,
}: Props) {
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)
  // Depois do 409 repetir o envio só devolveria o mesmo 409.
  const [jaValidado, setJaValidado] = useState(false)

  useEffect(() => {
    if (!open) return
    setErro('')
    setJaValidado(false)
  }, [open, documento?.id])

  async function confirmar() {
    if (!documento) return
    setEnviando(true)
    setErro('')
    try {
      await validarDocumento(documento.id)
      onValidado()
    } catch (e) {
      // 409 (`DOCUMENTO_JA_VALIDADO`) e 404 chegam com `message` própria do
      // backend; o normalizador já a extrai.
      setErro(mensagemDeErro(e, 'Não foi possível validar o documento.'))
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 403) onPermissaoNegada?.()
      if (status === 409) {
        setJaValidado(true)
        onJaValidado?.()
      }
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Validar documento">
      <div className="space-y-4">
        {documento && (
          <div className="space-y-1 text-sm text-textMuted">
            <p>
              Documento: <span className="font-medium text-textMain break-words">{documento.tipo}</span>
            </p>
            {residenteNome && (
              <p>
                Residente: <span className="font-medium text-textMain break-words">{residenteNome}</span>
              </p>
            )}
          </div>
        )}

        <p className="text-sm text-textMain">
          Confirme que conferiu o documento. A validação registra você como responsável, com data e hora, e não pode ser desfeita.
        </p>

        {documento && !documento.arquivo_presente && (
          // Depois de validado, o backend recusa novo arquivo (409): avisar antes
          // é o único momento em que isso ainda pode ser evitado.
          <p className="rounded-lg border-l-4 border-l-warning bg-orange-50/60 px-3 py-2 text-sm text-textMain">
            Este documento está sem arquivo anexado. Depois de validado, não será possível anexar.
          </p>
        )}

        {erro && <div role="alert" className="text-sm text-danger">{erro}</div>}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="btn-secondary w-full sm:w-auto">
            {jaValidado ? 'Voltar' : 'Cancelar'}
          </button>
          {!jaValidado && (
            <button type="button" onClick={confirmar} disabled={enviando} className="btn-primary w-full sm:w-auto disabled:opacity-60">
              {enviando ? 'Validando…' : 'Validar'}
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}
