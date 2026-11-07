import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router'
import { ChevronRight, Search, type LucideIcon } from 'lucide-react'
import { Dialog, DialogContent } from '../ui/dialog'
import { usePermissoes } from '../../context/PermissoesContext'
import { AvatarResidente } from '../residente/AvatarResidente'
import { getResidentesResumo, type ResidenteResumo } from '../../services/plantao'
import { contem, normalizar } from '../../lib/texto'
import { cn } from '../../lib/utils'
import { itensVisiveis, modulosVisiveis, type Pode } from './navegacao'

/**
 * UX-NAV-1: busca global (Ctrl+K) por residente ou tela.
 *
 * Residentes vêm de GET /residentes/ (a ILPI é a da sessão; o backend decide)
 * e só são buscados com `residentes:ler`. Telas são as que o menu mostra para
 * a sessão. Sem acento e sem maiúscula; nada de dado novo.
 */
const LIMITE = 6

export interface TelaBusca {
  to: string
  label: string
  secao: string
  icon: LucideIcon
}

/** Telas que a sessão pode abrir, com a seção do menu de cada uma. */
export function telasDaBusca(pode: Pode): TelaBusca[] {
  return modulosVisiveis(pode).flatMap(m =>
    m.tipo === 'link'
      ? [{ to: m.to, label: m.label, secao: 'Hoje', icon: m.icon }]
      : itensVisiveis(m, pode).map(i => ({ to: i.to, label: i.label, secao: m.label, icon: i.icon })),
  )
}

type Resultado =
  | { tipo: 'residente'; id: string; to: string; residente: ResidenteResumo }
  | { tipo: 'tela'; id: string; to: string; tela: TelaBusca }

export function BuscaGlobal({ open, onOpenChange }: { open: boolean; onOpenChange: (aberto: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && (
        <DialogContent title="Buscar" description="Residente ou tela do sistema." className="max-w-xl">
          <ConteudoBusca onFechar={() => onOpenChange(false)} />
        </DialogContent>
      )}
    </Dialog>
  )
}

function ConteudoBusca({ onFechar }: { onFechar: () => void }) {
  const navigate = useNavigate()
  const { pode } = usePermissoes()
  const podeResidentes = pode('residentes:ler')
  const [termo, setTermo] = useState('')
  const [residentes, setResidentes] = useState<ResidenteResumo[]>([])
  const [erroResidentes, setErroResidentes] = useState(false)
  const [ativo, setAtivo] = useState(0)

  useEffect(() => {
    if (!podeResidentes) return
    getResidentesResumo().then(r => setResidentes(r ?? [])).catch(() => setErroResidentes(true))
  }, [podeResidentes])

  const telas = useMemo(() => telasDaBusca(pode), [pode])
  const vazio = normalizar(termo) === ''

  const resultados: Resultado[] = useMemo(() => {
    if (vazio) return []
    const r: Resultado[] = residentes
      .filter(x => contem(x.nome, termo))
      .slice(0, LIMITE)
      .map(x => ({ tipo: 'residente', id: `r-${x.id}`, to: `/residentes/${x.id}`, residente: x }))
    const t: Resultado[] = telas
      .filter(x => contem(x.label, termo) || contem(x.secao, termo))
      .slice(0, LIMITE)
      .map(x => ({ tipo: 'tela', id: `t-${x.to}`, to: x.to, tela: x }))
    return [...r, ...t]
  }, [vazio, residentes, telas, termo])

  useEffect(() => setAtivo(0), [termo])

  function abrir(r: Resultado) {
    onFechar()
    navigate(r.to)
  }

  function teclar(e: KeyboardEvent<HTMLInputElement>) {
    if (!resultados.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setAtivo(i => (i + 1) % resultados.length) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setAtivo(i => (i - 1 + resultados.length) % resultados.length) }
    else if (e.key === 'Enter') { e.preventDefault(); abrir(resultados[ativo]) }
  }

  const deResidente = resultados.filter(r => r.tipo === 'residente')
  const deTela = resultados.filter(r => r.tipo === 'tela')
  const idDe = (r: Resultado) => `busca-${r.id}`

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <input
          type="search"
          role="combobox"
          aria-expanded={resultados.length > 0}
          aria-controls="busca-resultados"
          aria-activedescendant={resultados[ativo] ? idDe(resultados[ativo]) : undefined}
          aria-label="Buscar residente ou tela"
          placeholder="Nome do residente ou da tela"
          autoComplete="off"
          className="input min-h-[48px] pl-10 text-base"
          value={termo}
          onChange={e => setTermo(e.target.value)}
          onKeyDown={teclar}
        />
      </div>

      <div id="busca-resultados" role="listbox" aria-label="Resultados" className="max-h-[60vh] space-y-3 overflow-y-auto">
        {vazio ? (
          <p className="px-1 text-sm text-muted-foreground">
            {podeResidentes ? 'Digite o nome de um residente ou de uma tela.' : 'Digite o nome de uma tela.'}
          </p>
        ) : resultados.length === 0 ? (
          <div role="status" className="py-6 text-center">
            <p className="font-semibold text-foreground">Nenhum residente ou tela encontrado</p>
            <p className="mt-1 text-sm text-muted-foreground">Confira a grafia. Acentos e maiúsculas não importam.</p>
          </div>
        ) : (
          <>
            {deResidente.length > 0 && (
              <Grupo titulo="Residentes">
                {deResidente.map(r => r.tipo === 'residente' && (
                  <Opcao key={r.id} id={idDe(r)} ativa={resultados[ativo] === r} onEscolher={() => abrir(r)}>
                    <AvatarResidente nome={r.residente.nome} foto={r.residente.foto} className="size-9" />
                    <span className="min-w-0 flex-1 truncate font-medium">{r.residente.nome}</span>
                  </Opcao>
                ))}
              </Grupo>
            )}
            {deTela.length > 0 && (
              <Grupo titulo="Telas">
                {deTela.map(r => r.tipo === 'tela' && (
                  <Opcao key={r.id} id={idDe(r)} ativa={resultados[ativo] === r} onEscolher={() => abrir(r)}>
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-primary" aria-hidden="true">
                      <r.tela.icon className="size-[18px]" />
                    </span>
                    <span className="min-w-0 flex-1 truncate font-medium">{r.tela.label}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{r.tela.secao}</span>
                  </Opcao>
                ))}
              </Grupo>
            )}
          </>
        )}
        {erroResidentes && !vazio && (
          <p role="alert" className="px-1 text-sm text-muted-foreground">Não foi possível buscar residentes agora. As telas continuam disponíveis.</p>
        )}
      </div>
    </div>
  )
}

function Grupo({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div role="group" aria-label={titulo}>
      <p aria-hidden="true" className="px-1 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{titulo}</p>
      {children}
    </div>
  )
}

function Opcao({ id, ativa, onEscolher, children }: { id: string; ativa: boolean; onEscolher: () => void; children: React.ReactNode }) {
  return (
    <div
      id={id}
      role="option"
      aria-selected={ativa}
      onClick={onEscolher}
      className={cn(
        'flex min-h-[52px] cursor-pointer items-center gap-3 rounded-lg px-2 text-sm',
        ativa ? 'bg-brand-soft text-accent-foreground' : 'hover:bg-muted',
      )}
    >
      {children}
      <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    </div>
  )
}
