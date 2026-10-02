import { useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { Dialog, DialogContent } from '../ui/dialog'
import { cn } from '../../lib/utils'
import { PLANTAO_ORIGENS } from '../../services/plantao'
import type { Filtros } from './visoes'

const BOTTOM_SHEET =
  'max-sm:bottom-0 max-sm:left-0 max-sm:top-auto max-sm:max-h-[92vh] max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-b-none'

/**
 * UX-01A.2 — filtros secundários (origem e residente) num Sheet: a barra da
 * tela fica só com o que se usa o tempo todo (visão + situação).
 */
export function FiltrosPlantao({
  filtros,
  residentes,
  onMudar,
}: {
  filtros: Filtros
  residentes: { id: string; nome: string }[]
  onMudar: (filtros: Filtros) => void
}) {
  const [aberto, setAberto] = useState(false)
  const ativos = Number(filtros.origem !== 'todas') + Number(Boolean(filtros.residenteId))
  const opcoes = [{ value: 'todas' as const, label: 'Todas' }, ...PLANTAO_ORIGENS]

  return (
    <>
      <button
        type="button"
        onClick={() => setAberto(true)}
        aria-haspopup="dialog"
        aria-expanded={aberto}
        className={cn(
          'inline-flex min-h-[44px] shrink-0 items-center gap-2 rounded-lg border px-3 text-sm font-medium',
          ativos ? 'border-primary bg-brand-soft text-primary' : 'border-border bg-card text-foreground hover:bg-muted',
        )}
      >
        <SlidersHorizontal className="size-4" aria-hidden="true" />
        Filtros{ativos ? ` (${ativos})` : ''}
      </button>

      <Dialog open={aberto} onOpenChange={setAberto}>
        {aberto && (
          <DialogContent title="Filtros do plantão" focarConteudo className={BOTTOM_SHEET}>
            <div className="space-y-5">
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Origem</legend>
                <div className="flex flex-wrap gap-2">
                  {opcoes.map(opcao => (
                    <button
                      key={opcao.value}
                      type="button"
                      aria-pressed={filtros.origem === opcao.value}
                      onClick={() => onMudar({ ...filtros, origem: opcao.value })}
                      className={cn(
                        'min-h-[44px] rounded-full border px-4 text-sm',
                        filtros.origem === opcao.value ? 'border-primary bg-brand-soft font-medium text-primary' : 'border-border hover:bg-muted',
                      )}
                    >
                      {opcao.label}
                    </button>
                  ))}
                </div>
              </fieldset>

              <div className="space-y-2">
                <label htmlFor="filtro-residente" className="block text-sm font-medium">Residente</label>
                <select
                  id="filtro-residente"
                  className="input min-h-[48px]"
                  value={filtros.residenteId ?? ''}
                  onChange={e => onMudar({ ...filtros, residenteId: e.target.value || null })}
                >
                  <option value="">Todos os residentes</option>
                  {residentes.map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
                </select>
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => onMudar({ ...filtros, origem: 'todas', residenteId: null })}
                  className="btn-secondary min-h-[48px] flex-1"
                >
                  Limpar
                </button>
                <button type="button" onClick={() => setAberto(false)} className="btn-primary min-h-[48px] flex-1">
                  Ver resultados
                </button>
              </div>
            </div>
          </DialogContent>
        )}
      </Dialog>
    </>
  )
}
