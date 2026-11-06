import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

// Estilos de texto da Onda 5 são tamanho, não cor: sem isto, o merge descarta
// `text-apoio` ao lado de `text-foreground`.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [{ text: ['titulo-tela', 'titulo-secao', 'titulo-cartao', 'numero-destaque', 'corpo', 'corpo-forte', 'apoio', 'rotulo', 'botao', 'navegacao'] }],
    },
  },
})

/** Junta classes condicionais e resolve conflitos do Tailwind (padrão shadcn/ui). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
