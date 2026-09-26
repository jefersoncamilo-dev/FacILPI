import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Atalho de cadastro por link (UX-11 / #101): as ações rápidas do Início
 * levam a `?novo=1` (ou outro parâmetro), e a tela abre o formulário ao
 * carregar — só quando a pessoa pode criar (as permissões chegam depois do
 * primeiro render, então espera por elas). Ao fechar, o parâmetro sai da URL
 * para o formulário não reabrir ao recarregar ou voltar.
 */
export function useAberturaPorParametro(nome: string, permitido = true): [boolean, (aberto: boolean) => void] {
  const [params, setParams] = useSearchParams()
  const pedido = params.get(nome) === '1'
  const [aberto, setAberto] = useState(false)
  const abriuPeloLink = useRef(false)

  useEffect(() => {
    if (pedido && permitido && !abriuPeloLink.current) {
      abriuPeloLink.current = true
      setAberto(true)
    }
  }, [pedido, permitido])

  useEffect(() => {
    if (abriuPeloLink.current && !aberto && params.has(nome)) {
      const p = new URLSearchParams(params)
      p.delete(nome)
      setParams(p, { replace: true })
    }
  }, [aberto, params, setParams, nome])

  return [aberto, setAberto]
}
