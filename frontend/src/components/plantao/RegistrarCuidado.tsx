import { useState } from 'react'
import { Ban, CircleCheck, CircleX, MessageSquarePlus } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../../services/api'
import { Dialog, DialogContent } from '../ui/dialog'
import { cn } from '../../lib/utils'
import {
  ROTULO_RESULTADO_CUIDADO,
  registrarCuidado,
  rotuloDoItem,
  type PlantaoItem,
  type ResultadoCuidado,
} from '../../services/plantao'

const FALHA = 'Não foi possível salvar. Tentar novamente.'

// Atalhos de texto para o motivo; o campo continua livre e editável.
const SUGESTOES: Record<Exclude<ResultadoCuidado, 'executada'>, string[]> = {
  recusada: ['Residente recusou'],
  omitida: ['Residente ausente', 'Residente dormindo', 'Material indisponível'],
}

const OPCOES: { valor: ResultadoCuidado; Icone: typeof CircleCheck; classe: string }[] = [
  { valor: 'executada', Icone: CircleCheck, classe: 'border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-700' },
  { valor: 'recusada', Icone: CircleX, classe: 'border-orange-300 bg-card text-orange-900 hover:bg-orange-50' },
  { valor: 'omitida', Icone: Ban, classe: 'border-slate-300 bg-card text-slate-800 hover:bg-muted' },
]

/**
 * UX-01A.1 — Registrar rápido de um cuidado do plantão.
 *
 * "Realizado" salva com um toque. "Recusado"/"Não realizado" revelam o motivo
 * (obrigatório, como no backend). Observação fica recolhida e nenhum campo de
 * texto recebe foco sozinho — o teclado só abre se a pessoa pedir. Em falha,
 * o diálogo continua aberto com o que foi informado.
 */
export function RegistrarCuidado({
  item,
  nomeResidente,
  onFechar,
  onSalvo,
  onFalha,
}: {
  item: PlantaoItem | null
  nomeResidente?: string
  onFechar: () => void
  onSalvo: (item: PlantaoItem) => void
  onFalha?: () => void
}) {
  return (
    <Dialog open={item !== null} onOpenChange={aberto => { if (!aberto) onFechar() }}>
      {item && (
        <DialogContent
          title="Registrar cuidado"
          focarConteudo
          className="max-sm:bottom-0 max-sm:left-0 max-sm:top-auto max-sm:max-h-[92vh] max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-b-none max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]"
        >
          <Formulario key={item.registro_id} item={item} nomeResidente={nomeResidente} onSalvo={onSalvo} onFalha={onFalha} />
        </DialogContent>
      )}
    </Dialog>
  )
}

function Formulario({
  item,
  nomeResidente,
  onSalvo,
  onFalha,
}: {
  item: PlantaoItem
  nomeResidente?: string
  onSalvo: (item: PlantaoItem) => void
  onFalha?: () => void
}) {
  const [resultado, setResultado] = useState<ResultadoCuidado | null>(null)
  const [motivo, setMotivo] = useState('')
  const [observacao, setObservacao] = useState('')
  const [comObservacao, setComObservacao] = useState(false)
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')

  async function salvar(valor: ResultadoCuidado) {
    if (valor !== 'executada' && !motivo.trim()) {
      setErro('Informe o motivo.')
      return
    }
    setSalvando(true)
    setErro('')
    try {
      await registrarCuidado(item, { resultado: valor, justificativa: motivo, observacao })
      onSalvo(item)
    } catch (e) {
      // Sem resposta (rede/servidor fora) vale a mensagem operacional; com resposta,
      // o motivo do backend (ex.: outro plantonista já registrou) é mais útil.
      const comResposta = Boolean((e as { response?: unknown })?.response)
      setErro(comResposta ? mensagemDeErro(e, FALHA) : FALHA)
      onFalha?.()
    } finally {
      setSalvando(false)
    }
  }

  function escolher(valor: ResultadoCuidado) {
    setErro('')
    if (valor === 'executada') {
      void salvar(valor)
      return
    }
    setResultado(valor)
  }

  const exigeMotivo = resultado !== null && resultado !== 'executada'

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-muted px-4 py-3">
        <div className="font-medium text-foreground">{rotuloDoItem(item)}</div>
        <div className="mt-0.5 text-sm text-muted-foreground">
          {nomeResidente || item.residente_id}
          {item.previsto_em ? ` • ${formatDateTime(item.previsto_em)}` : ''}
        </div>
      </div>

      <div className="grid gap-2" role="group" aria-label="Resultado">
        {OPCOES.map(({ valor, Icone, classe }) => (
          <button
            key={valor}
            type="button"
            disabled={salvando}
            aria-pressed={valor === 'executada' ? undefined : resultado === valor}
            onClick={() => escolher(valor)}
            className={cn(
              'flex min-h-[56px] items-center gap-3 rounded-xl border-2 px-4 text-base font-semibold transition-colors disabled:opacity-60',
              classe,
              resultado === valor && 'ring-2 ring-primary ring-offset-2',
            )}
          >
            <Icone className="size-6 shrink-0" aria-hidden="true" />
            {valor === 'executada' && salvando ? 'Salvando…' : ROTULO_RESULTADO_CUIDADO[valor]}
          </button>
        ))}
      </div>

      {exigeMotivo && (
        <div className="space-y-2">
          <label htmlFor="motivo-cuidado" className="block text-sm font-medium">
            Motivo <span className="text-muted-foreground">(obrigatório)</span>
          </label>
          <div className="flex flex-wrap gap-2">
            {SUGESTOES[resultado].map(sugestao => (
              <button
                key={sugestao}
                type="button"
                onClick={() => { setMotivo(sugestao); setErro('') }}
                className={cn(
                  'min-h-[44px] rounded-full border px-4 text-sm',
                  motivo === sugestao ? 'border-primary bg-brand-soft text-primary' : 'border-border text-foreground hover:bg-muted',
                )}
              >
                {sugestao}
              </button>
            ))}
          </div>
          <input
            id="motivo-cuidado"
            className="input"
            placeholder="Ou descreva o motivo"
            value={motivo}
            onChange={e => setMotivo(e.target.value)}
          />
        </div>
      )}

      {comObservacao ? (
        <div className="space-y-1">
          <label htmlFor="observacao-cuidado" className="block text-sm font-medium">
            Observação <span className="text-muted-foreground">(opcional)</span>
          </label>
          <textarea
            id="observacao-cuidado"
            className="input min-h-[80px]"
            value={observacao}
            onChange={e => setObservacao(e.target.value)}
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setComObservacao(true)}
          className="inline-flex min-h-[44px] items-center gap-2 text-sm font-medium text-primary hover:underline"
        >
          <MessageSquarePlus className="size-4" aria-hidden="true" /> Adicionar observação
        </button>
      )}

      {erro && <div className="text-sm font-medium text-danger" role="alert">{erro}</div>}

      {exigeMotivo && (
        <button
          type="button"
          onClick={() => void salvar(resultado)}
          disabled={salvando}
          className="btn-primary min-h-[48px] w-full disabled:opacity-60"
        >
          {salvando ? 'Salvando…' : `Salvar como ${ROTULO_RESULTADO_CUIDADO[resultado].toLowerCase()}`}
        </button>
      )}
    </div>
  )
}
