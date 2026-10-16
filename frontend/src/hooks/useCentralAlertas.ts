import { useSyncExternalStore } from 'react'
import { mensagemDeErro } from '../services/api'
import { listarAlertas, type CentralAlertas } from '../services/alertas'
import { CONTEXT_CHANGED_EVENT, TOKEN_KEY } from '../types/context'

/**
 * Uma única leitura de GET /central-alertas/ para sino, Central e navegação
 * inferior (#117): todos mostram o MESMO retrato, na ordem do backend — sino e
 * Central não discordam.
 *
 * Política de atualização (#107): recarrega ao navegar, no máximo uma vez por
 * minuto; a Central força a recarga ao abrir e no "Atualizar". Sem WebSocket.
 *
 * O retrato é da sessão que o buscou: troca de contexto, logout ou outro
 * usuário no mesmo aparelho descartam o retrato (tablet compartilhado não
 * pode mostrar alertas de outra pessoa ou de outra ILPI).
 */
export type EstadoCentral =
  | { status: 'vazio' }
  | { status: 'carregando'; dados: CentralAlertas | null }
  | { status: 'ok'; dados: CentralAlertas }
  | { status: 'proibido' }
  | { status: 'erro'; mensagem: string }

export const INTERVALO_MINIMO = 60_000

const VAZIO: EstadoCentral = { status: 'vazio' }
let estado: EstadoCentral = VAZIO
let dono: string | null = null
let ultima = 0
let geracao = 0
let emVoo: Promise<void> | null = null
const ouvintes = new Set<() => void>()

function sessaoAtual(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

function emitir(novo: EstadoCentral) {
  estado = novo
  ouvintes.forEach(f => f())
}

/** Descarta o retrato (troca de contexto, logout, testes). */
export function limparCentralAlertas() {
  geracao += 1
  dono = null
  ultima = 0
  emVoo = null
  emitir(VAZIO)
}

if (typeof window !== 'undefined') window.addEventListener(CONTEXT_CHANGED_EVENT, limparCentralAlertas)

export function recarregarCentralAlertas({ forcar = false }: { forcar?: boolean } = {}): Promise<void> {
  const sessao = sessaoAtual()
  if (sessao !== dono) limparCentralAlertas()
  if (emVoo) return emVoo
  const agora = Date.now()
  if (!forcar && ultima && agora - ultima < INTERVALO_MINIMO) return Promise.resolve()
  ultima = agora
  dono = sessao
  const minha = ++geracao
  emitir({ status: 'carregando', dados: estado.status === 'ok' || estado.status === 'carregando' ? estado.dados : null })
  emVoo = listarAlertas()
    .then(dados => { if (minha === geracao) emitir({ status: 'ok', dados }) })
    .catch((e: any) => {
      if (minha !== geracao) return
      if (e?.response?.status === 403) emitir({ status: 'proibido' })
      else emitir({ status: 'erro', mensagem: mensagemDeErro(e, 'Não foi possível carregar os alertas.') })
    })
    .finally(() => { if (minha === geracao) emVoo = null })
  return emVoo
}

function assinar(f: () => void) {
  ouvintes.add(f)
  return () => { ouvintes.delete(f) }
}

function retrato(): EstadoCentral {
  // Retrato de outra sessão nunca aparece, nem por um quadro.
  return dono === null || dono === sessaoAtual() ? estado : VAZIO
}

export function useCentralAlertas(): EstadoCentral {
  return useSyncExternalStore(assinar, retrato, retrato)
}
