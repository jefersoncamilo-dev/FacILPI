import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { BotaoVoltar } from './BotaoVoltar'

export interface LinkVerTambem {
  to: string
  rotulo: string
}

/**
 * UX-NAV-0: esqueleto de toda página de módulo.
 *
 * 1. Trilha: no computador, a barra superior do shell já mostra
 *    "Seção › Tela"; no celular, o Voltar faz esse papel.
 * 2. Título e subtítulo. 3. Uma ação primária (no máximo).
 * 4–6. Abas, filtros e lista vêm em `children`. 7. "Ver também".
 */
export function PaginaModulo({
  titulo,
  subtitulo,
  acao,
  voltarPara,
  verTambem = [],
  children,
}: {
  titulo: string
  subtitulo?: string
  /** A ação primária da tela; quem não pode executá-la não deve recebê-la. */
  acao?: ReactNode
  /** Destino do Voltar no celular quando não há histórico (ex.: hub da seção). */
  voltarPara?: string
  verTambem?: LinkVerTambem[]
  children: ReactNode
}) {
  return (
    <div className="space-y-5">
      {voltarPara && (
        <div className="xl:hidden">
          <BotaoVoltar fallback={voltarPara} />
        </div>
      )}

      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="font-display text-titulo-tela text-brand-ink">{titulo}</h1>
          {subtitulo && <p className="mt-1 text-sm text-muted-foreground">{subtitulo}</p>}
        </div>
        {acao && <div className="shrink-0 [&>*]:w-full sm:[&>*]:w-auto">{acao}</div>}
      </header>

      {children}

      {verTambem.length > 0 && (
        <nav aria-label="Ver também" className="flex flex-wrap items-center gap-2 pt-2">
          <span className="text-sm font-semibold text-muted-foreground">Ver também</span>
          {verTambem.map(link => (
            <Link
              key={link.to}
              to={link.to}
              className="inline-flex min-h-[44px] items-center rounded-full border border-border bg-card px-4 text-sm font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {link.rotulo}
            </Link>
          ))}
        </nav>
      )}
    </div>
  )
}
