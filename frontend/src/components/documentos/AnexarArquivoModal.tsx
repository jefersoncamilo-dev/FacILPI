import { useEffect, useRef, useState } from 'react'
import { Modal } from '../Modal'
import { mensagemDeErro } from '../../services/api'
import {
  ARQUIVO_ACCEPT,
  ARQUIVO_TIPOS_ROTULO,
  anexarArquivo,
  formatarTamanho,
  validarArquivo,
  type Documento,
} from '../../services/documentos'

interface Props {
  open: boolean
  onClose: () => void
  onAnexado: () => void
  /** Documento que receberá o arquivo. `null` mantém o modal fechado. */
  documento: Documento | null
  /** Chamado quando o backend recusa por permissão (403). */
  onPermissaoNegada?: () => void
}

export function AnexarArquivoModal({ open, onClose, onAnexado, documento, onPermissaoNegada }: Props) {
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)
  // O input de arquivo é não controlado: sem limpar o elemento, reabrir o modal
  // mostraria o nome do arquivo do documento anterior.
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    setArquivo(null)
    setErro('')
    if (inputRef.current) inputRef.current.value = ''
  }, [open, documento?.id])

  async function confirmar() {
    if (!documento) return
    const invalido = validarArquivo(arquivo)
    if (invalido || !arquivo) {
      setErro(invalido ?? 'Selecione um arquivo.')
      return
    }
    setEnviando(true)
    setErro('')
    try {
      await anexarArquivo(documento.id, arquivo)
      onAnexado()
    } catch (e) {
      // 409 (já anexado / já validado), 413 (tamanho), 422 (vazio ou tipo) e 404
      // chegam com `message` própria do backend; o normalizador já a extrai.
      setErro(mensagemDeErro(e, 'Não foi possível anexar o arquivo.'))
      if ((e as { response?: { status?: number } })?.response?.status === 403) {
        onPermissaoNegada?.()
      }
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Anexar arquivo">
      <div className="space-y-4">
        {documento && (
          <p className="text-sm text-textMuted">
            Documento: <span className="font-medium text-textMain break-words">{documento.tipo}</span>
          </p>
        )}

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="doc-arquivo">Arquivo</label>
          <input
            id="doc-arquivo"
            ref={inputRef}
            type="file"
            className="input"
            accept={ARQUIVO_ACCEPT}
            onChange={e => { setArquivo(e.target.files?.[0] ?? null); setErro('') }}
          />
          <p className="text-xs text-textMuted mt-1">{ARQUIVO_TIPOS_ROTULO}</p>
        </div>

        {arquivo && (
          <p className="text-sm text-textMuted break-words">
            Selecionado: <span className="font-medium text-textMain">{arquivo.name}</span>
            {arquivo.size > 0 && <> — {formatarTamanho(arquivo.size)}</>}
          </p>
        )}

        {erro && <div role="alert" className="text-sm text-danger">{erro}</div>}

        <button type="button" onClick={confirmar} disabled={enviando} className="btn-primary w-full disabled:opacity-60">
          {enviando ? 'Enviando…' : 'Anexar'}
        </button>
        <p className="text-xs text-textMuted text-center">
          O tipo é conferido pelo conteúdo do arquivo, não pela extensão. Cada documento recebe um arquivo.
        </p>
      </div>
    </Modal>
  )
}
