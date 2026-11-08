import { cn } from '../../lib/utils'
import { ANEL_GRAU, ANEL_SEM_GRAU, ehGrau, type GrauNaTela } from '../../lib/grau'

/** "Maria da Silva Souza" → "MS". Um nome só → duas primeiras letras. */
export function iniciais(nome: string): string {
  const partes = nome.trim().split(/\s+/).filter(p => p.length > 2 || /^[A-ZÀ-Ý]/.test(p))
  if (partes.length === 0) return '?'
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase()
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase()
}

// Só imagem embutida: o campo `foto` é texto livre e não deve virar requisição
// para qualquer endereço. A CSP (img-src 'self' data:) bloquearia HTTPS (N7).
function fotoSegura(foto?: string | null): string | null {
  if (!foto) return null
  return /^data:image\/(png|jpe?g|webp|gif);base64,/i.test(foto) ? foto : null
}

/**
 * Foto do residente ou, sem foto, as iniciais. Decorativo: o nome está ao lado.
 * UX-GRAU: com `grau`, um círculo na cor do grau de dependência envolve a foto
 * (o selo com o texto do grau acompanha na tela; a cor nunca vai sozinha).
 * Sem `grau` (undefined), nenhum círculo.
 */
export function AvatarResidente({ nome, foto, grau, className }: { nome: string; foto?: string | null; grau?: GrauNaTela; className?: string }) {
  const src = fotoSegura(foto)
  const anel = grau === undefined ? '' : cn(ehGrau(grau) ? ANEL_GRAU[grau] : ANEL_SEM_GRAU, 'ring-offset-2 ring-offset-card')
  return src ? (
    <img src={src} alt="" aria-hidden="true" data-grau={grau ?? undefined} className={cn('size-10 shrink-0 rounded-full object-cover', anel, className)} />
  ) : (
    <span
      aria-hidden="true"
      data-grau={grau ?? undefined}
      className={cn('flex size-10 shrink-0 items-center justify-center rounded-full bg-avatar text-sm font-semibold text-avatar-foreground', anel, className)}
    >
      {iniciais(nome)}
    </span>
  )
}
