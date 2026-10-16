import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import {
  PRONTUARIO_CATEGORIAS,
  PRONTUARIO_ORIGENS,
  ProntuarioCategoria,
  ProntuarioOrigem,
} from '../../services/prontuario'

export interface FiltrosValue {
  categoria?: ProntuarioCategoria
  origem?: ProntuarioOrigem
  desde?: string
  ate?: string
  incluirMovimentacoes: boolean
}

export const FILTROS_INICIAIS: FiltrosValue = { incluirMovimentacoes: true }

function resumoFiltros(v: FiltrosValue): string {
  const partes: string[] = []
  if (v.categoria) partes.push(PRONTUARIO_CATEGORIAS.find(c => c.value === v.categoria)?.label || v.categoria)
  if (v.origem) partes.push(PRONTUARIO_ORIGENS.find(o => o.value === v.origem)?.label || v.origem)
  if (v.desde || v.ate) partes.push('período')
  return partes.length ? partes.join(', ') : 'nenhum'
}

function Campos({ valor, onChange }: { valor: FiltrosValue; onChange: (v: FiltrosValue) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm block">
        <span className="block text-xs text-textMuted font-medium mb-1">Categoria</span>
        <select
          className="input"
          value={valor.categoria || ''}
          onChange={e => onChange({ ...valor, categoria: (e.target.value || undefined) as ProntuarioCategoria | undefined })}
        >
          <option value="">Todas</option>
          {PRONTUARIO_CATEGORIAS.map(c => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
      </label>
      <label className="text-sm block">
        <span className="block text-xs text-textMuted font-medium mb-1">Origem</span>
        <select
          className="input"
          value={valor.origem || ''}
          onChange={e => onChange({ ...valor, origem: (e.target.value || undefined) as ProntuarioOrigem | undefined })}
        >
          <option value="">Todas</option>
          {PRONTUARIO_ORIGENS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>
      <label className="text-sm block">
        <span className="block text-xs text-textMuted font-medium mb-1">De</span>
        <input
          type="date"
          className="input"
          value={valor.desde || ''}
          onChange={e => onChange({ ...valor, desde: e.target.value || undefined })}
        />
      </label>
      <label className="text-sm block">
        <span className="block text-xs text-textMuted font-medium mb-1">Até</span>
        <input
          type="date"
          className="input"
          value={valor.ate || ''}
          onChange={e => onChange({ ...valor, ate: e.target.value || undefined })}
        />
      </label>
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <input
          type="checkbox"
          className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary"
          checked={valor.incluirMovimentacoes}
          onChange={e => onChange({ ...valor, incluirMovimentacoes: e.target.checked })}
        />
        Incluir movimentações de ocupação e ausência
      </label>
    </div>
  )
}

export function ProntuarioFiltros({ value, onChange }: { value: FiltrosValue; onChange: (v: FiltrosValue) => void }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<FiltrosValue>(value)

  useEffect(() => {
    if (!open) setDraft(value)
  }, [value, open])

  function aplicarDraft() {
    onChange(draft)
    setOpen(false)
  }

  function limpar() {
    onChange(FILTROS_INICIAIS)
    setDraft(FILTROS_INICIAIS)
    setOpen(false)
  }

  return (
    <>
      <div className="hidden md:block card p-4">
        <Campos valor={value} onChange={onChange} />
      </div>

      <div className="md:hidden flex items-center justify-between gap-3 card p-3">
        <span className="text-sm text-textMuted truncate">Filtros: {resumoFiltros(value)}</span>
        <button type="button" onClick={() => setOpen(true)} className="btn-secondary shrink-0">Filtrar</button>
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="Filtrar prontuário">
        <div className="space-y-4">
          <Campos valor={draft} onChange={setDraft} />
          <div className="flex gap-3">
            <button type="button" onClick={limpar} className="btn-secondary flex-1">Limpar</button>
            <button type="button" onClick={aplicarDraft} className="btn-primary flex-1">Aplicar</button>
          </div>
        </div>
      </Modal>
    </>
  )
}
