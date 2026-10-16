import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { contextApi } from '../services/context'
import { CONTEXT_CHANGED_EVENT } from '../types/context'

/**
 * UX-01 (#83): permissões efetivas do contexto, para a interface não oferecer
 * o que o backend recusaria. NÃO é autorização — cada rota do backend decide.
 *
 * - `carregando`: ainda sem resposta; a navegação mostra esqueleto.
 * - `ok`: lista do backend; itens com permissão fora dela ficam ocultos.
 * - `indisponivel`: endpoint ausente ou resposta inesperada; mostra-se tudo o
 *   que está pronto e o backend segue recusando o que não couber (403).
 */
type Estado =
  | { status: 'carregando' }
  | { status: 'ok'; chaves: ReadonlySet<string> }
  | { status: 'indisponivel' }

type PermissoesValue = {
  /** `sem_provider`: tela montada fora do shell (ex.: testes isolados). */
  status: Estado['status'] | 'sem_provider'
  /** Sem chave, sempre pode. Com chave, depende do estado (ver acima). */
  pode: (chave?: string) => boolean
}

const PermissoesContext = createContext<PermissoesValue | null>(null)

export function PermissoesProvider({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<Estado>({ status: 'carregando' })

  const carregar = useCallback(async () => {
    try {
      const { data } = await contextApi.permissoesDaSessao()
      if (data && Array.isArray(data.permissoes)) {
        setEstado({ status: 'ok', chaves: new Set(data.permissoes) })
      } else {
        setEstado({ status: 'indisponivel' })
      }
    } catch {
      setEstado({ status: 'indisponivel' })
    }
  }, [])

  useEffect(() => {
    carregar()
    const aoTrocarContexto = () => {
      setEstado({ status: 'carregando' })
      carregar()
    }
    window.addEventListener(CONTEXT_CHANGED_EVENT, aoTrocarContexto)
    return () => window.removeEventListener(CONTEXT_CHANGED_EVENT, aoTrocarContexto)
  }, [carregar])

  const pode = useCallback(
    (chave?: string) => {
      if (!chave) return true
      if (estado.status === 'ok') return estado.chaves.has(chave)
      return estado.status === 'indisponivel'
    },
    [estado],
  )

  return <PermissoesContext.Provider value={{ status: estado.status, pode }}>{children}</PermissoesContext.Provider>
}

export function usePermissoes(): PermissoesValue {
  const value = useContext(PermissoesContext)
  if (!value) throw new Error('usePermissoes precisa estar dentro de PermissoesProvider')
  return value
}

const SEM_PROVIDER: PermissoesValue = { status: 'sem_provider', pode: () => true }

/**
 * Para telas que também são montadas fora do shell (testes, telas isoladas):
 * sem provider, `pode` libera tudo (o backend decide cada rota, igual ao
 * fallback do shell) e `status` é `sem_provider`, para quem só enriquece a
 * tela (contexto do residente, leitos) não consultar fontes extras.
 */
export function usePermissoesOuPadrao(): PermissoesValue {
  return useContext(PermissoesContext) ?? SEM_PROVIDER
}
