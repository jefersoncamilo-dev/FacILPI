import { useEffect, useState } from 'react'

/** Duração total da entrada (sequência dos cartões + barras), em ms. */
export const DURACAO_ENTRADA = 1400

/**
 * UX-DASH-1: `true` só durante a primeira entrada, a partir do momento em que
 * os dados ficam prontos. Depois vira `false` para sempre: as classes de
 * animação saem e trocar filtro/período não repete o movimento.
 * `prefers-reduced-motion` é respeitado no CSS (as classes não animam).
 */
export function useAnimarUmaVez(pronto: boolean): boolean {
  const [fase, setFase] = useState<'antes' | 'animando' | 'depois'>('antes')
  if (pronto && fase === 'antes') setFase('animando')
  useEffect(() => {
    if (fase !== 'animando') return
    const t = setTimeout(() => setFase('depois'), DURACAO_ENTRADA)
    return () => clearTimeout(t)
  }, [fase])
  return fase === 'animando'
}
