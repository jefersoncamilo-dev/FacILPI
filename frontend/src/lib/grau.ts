/**
 * UX-GRAU: grau de dependência como prioridade de atenção.
 *
 * Grau I verde, Grau II amarelo, Grau III vermelho (tokens --grau-*, contraste
 * conferido em contrasteTokens.test.ts). A cor nunca vai sozinha: o selo diz
 * "Grau II" por extenso.
 *
 * Valores de grau na tela:
 *  - 'Grau I' | 'Grau II' | 'Grau III': grau oficial ativo;
 *  - null: consultado e sem grau ativo ("Sem grau");
 *  - undefined: não consultado (sem permissão, carregando ou falha) — nunca
 *    vira cor nem posição na ordem.
 */
export const GRAUS = ['Grau I', 'Grau II', 'Grau III'] as const
export type Grau = (typeof GRAUS)[number]
export type GrauNaTela = Grau | null | undefined

export function ehGrau(valor: unknown): valor is Grau {
  return typeof valor === 'string' && (GRAUS as readonly string[]).includes(valor)
}

/** Classes do selo (fundo + texto + borda). */
export const SELO_GRAU: Record<Grau, string> = {
  'Grau I': 'border-grau-1 bg-grau-1-fundo text-grau-1-texto',
  'Grau II': 'border-grau-2-contorno bg-grau-2-fundo text-grau-2-texto',
  'Grau III': 'border-grau-3 bg-grau-3-fundo text-grau-3-texto',
}
export const SELO_SEM_GRAU = 'border-border bg-muted text-muted-foreground'

/**
 * Círculo em volta da foto. O amarelo do Grau II não contrasta com fundo
 * claro: leva contorno escuro por fora do anel (no escuro, o contorno é o
 * próprio amarelo). Conta do contorno: ring-offset 2 px + anel 4 px = 6 px;
 * com `outline-offset` menor, o contorno cairia em cima do amarelo.
 */
export const ANEL_GRAU: Record<Grau, string> = {
  'Grau I': 'ring-4 ring-grau-1',
  'Grau II': 'ring-4 ring-grau-2 outline-1 outline-offset-[6px] outline-grau-2-contorno',
  'Grau III': 'ring-4 ring-grau-3',
}
export const ANEL_SEM_GRAU = 'ring-4 ring-border'

/**
 * Posição na ordem de atenção (menor = antes). Decisão de produto: sem grau
 * definido vai para o topo (não se sabe o cuidado necessário); depois III,
 * II e I. Não consultado (undefined) não reordena: fica por último, estável.
 */
export function ordemDoGrau(grau: GrauNaTela): number {
  if (grau === undefined) return 9
  if (grau === null) return 0
  return { 'Grau III': 1, 'Grau II': 2, 'Grau I': 3 }[grau]
}

/** Comparador estável por grau; use como critério depois da urgência, quando houver. */
export function compararPorGrau(a: GrauNaTela, b: GrauNaTela): number {
  return ordemDoGrau(a) - ordemDoGrau(b)
}

/** Normaliza o que vem da API ('Grau II', null, outro texto) para o valor de tela. */
export function grauDaApi(valor: string | null | undefined): GrauNaTela {
  if (valor === undefined) return undefined
  return ehGrau(valor) ? valor : null
}
