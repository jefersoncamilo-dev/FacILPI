import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import { mensagemDeErro } from '../../services/api'
import {
  FORMULARIO_SINAIS_VAZIO,
  SINAIS_VITAIS_CAMPOS,
  avisoPressao,
  montarPayload,
  registrarSinalVital,
  type CampoSinal,
  type FormularioSinais,
} from '../../services/sinaisVitais'

export interface ResidenteOpcao {
  id: string
  nome: string
}

interface Props {
  open: boolean
  onClose: () => void
  onRegistrado: () => void
  /**
   * Residente já definido pelo contexto (Prontuário). Quando presente, o campo
   * não é editável: o vínculo não deve ser trocado dentro do prontuário de outro.
   */
  residenteFixo?: ResidenteOpcao | null
  /** Opções usadas apenas quando não há residente fixo (rota própria). */
  residentes?: ResidenteOpcao[]
  /** Chamado quando o backend recusa por permissão (403). */
  onPermissaoNegada?: () => void
}

export function RegistrarSinalVitalModal({
  open,
  onClose,
  onRegistrado,
  residenteFixo = null,
  residentes = [],
  onPermissaoNegada,
}: Props) {
  const [form, setForm] = useState<FormularioSinais>(FORMULARIO_SINAIS_VAZIO)
  const [residenteId, setResidenteId] = useState('')
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)

  // Reabrir sempre começa limpo: valores de uma aferição anterior reaproveitados
  // por engano viram registro clínico falso.
  useEffect(() => {
    if (!open) return
    setForm(FORMULARIO_SINAIS_VAZIO)
    setResidenteId(residenteFixo?.id ?? '')
    setErro('')
  }, [open, residenteFixo?.id])

  function alterarSinal(campo: CampoSinal, valor: string) {
    setForm(atual => ({ ...atual, valores: { ...atual.valores, [campo]: valor } }))
  }

  async function confirmar() {
    const { erro: invalido, payload } = montarPayload(residenteId, form)
    if (invalido || !payload) {
      setErro(invalido ?? 'Não foi possível montar o registro.')
      return
    }
    setSalvando(true)
    setErro('')
    try {
      await registrarSinalVital(payload)
      onRegistrado()
    } catch (e) {
      // 404 aqui significa "residente não encontrado nesta instituição" — o
      // backend usa o mesmo 404 para inexistente e cross-tenant, e a tela
      // preserva essa indistinção.
      setErro(mensagemDeErro(e, 'Não foi possível registrar os sinais vitais.'))
      if ((e as { response?: { status?: number } })?.response?.status === 403) {
        onPermissaoNegada?.()
      }
    } finally {
      setSalvando(false)
    }
  }

  const aviso = avisoPressao(form)

  return (
    <Modal open={open} onClose={onClose} title="Registrar sinais vitais">
      <div className="space-y-4">
        {residenteFixo ? (
          <p className="text-sm text-textMuted">
            Residente: <span className="font-medium text-textMain">{residenteFixo.nome || residenteFixo.id}</span>
          </p>
        ) : (
          <div>
            <label className="block text-sm font-medium mb-1" htmlFor="sv-residente">Residente</label>
            <select
              id="sv-residente"
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

        {/* Uma coluna em 360; duas a partir de 640, o que cobre 768 e 1366. */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {SINAIS_VITAIS_CAMPOS.map(def => (
            <div key={def.campo}>
              <label className="block text-sm font-medium mb-1" htmlFor={`sv-${def.campo}`}>
                {def.label} <span className="text-textMuted font-normal">({def.unidade})</span>
              </label>
              <input
                id={`sv-${def.campo}`}
                className="input"
                type="text"
                // Teclado numérico no celular sem o descarte de vírgula do type="number".
                inputMode={def.inteiro ? 'numeric' : 'decimal'}
                autoComplete="off"
                value={form.valores[def.campo]}
                onChange={e => alterarSinal(def.campo, e.target.value)}
              />
            </div>
          ))}
        </div>

        <p className="text-xs text-textMuted">Preencha ao menos um sinal. Os demais podem ficar em branco.</p>

        {aviso && (
          <div role="status" className="text-sm text-warning bg-orange-50 border border-orange-200 rounded-xl p-3">
            {aviso}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="sv-data">Data e hora da aferição</label>
          <input
            id="sv-data"
            className="input"
            type="datetime-local"
            value={form.data}
            onChange={e => setForm({ ...form, data: e.target.value })}
          />
          <p className="text-xs text-textMuted mt-1">Em branco, registra o momento atual.</p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="sv-observacao">Observação</label>
          <input
            id="sv-observacao"
            className="input"
            value={form.observacao}
            onChange={e => setForm({ ...form, observacao: e.target.value })}
            placeholder="Opcional"
          />
        </div>

        {erro && <div role="alert" className="text-sm text-danger">{erro}</div>}

        <button type="button" onClick={confirmar} disabled={salvando} className="btn-primary w-full disabled:opacity-60">
          {salvando ? 'Registrando…' : 'Registrar'}
        </button>
        <p className="text-xs text-textMuted text-center">
          Correção de um registro é uma nova aferição — o histórico não é alterado.
        </p>
      </div>
    </Modal>
  )
}
