import type { ReactNode } from 'react'
import { Dialog, DialogContent } from './ui/dialog'

/**
 * Modal das telas existentes (UX-11 / #101). Mesmo contrato de antes
 * (`open`, `onClose`, `title`, `children`), agora sobre o Dialog do Radix:
 * foco preso dentro do diálogo, Escape, devolução do foco a quem abriu e o
 * mesmo visual dos diálogos das telas novas. Antes, Tab escapava para a página
 * de trás e cada modal tinha cabeçalho próprio.
 */
export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: string; children: ReactNode }) {
  return (
    <Dialog open={open} onOpenChange={aberto => { if (!aberto) onClose() }}>
      {open && <DialogContent title={title ?? ''}>{children}</DialogContent>}
    </Dialog>
  )
}
