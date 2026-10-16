import { cn } from '../../lib/utils'

/** "Maria da Silva Souza" → "MS". Um nome só → duas primeiras letras. */
export function iniciais(nome: string): string {
  const partes = nome.trim().split(/\s+/).filter(p => p.length > 2 || /^[A-ZÀ-Ý]/.test(p))
  if (partes.length === 0) return '?'
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase()
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase()
}

// Só imagem embutida ou HTTPS: o campo `foto` é texto livre e não deve virar
// requisição para qualquer endereço.
function fotoSegura(foto?: string | null): string | null {
  if (!foto) return null
  return /^data:image\/(png|jpe?g|webp|gif);base64,/i.test(foto) || /^https:\/\//i.test(foto) ? foto : null
}

/** Foto do residente ou, sem foto, as iniciais. Decorativo: o nome está ao lado. */
export function AvatarResidente({ nome, foto, className }: { nome: string; foto?: string | null; className?: string }) {
  const src = fotoSegura(foto)
  return src ? (
    <img src={src} alt="" aria-hidden="true" className={cn('size-10 shrink-0 rounded-full object-cover', className)} />
  ) : (
    <span
      aria-hidden="true"
      className={cn('flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-sm font-semibold text-primary', className)}
    >
      {iniciais(nome)}
    </span>
  )
}
