import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import { mensagemDeErro } from '../../services/api'
import {
  criarDocumento,
  formularioVazio,
  montarPayload,
  type FormularioDocumento,
} from '../../services/documentos'
import type { ResidenteOpcao } from '../intercorrencias/RegistrarIntercorrenciaModal'

interface Props {
  open: boolean
  onClose: () => void
  onCadastrado: () => void
  /**
   * Residente já definido pelo contexto (Prontuário ou filtro). Quando presente,
   * o campo não é editável: não se cadastra documento no prontuário de outro.
   */
  residenteFixo?: ResidenteOpcao | null
  /** Opções usadas apenas quando não há residente fixo. */
  residentes?: ResidenteOpcao[]
  /** Chamado quando o backend recusa por permissão (403). */
  onPermissaoNegada?: () => void
}

export function CadastrarDocumentoModal({
  open,
  onClose,
  onCadastrado,
  residenteFixo = null,
  residentes = [],
  onPermissaoNegada,
}: Props) {
  const [form, setForm] = useState<FormularioDocumento>(() => formularioVazio())
  const [residenteId, setResidenteId] = useState('')
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)

  // Reabrir sempre começa limpo: reaproveitar valores de um cadastro anterior
  // por engano criaria documento com metadado do residente errado.
  useEffect(() => {
    if (!open) return
    setForm(formularioVazio())
    setResidenteId(residenteFixo?.id ?? '')
    setErro('')
  }, [open, residenteFixo?.id])

  async function confirmar() {
    const { erro: invalido, payload } = montarPayload(residenteId, form)
    if (invalido || !payload) {
      setErro(invalido ?? 'Não foi possível montar o documento.')
      return
    }
    setSalvando(true)
    setErro('')
    try {
      await criarDocumento(payload)
      onCadastrado()
    } catch (e) {
      // 404 aqui significa "residente não encontrado nesta instituição": o
      // backend usa o mesmo 404 para inexistente e cross-tenant, e a tela
      // preserva essa indistinção.
      setErro(mensagemDeErro(e, 'Não foi possível cadastrar o documento.'))
      if ((e as { response?: { status?: number } })?.response?.status === 403) {
        onPermissaoNegada?.()
      }
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Cadastrar documento">
      <div className="space-y-4">
        {residenteFixo ? (
          <p className="text-sm text-textMuted">
            Residente: <span className="font-medium text-textMain">{residenteFixo.nome || residenteFixo.id}</span>
          </p>
        ) : (
          <div>
            <label className="block text-sm font-medium mb-1" htmlFor="doc-residente">Residente</label>
            <select
              id="doc-residente"
              className="input"
              value={residenteId}
              onChange={e => setResidenteId(e.target.value)}
            >
              <option value="">Selecione o residente</option>
              {residentes.map(r => (
                <option key={r.id} value={r.id}>{r.nome}</option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="doc-tipo">Tipo</label>
          <input
            id="doc-tipo"
            className="input"
            maxLength={100}
            autoComplete="off"
            placeholder="RG, CPF, cartão do SUS, laudo médico…"
            value={form.tipo}
            onChange={e => setForm({ ...form, tipo: e.target.value })}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="doc-numero">Número (opcional)</label>
          <input
            id="doc-numero"
            className="input"
            maxLength={100}
            autoComplete="off"
            value={form.numero}
            onChange={e => setForm({ ...form, numero: e.target.value })}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="doc-validade">Validade (opcional)</label>
          {/* `type="date"` já entrega `YYYY-MM-DD`, que é exatamente o formato da
              coluna `Date` do backend — sem hora e sem conversão de fuso. */}
          <input
            id="doc-validade"
            className="input"
            type="date"
            value={form.validade}
            onChange={e => setForm({ ...form, validade: e.target.value })}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="doc-responsavel">Responsável pelo envio (opcional)</label>
          <input
            id="doc-responsavel"
            className="input"
            maxLength={255}
            autoComplete="off"
            value={form.responsavelEnvio}
            onChange={e => setForm({ ...form, responsavelEnvio: e.target.value })}
          />
        </div>

        <label className="flex items-center gap-3 min-h-[44px] cursor-pointer">
          <input
            id="doc-obrigatorio"
            type="checkbox"
            className="w-5 h-5 rounded"
            checked={form.obrigatorio}
            onChange={e => setForm({ ...form, obrigatorio: e.target.checked })}
          />
          <span className="text-sm font-medium">Documento obrigatório</span>
        </label>

        {erro && <div role="alert" className="text-sm text-danger">{erro}</div>}

        <button type="button" onClick={confirmar} disabled={salvando} className="btn-primary w-full disabled:opacity-60">
          {salvando ? 'Cadastrando…' : 'Cadastrar'}
        </button>
        <p className="text-xs text-textMuted text-center">
          O documento nasce pendente. O arquivo é anexado depois, pelo próprio cartão.
        </p>
      </div>
    </Modal>
  )
}
