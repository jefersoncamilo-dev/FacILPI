import { useCallback, useState } from 'react'
import { ArrowLeft, History } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../../services/api'
import { Dialog, DialogContent } from '../ui/dialog'
import { cn } from '../../lib/utils'
import {
  ROTULO_RESULTADO_CUIDADO,
  corrigirRegistro,
  listarRegistrosRecentes,
  type ExecucaoRegistrada,
  type ResultadoCuidado,
} from '../../services/plantao'

const BOTTOM_SHEET =
  'max-sm:bottom-0 max-sm:left-0 max-sm:top-auto max-sm:max-h-[92vh] max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-b-none max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]'

const JANELA_MS = 24 * 60 * 60 * 1000
type Escolha = ResultadoCuidado | 'anular'
const ESCOLHAS: { valor: Escolha; rotulo: string }[] = [
  { valor: 'executada', rotulo: ROTULO_RESULTADO_CUIDADO.executada },
  { valor: 'recusada', rotulo: ROTULO_RESULTADO_CUIDADO.recusada },
  { valor: 'omitida', rotulo: ROTULO_RESULTADO_CUIDADO.omitida },
  { valor: 'anular', rotulo: 'Anular registro' },
]

/**
 * UX-01F — correção de registros de cuidado (decisão A). Só aparece para quem
 * tem `execucoes:corrigir` (Enfermagem, RT e administrador); o cuidador registra,
 * mas não corrige. Correção é estorno: o registro original continua visível,
 * marcado como corrigido, com motivo. "Anular" estorna sem substituto e o
 * cuidado volta para a fila. Medicação não entra aqui.
 */
export function CorrigirRegistros({
  nomes,
  onCorrigido,
}: {
  nomes: Record<string, string>
  onCorrigido: (mensagem: string) => void
}) {
  const [aberto, setAberto] = useState(false)
  const [registros, setRegistros] = useState<ExecucaoRegistrada[] | null>(null)
  const [erro, setErro] = useState('')
  const [emCorrecao, setEmCorrecao] = useState<ExecucaoRegistrada | null>(null)

  const carregar = useCallback(async () => {
    setErro('')
    try {
      setRegistros(await listarRegistrosRecentes(new Date(Date.now() - JANELA_MS).toISOString()))
    } catch (e) {
      setRegistros(null)
      setErro(mensagemDeErro(e, 'Não foi possível carregar os registros.'))
    }
  }, [])

  function abrir() {
    setAberto(true)
    setEmCorrecao(null)
    setRegistros(null)
    void carregar()
  }

  async function corrigido(mensagem: string) {
    setEmCorrecao(null)
    await carregar()
    onCorrigido(mensagem)
  }

  return (
    <>
      <button
        type="button"
        onClick={abrir}
        aria-haspopup="dialog"
        className="inline-flex min-h-[44px] items-center gap-2 text-sm font-medium text-primary hover:underline"
      >
        <History className="size-4" aria-hidden="true" /> Corrigir registros
      </button>

      <Dialog open={aberto} onOpenChange={setAberto}>
        {aberto && (
          <DialogContent
            title={emCorrecao ? 'Corrigir registro' : 'Corrigir registros'}
            description={emCorrecao ? undefined : 'Cuidados registrados nas últimas 24 horas. A correção fica no histórico; nada é apagado.'}
            focarConteudo
            className={BOTTOM_SHEET}
          >
            {emCorrecao ? (
              <FormCorrecao
                registro={emCorrecao}
                nome={nomes[emCorrecao.residente_id] || emCorrecao.residente_id}
                onVoltar={() => setEmCorrecao(null)}
                onCorrigido={corrigido}
              />
            ) : (
              <Lista registros={registros} erro={erro} nomes={nomes} onCorrigir={setEmCorrecao} onTentar={() => void carregar()} />
            )}
          </DialogContent>
        )}
      </Dialog>
    </>
  )
}

function Lista({
  registros,
  erro,
  nomes,
  onCorrigir,
  onTentar,
}: {
  registros: ExecucaoRegistrada[] | null
  erro: string
  nomes: Record<string, string>
  onCorrigir: (registro: ExecucaoRegistrada) => void
  onTentar: () => void
}) {
  if (erro) {
    return (
      <div className="space-y-3">
        <p className="text-sm font-medium text-danger" role="alert">{erro}</p>
        <button type="button" onClick={onTentar} className="btn-primary min-h-[44px]">Tentar novamente</button>
      </div>
    )
  }
  if (registros === null) return <p className="text-sm text-muted-foreground" role="status">Carregando…</p>
  if (registros.length === 0) return <p className="text-sm text-muted-foreground">Nenhum cuidado registrado nas últimas 24 horas.</p>

  return (
    <ul className="max-h-[60vh] space-y-2 overflow-y-auto">
      {registros.map(registro => {
        const nome = nomes[registro.residente_id] || registro.residente_id
        const cuidado = registro.descricao || 'Cuidado programado'
        const corrigido = Boolean(registro.estornado_em)
        return (
          <li key={registro.id} className={cn('rounded-lg border p-3', corrigido ? 'border-border bg-muted/50' : 'border-border')}>
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{nome}</div>
                <div className="truncate text-sm text-muted-foreground">{cuidado} • {formatDateTime(registro.ocorrido_em)}</div>
                <div className={cn('mt-1 text-sm font-medium', corrigido ? 'text-muted-foreground line-through' : registro.resultado === 'executada' ? 'text-primary' : 'text-alerta-forte')}>
                  {ROTULO_RESULTADO_CUIDADO[registro.resultado]}{registro.justificativa ? `: ${registro.justificativa}` : ''}
                </div>
                <div className="text-sm text-muted-foreground">
                  {registro.substitui_id ? 'Correção' : 'Registrado'}{registro.executor_nome ? ` por ${registro.executor_nome}` : ''}
                </div>
                {corrigido && (
                  <div className="mt-1 text-sm font-medium text-foreground">
                    Corrigido{registro.motivo_estorno ? `: ${registro.motivo_estorno}` : ''}
                  </div>
                )}
              </div>
              {!corrigido && (
                <button
                  type="button"
                  onClick={() => onCorrigir(registro)}
                  aria-label={`Corrigir — ${nome}, ${cuidado}, ${formatDateTime(registro.ocorrido_em)}`}
                  className="min-h-[44px] shrink-0 rounded-lg border border-border px-3 text-sm font-medium hover:bg-muted"
                >
                  Corrigir
                </button>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function FormCorrecao({
  registro,
  nome,
  onVoltar,
  onCorrigido,
}: {
  registro: ExecucaoRegistrada
  nome: string
  onVoltar: () => void
  onCorrigido: (mensagem: string) => Promise<void>
}) {
  const [escolha, setEscolha] = useState<Escolha | null>(null)
  const [justificativa, setJustificativa] = useState('')
  const [motivo, setMotivo] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')

  const exigeJustificativa = escolha === 'recusada' || escolha === 'omitida'

  async function salvar() {
    if (!escolha) return setErro('Escolha como o registro deve ficar.')
    if (exigeJustificativa && !justificativa.trim()) return setErro('Informe o motivo do resultado.')
    if (!motivo.trim()) return setErro('Informe o motivo da correção.')
    setSalvando(true)
    setErro('')
    try {
      await corrigirRegistro(registro, {
        motivo,
        novo: escolha === 'anular' ? null : { resultado: escolha, justificativa },
      })
      await onCorrigido(escolha === 'anular' ? 'Registro anulado. O cuidado voltou para a fila.' : 'Registro corrigido.')
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível salvar a correção. Tente novamente.'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-muted px-4 py-3">
        <div className="font-medium text-foreground">{registro.descricao || 'Cuidado programado'}</div>
        <div className="mt-0.5 text-sm text-muted-foreground">{nome} • {formatDateTime(registro.ocorrido_em)}</div>
        <div className="mt-1 text-sm">
          Registrado como <strong>{ROTULO_RESULTADO_CUIDADO[registro.resultado]}</strong>
          {registro.justificativa ? `: ${registro.justificativa}` : ''}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2" role="group" aria-label="Como deve ficar">
        {ESCOLHAS.map(opcao => (
          <button
            key={opcao.valor}
            type="button"
            aria-pressed={escolha === opcao.valor}
            onClick={() => { setEscolha(opcao.valor); setErro('') }}
            className={cn(
              'min-h-[48px] rounded-lg border px-2 text-sm font-medium',
              escolha === opcao.valor ? 'border-primary bg-brand-soft text-primary' : 'border-border hover:bg-muted',
            )}
          >
            {opcao.rotulo}
          </button>
        ))}
      </div>
      {escolha === 'anular' && (
        <p className="text-sm text-muted-foreground">O registro fica no histórico como anulado e o cuidado volta para a fila do plantão.</p>
      )}

      {exigeJustificativa && (
        <div className="space-y-1">
          <label htmlFor="justificativa-correcao" className="block text-sm font-medium">
            Motivo do resultado <span className="text-muted-foreground">(obrigatório)</span>
          </label>
          <input id="justificativa-correcao" className="input" value={justificativa} onChange={e => setJustificativa(e.target.value)} />
        </div>
      )}

      <div className="space-y-1">
        <label htmlFor="motivo-correcao" className="block text-sm font-medium">
          Motivo da correção <span className="text-muted-foreground">(obrigatório)</span>
        </label>
        <input
          id="motivo-correcao"
          className="input"
          placeholder="Ex.: registrado no residente errado"
          value={motivo}
          onChange={e => setMotivo(e.target.value)}
        />
      </div>

      {erro && <div className="text-sm font-medium text-danger" role="alert">{erro}</div>}

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={onVoltar}
          disabled={salvando}
          className="inline-flex min-h-[48px] items-center justify-center gap-2 rounded-lg border border-border text-sm font-medium hover:bg-muted disabled:opacity-60"
        >
          <ArrowLeft className="size-4" aria-hidden="true" /> Voltar
        </button>
        <button type="button" onClick={() => void salvar()} disabled={salvando} className="btn-primary min-h-[48px] disabled:opacity-60">
          {salvando ? 'Salvando…' : 'Salvar correção'}
        </button>
      </div>
    </div>
  )
}
