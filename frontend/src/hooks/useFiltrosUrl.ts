import { useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router'

/**
 * UX-NAV-0: filtros de uma página de módulo guardados na URL.
 *
 * Recarregar, compartilhar o link ou voltar mantém o recorte. Cada troca
 * substitui a entrada do histórico (`replace`), para o voltar não percorrer
 * filtro por filtro. Parâmetros de outras chaves (ex.: `registrar`, `aba`)
 * são preservados.
 */
export function useFiltrosUrl<K extends string>(chaves: readonly K[]) {
  const [params, setParams] = useSearchParams()
  const valores = Object.fromEntries(chaves.map(k => [k, params.get(k) ?? ''])) as Record<K, string>

  const definir = useCallback(
    (chave: K, valor: string) => {
      setParams(
        atual => {
          const p = new URLSearchParams(atual)
          if (valor) p.set(chave, valor)
          else p.delete(chave)
          return p
        },
        { replace: true },
      )
    },
    [setParams],
  )

  const limpar = useCallback(() => {
    setParams(
      atual => {
        const p = new URLSearchParams(atual)
        chaves.forEach(k => p.delete(k))
        return p
      },
      { replace: true },
    )
    // `chaves` é uma lista estável declarada pela página.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setParams])

  return { valores, definir, limpar, ativos: chaves.filter(k => valores[k]) }
}

/**
 * Aba ativa guardada em `?aba=`. Valor ausente, inválido ou não permitido cai
 * na primeira aba da lista (a padrão) e o parâmetro sai da URL sem criar
 * entrada no histórico.
 */
export function useAbaUrl<T extends string>(abas: readonly T[], param = 'aba', pronto = true) {
  const [params, setParams] = useSearchParams()
  const pedida = params.get(param)
  const padrao = abas[0]
  const ativa = (pedida && (abas as readonly string[]).includes(pedida) ? pedida : padrao) as T
  // Enquanto as permissões carregam, a lista de abas ainda não é a final:
  // nada é corrigido para não apagar um `?aba=` que logo será válido.
  const invalida = pronto && pedida !== null && ativa !== pedida

  const trocar = useCallback(
    (nova: T) => {
      setParams(
        atual => {
          const p = new URLSearchParams(atual)
          // Enquanto as permissões carregam, a padrão ainda é provisória: a escolha
          // vai sempre para a URL, para não se perder quando a lista final chegar.
          if (nova === padrao && pronto) p.delete(param)
          else p.set(param, nova)
          return p
        },
        { replace: true },
      )
    },
    [setParams, padrao, param, pronto],
  )

  // Aba inválida ou não permitida: a URL é corrigida sem nova entrada no histórico.
  useEffect(() => {
    if (!invalida) return
    setParams(
      atual => {
        const p = new URLSearchParams(atual)
        p.delete(param)
        return p
      },
      { replace: true },
    )
  }, [invalida, setParams, param])

  return { ativa, trocar, invalida, pedida }
}
