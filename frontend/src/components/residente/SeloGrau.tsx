import { cn } from '../../lib/utils'
import { SELO_GRAU, SELO_SEM_GRAU, ehGrau, type GrauNaTela } from '../../lib/grau'

/**
 * Grau de dependência = prioridade de atenção: I verde, II amarelo, III
 * vermelho (UX-GRAU). O texto ("Grau II") vai sempre junto, para não depender
 * só da cor. `semGrau` mostra "Sem grau" quando o grau foi consultado e não
 * existe (null); sem consulta (undefined) nada aparece.
 */
export function SeloGrau({
  classificacao,
  semGrau = false,
  tamanho = 'pequeno',
  className,
}: {
  classificacao?: GrauNaTela | string
  semGrau?: boolean
  tamanho?: 'pequeno' | 'medio'
  className?: string
}) {
  const medida = tamanho === 'medio' ? 'min-h-[28px] px-2.5 text-xs' : 'px-1.5 text-[11px] leading-4'
  if (ehGrau(classificacao)) {
    return (
      <span
        className={cn('inline-flex shrink-0 items-center rounded-full border font-semibold', medida, SELO_GRAU[classificacao], className)}
        aria-label={`Grau de dependência ${classificacao.replace('Grau ', '')}`}
      >
        {classificacao}
      </span>
    )
  }
  if (semGrau && classificacao === null) {
    return (
      <span className={cn('inline-flex shrink-0 items-center rounded-full border font-semibold', medida, SELO_SEM_GRAU, className)}>
        Sem grau
      </span>
    )
  }
  return null
}
