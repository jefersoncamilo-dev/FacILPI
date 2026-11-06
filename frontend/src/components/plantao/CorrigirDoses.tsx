import { useCallback, useState } from 'react'
import { ArrowLeft, Pill } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../../services/api'
import { Dialog, DialogContent } from '../ui/dialog'
import { cn } from '../../lib/utils'
import {
  ROTULO_RESULTADO_DOSE,
  corrigirDose,
  listarDosesRecentes,
  type AdministracaoRegistrada,
  type ResultadoDose,
} from '../../services/plantao'

const BOTTOM_SHEET =
  'max-sm:bottom-0 max-sm:left-0 max-sm:top-auto max-sm:max-h-[92vh] max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-b-none max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]'

const JANELA_MS = 24 * 60 * 60 * 1000
type Escolha = ResultadoDose | 'anular'
const ESCOLHAS: { valor: Escolha; rotulo: string }[] = [
  { valor: 'administrada', rotulo: ROTULO_RESULTADO_DOSE.administrada },
  { valor: 'recusada', rotulo: ROTULO_RESULTADO_DOSE.recusada },
  { valor: 'omitida', rotulo: ROTULO_RESULTADO_DOSE.omitida },
  { valor: 'anular', rotulo: 'Anular registro' },
]

/**
 * #11 (D2 = sim) — estorno de administração de dose. Mesmo modelo da UX-01F:
 * só aparece para quem tem `administracoes:corrigir` (Enfermagem e RT); motivo
 * obrigatório, substituto opcional, nada apagado e o original fica visível como
 * corrigido. "Anular" estorna sem substituto e a dose volta a ficar pendente.
 */
export function CorrigirDoses({
  nomes,
  onCorrigido,
}: {
  nomes: Record<string, string>
  onCorrigido: (mensagem: string) => void
}) {
  const [aberto, setAberto] = useState(false)
  const [registros, setRegistros] = useState<AdministracaoRegistrada[] | null>(null)
  const [erro, setErro] = useState('')
  const [emCorrecao, setEmCorrecao] = useState<AdministracaoRegistrada | null>(null)

  const carregar = useCallback(async () => {
    setErro('')
    try {
      setRegistros(await listarDosesRecentes(new Date(Date.now() - JANELA_MS).toISOString()))
    } catch (e) {
      setRegistros(null)
      setErro(mensagemDeErro(e, 'Não foi possível carregar as doses.'))
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
        <Pill className="size-4" aria-hidden="true" /> Corrigir doses
      </button>

      <Dialog open={aberto} onOpenChange={setAberto}>
        {aberto && (
          <DialogContent
            title={emCorrecao ? 'Corrigir dose' : 'Corrigir doses'}
            description={emCorrecao ? undefined : 'Doses registradas nas últimas 24 horas. A correção fica no histórico; nada é apagado.'}
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
  registros: AdministracaoRegistrada[] | null
  erro: string
  nomes: Record<string, string>
  onCorrigir: (registro: AdministracaoRegistrada) => void
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
  if (registros.length === 0) return <p className="text-sm text-muted-foreground">Nenhuma dose registrada nas últimas 24 horas.</p>

  return (
    <ul className="max-h-[60vh] space-y-2 overflow-y-auto">
      {registros.map(registro => {
        const nome = nomes[registro.residente_id] || registro.residente_id
        const remedio = registro.descricao || 'Medicamento prescrito'
        const corrigido = Boolean(registro.estornado_em)
        return (
          <li key={registro.id} className={cn('rounded-lg border p-3', corrigido ? 'border-border bg-muted/50' : 'border-border')}>
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{nome}</div>
                <div className="truncate text-sm text-muted-foreground">{remedio} • {formatDateTime(registro.ocorrido_em)}</div>
                <div className={cn('mt-1 text-sm font-medium', corrigido ? 'text-muted-foreground line-through' : registro.resultado === 'administrada' ? 'text-primary' : 'text-alerta-forte')}>
                  {ROTULO_RESULTADO_DOSE[registro.resultado]}{registro.justificativa ? `: ${registro.justificativa}` : ''}
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
                  aria-label={`Corrigir — ${nome}, ${remedio}, ${formatDateTime(registro.ocorrido_em)}`}
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
  registro: AdministracaoRegistrada
  nome: string
  onVoltar: () => void
  onCorrigido: (mensagem: string) => Promise<void>
}) {
  const [escolha, setEscolha] = useState<Escolha | null>(null)
  const [justificativa, setJustificativa] = useState('')
  const [quantidade, setQuantidade] = useState(registro.quantidade_realizada != null ? String(Number(registro.quantidade_realizada)) : '')
  const [motivo, setMotivo] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')

  const exigeJustificativa = escolha === 'recusada' || escolha === 'omitida'

  async function salvar() {
    if (!escolha) return setErro('Escolha como o registro deve ficar.')
    const qtd = Number(quantidade.replace(',', '.'))
    if (escolha === 'administrada' && !(qtd > 0)) return setErro('Informe a quantidade administrada.')
    if (exigeJustificativa && !justificativa.trim()) return setErro('Informe o motivo do resultado.')
    if (!motivo.trim()) return setErro('Informe o motivo da correção.')
    setSalvando(true)
    setErro('')
    try {
      await corrigirDose(registro, {
        motivo,
        novo: escolha === 'anular' ? null
          : escolha === 'administrada' ? { resultado: escolha, quantidade_realizada: qtd }
          : { resultado: escolha, justificativa },
      })
      await onCorrigido(escolha === 'anular' ? 'Registro anulado. A dose voltou a ficar pendente.' : 'Dose corrigida.')
    } catch (e) {
      setErro(mensagemDeErro(e, 'Não foi possível salvar a correção. Tente novamente.'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-muted px-4 py-3">
        <div className="font-medium text-foreground">{registro.descricao || 'Medicamento prescrito'}</div>
        <div className="mt-0.5 text-sm text-muted-foreground">{nome} • {formatDateTime(registro.ocorrido_em)}</div>
        <div className="mt-1 text-sm">
          Registrado como <strong>{ROTULO_RESULTADO_DOSE[registro.resultado]}</strong>
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
        <p className="text-sm text-muted-foreground">O registro fica no histórico como anulado e a dose volta a ficar pendente.</p>
      )}

      {escolha === 'administrada' && (
        <div className="space-y-1">
          <label htmlFor="quantidade-correcao" className="block text-sm font-medium">
            Quantidade administrada <span className="text-muted-foreground">(obrigatório)</span>
          </label>
          <input id="quantidade-correcao" className="input" inputMode="decimal" value={quantidade} onChange={e => setQuantidade(e.target.value)} />
        </div>
      )}

      {exigeJustificativa && (
        <div className="space-y-1">
          <label htmlFor="justificativa-dose" className="block text-sm font-medium">
            Motivo do resultado <span className="text-muted-foreground">(obrigatório)</span>
          </label>
          <input id="justificativa-dose" className="input" value={justificativa} onChange={e => setJustificativa(e.target.value)} />
        </div>
      )}

      <div className="space-y-1">
        <label htmlFor="motivo-correcao-dose" className="block text-sm font-medium">
          Motivo da correção <span className="text-muted-foreground">(obrigatório)</span>
        </label>
        <input
          id="motivo-correcao-dose"
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
