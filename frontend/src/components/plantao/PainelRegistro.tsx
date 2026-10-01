import { useEffect, useRef, type ReactNode } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'

/**
 * Painel de registro do Meu Plantão (#136): Sheet inferior abaixo de 1024 px e
 * painel lateral direito a partir de 1024 px. A lista fica montada por baixo —
 * fechar devolve a pessoa ao mesmo ponto, sem recarregar nem rolar.
 *
 * Sobre o Radix Dialog (foco preso, Escape, aria-modal). O foco inicial vai ao
 * título (não ao primeiro botão), e ao fechar volta a quem abriu; se esse
 * elemento foi trocado na lista (ex.: a linha virou "registrada"), volta ao
 * elemento de `idRetorno`.
 */
export function PainelRegistro({
  aberto,
  aoFechar,
  titulo,
  cabecalho,
  rodape,
  children,
  chaveConteudo,
  idRetorno,
}: {
  aberto: boolean
  aoFechar: () => void
  titulo: string
  cabecalho: ReactNode
  rodape?: ReactNode
  children: ReactNode
  /** Mudou a chave com o painel aberto ("Salvar e próximo")? O foco volta ao título. */
  chaveConteudo?: string
  idRetorno?: string
}) {
  const tituloRef = useRef<HTMLHeadingElement>(null)
  const corpoRef = useRef<HTMLDivElement>(null)
  const anterior = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!aberto) return
    corpoRef.current?.scrollTo?.({ top: 0 })
    tituloRef.current?.focus()
  }, [chaveConteudo, aberto])

  return (
    <DialogPrimitive.Root open={aberto} onOpenChange={a => { if (!a) aoFechar() }}>
      {aberto && (
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/40 data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none" />
          <DialogPrimitive.Content
            aria-modal="true"
            onOpenAutoFocus={event => {
              anterior.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
              event.preventDefault()
              tituloRef.current?.focus()
            }}
            onCloseAutoFocus={event => {
              const alvo = anterior.current?.isConnected
                ? anterior.current
                : (idRetorno ? document.getElementById(idRetorno) : null)
              if (alvo) {
                event.preventDefault()
                alvo.focus({ preventScroll: true })
              }
            }}
            className={[
              'fixed inset-x-0 bottom-0 z-50 mx-auto flex max-h-[calc(100dvh-1.5rem)] w-full max-w-xl flex-col rounded-t-2xl bg-card shadow-xl focus:outline-none',
              'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-bottom-4 data-[state=open]:duration-200 motion-reduce:animate-none',
              'lg:inset-y-0 lg:left-auto lg:right-0 lg:mx-0 lg:h-full lg:max-h-none lg:max-w-md lg:rounded-none lg:rounded-l-2xl lg:border-l lg:border-border lg:data-[state=open]:slide-in-from-right-4',
            ].join(' ')}
          >
            <div className="shrink-0 border-b border-border px-4 pb-3 pt-2 lg:pt-4">
              <div className="mx-auto mb-2 h-1 w-9 rounded-full bg-input lg:hidden" aria-hidden="true" />
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <DialogPrimitive.Title asChild>
                    <h2 ref={tituloRef} tabIndex={-1} className="font-display text-lg font-semibold leading-tight text-foreground focus:outline-none">
                      {titulo}
                    </h2>
                  </DialogPrimitive.Title>
                  <DialogPrimitive.Description asChild>
                    <div className="mt-1 space-y-1 text-sm">{cabecalho}</div>
                  </DialogPrimitive.Description>
                </div>
                <DialogPrimitive.Close
                  className="inline-flex size-11 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  aria-label="Fechar"
                >
                  <X className="size-5" aria-hidden="true" />
                </DialogPrimitive.Close>
              </div>
            </div>
            <div ref={corpoRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4">
              {children}
            </div>
            {rodape && (
              <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border bg-card px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
                {rodape}
              </div>
            )}
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      )}
    </DialogPrimitive.Root>
  )
}
