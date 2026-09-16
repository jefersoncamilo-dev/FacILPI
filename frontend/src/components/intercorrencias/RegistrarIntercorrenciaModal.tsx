import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import { mensagemDeErro } from '../../services/api'
import {
  GRAVIDADES,
  formularioVazio,
  montarPayload,
  paraInputLocal,
  registrarIntercorrencia,
  type FormularioIntercorrencia,
  type Gravidade,
} from '../../services/intercorrencias'

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
   * não é editável: não se troca o vínculo dentro do prontuário de outro.
   */
  residenteFixo?: ResidenteOpcao | null
  /** Opções usadas apenas quando não há residente fixo (rota própria). */
  residentes?: ResidenteOpcao[]
  /** Chamado quando o backend recusa por permissão (403). */
  onPermissaoNegada?: () => void
}

export function RegistrarIntercorrenciaModal({
  open,
  onClose,
  onRegistrado,
  residenteFixo = null,
  residentes = [],
  onPermissaoNegada,
}: Props) {
  const [form, setForm] = useState<FormularioIntercorrencia>(() => formularioVazio())
  const [residenteId, setResidenteId] = useState('')
  const [maximo, setMaximo] = useState(() => paraInputLocal(new Date()))
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)

  // Reabrir sempre começa limpo e com o relógio atualizado: valores de um
  // registro anterior reaproveitados por engano viram histórico clínico falso.
  useEffect(() => {
    if (!open) return
    const agora = new Date()
    setForm(formularioVazio(agora))
    setMaximo(paraInputLocal(agora))
    setResidenteId(residenteFixo?.id ?? '')
    setErro('')
  }, [open, residenteFixo?.id])

  async function confirmar() {
    const { erro: invalido, payload } = montarPayload(residenteId, form)
    if (invalido || !payload) {
      setErro(invalido ?? 'Não foi possível montar o registro.')
      return
    }
    setSalvando(true)
    setErro('')
    try {
      await registrarIntercorrencia(payload)
      onRegistrado()
    } catch (e) {
      // 404 aqui significa "residente não encontrado nesta instituição": o
      // backend usa o mesmo 404 para inexistente e cross-tenant, e a tela
      // preserva essa indistinção.
      setErro(mensagemDeErro(e, 'Não foi possível registrar a intercorrência.'))
      if ((e as { response?: { status?: number } })?.response?.status === 403) {
        onPermissaoNegada?.()
      }
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Registrar intercorrência">
      <div className="space-y-4">
        {residenteFixo ? (
          <p className="text-sm text-textMuted">
            Residente: <span className="font-medium text-textMain">{residenteFixo.nome || residenteFixo.id}</span>
          </p>
        ) : (
          <div>
            <label className="block text-sm font-medium mb-1" htmlFor="int-residente">Residente</label>
            <select
              id="int-residente"
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
          <label className="block text-sm font-medium mb-1" htmlFor="int-tipo">Tipo</label>
          <input
            id="int-tipo"
            className="input"
            maxLength={100}
            autoComplete="off"
            placeholder="Queda, engasgo, alteração de comportamento…"
            value={form.tipo}
            onChange={e => setForm({ ...form, tipo: e.target.value })}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="int-gravidade">Gravidade</label>
          <select
            id="int-gravidade"
            className="input"
            value={form.gravidade}
            onChange={e => setForm({ ...form, gravidade: e.target.value as Gravidade })}
          >
            {GRAVIDADES.map(g => (
              <option key={g.value} value={g.value}>{g.label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="int-ocorrido">Data e hora da ocorrência</label>
          <input
            id="int-ocorrido"
            className="input"
            type="datetime-local"
            // O backend recusa futuro; `max` evita que o usuário sequer o escolha
            // nos navegadores que honram o atributo.
            max={maximo}
            value={form.ocorridoEm}
            onChange={e => setForm({ ...form, ocorridoEm: e.target.value })}
          />
          <p className="text-xs text-textMuted mt-1">
            Já preenchida com o momento atual. Ajuste se a intercorrência aconteceu antes.
          </p>
        </div>

        {/* SBAR e providência ficam recolhidos: são cinco campos longos e o
            registro precisa ser rápido em 360px. Continuam no DOM e acessíveis. */}
        <details className="rounded-xl border border-slate-200">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium min-h-[44px] flex items-center">
            Detalhamento SBAR e providência (opcional)
          </summary>
          <div className="space-y-3 px-4 pb-4">
            <div>
              <label className="block text-sm font-medium mb-1" htmlFor="int-sbar-s">Situação</label>
              <textarea id="int-sbar-s" className="input" rows={2}
                value={form.sbarSituacao} onChange={e => setForm({ ...form, sbarSituacao: e.target.value })} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" htmlFor="int-sbar-b">Contexto</label>
              <textarea id="int-sbar-b" className="input" rows={2}
                value={form.sbarContexto} onChange={e => setForm({ ...form, sbarContexto: e.target.value })} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" htmlFor="int-sbar-a">Avaliação</label>
              <textarea id="int-sbar-a" className="input" rows={2}
                value={form.sbarAvaliacao} onChange={e => setForm({ ...form, sbarAvaliacao: e.target.value })} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" htmlFor="int-sbar-r">Recomendação</label>
              <textarea id="int-sbar-r" className="input" rows={2}
                value={form.sbarRecomendacao} onChange={e => setForm({ ...form, sbarRecomendacao: e.target.value })} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" htmlFor="int-providencia">Providência</label>
              <textarea id="int-providencia" className="input" rows={2}
                value={form.providencia} onChange={e => setForm({ ...form, providencia: e.target.value })} />
            </div>
          </div>
        </details>

        {erro && <div role="alert" className="text-sm text-danger">{erro}</div>}

        <button type="button" onClick={confirmar} disabled={salvando} className="btn-primary w-full disabled:opacity-60">
          {salvando ? 'Registrando…' : 'Registrar'}
        </button>
        <p className="text-xs text-textMuted text-center">
          A intercorrência nasce aberta e aparece no Meu Plantão até ser encerrada.
        </p>
      </div>
    </Modal>
  )
}
