import { useState } from 'react'
import { Monitor, Moon, Sun } from 'lucide-react'
import { cn } from '../../lib/utils'
import { definirTema, definirVisual, lerTema, lerVisual, type Tema } from '../../lib/aparencia'
import { Dialog, DialogContent } from '../ui/dialog'

const TEMAS: { valor: Tema; rotulo: string; Icone: typeof Sun }[] = [
  { valor: 'claro', rotulo: 'Claro', Icone: Sun },
  { valor: 'escuro', rotulo: 'Escuro', Icone: Moon },
  { valor: 'automatico', rotulo: 'Automático', Icone: Monitor },
]

/** Onda 5 (#213): tema e visual simples, guardados neste aparelho. */
export function AparenciaDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [tema, setTema] = useState<Tema>(lerTema)
  const [simples, setSimples] = useState(() => lerVisual() === 'simples')

  function escolherTema(valor: Tema) {
    setTema(valor)
    definirTema(valor)
  }

  function alternarSimples(ligado: boolean) {
    setSimples(ligado)
    definirVisual(ligado ? 'simples' : 'automatico')
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Aparência" description="Vale só para este aparelho.">
        <fieldset className="space-y-3">
          <legend className="text-rotulo text-muted-foreground">Tema</legend>
          <div role="radiogroup" aria-label="Tema" className="grid grid-cols-3 gap-2">
            {TEMAS.map(({ valor, rotulo, Icone }) => (
              <button
                key={valor}
                type="button"
                role="radio"
                aria-checked={tema === valor}
                onClick={() => escolherTema(valor)}
                className={cn(
                  'flex min-h-[64px] flex-col items-center justify-center gap-1 rounded-lg border text-apoio font-medium transition',
                  tema === valor ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-card text-foreground hover:bg-muted',
                )}
              >
                <Icone className="size-5" strokeWidth={2} aria-hidden="true" />
                {rotulo}
              </button>
            ))}
          </div>
        </fieldset>
        <label className="mt-5 flex min-h-[48px] cursor-pointer items-start gap-3 rounded-lg border border-input bg-card p-3">
          <input
            type="checkbox"
            checked={simples}
            onChange={e => alternarSimples(e.target.checked)}
            className="mt-1 size-5 accent-[hsl(var(--primary))]"
          />
          <span>
            <span className="block text-corpo-forte text-foreground">Visual simples</span>
            <span className="block text-apoio text-muted-foreground">Sem transparências. Deixa o app mais leve em celulares simples.</span>
          </span>
        </label>
      </DialogContent>
    </Dialog>
  )
}
