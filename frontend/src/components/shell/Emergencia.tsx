import { useEffect, useMemo, useState } from 'react'
import { Link, matchPath, useLocation } from 'react-router-dom'
import { ChevronRight, FileText, Search, Siren } from 'lucide-react'
import { Dialog, DialogContent } from '../ui/dialog'
import { usePermissoes } from '../../context/PermissoesContext'
import { AvatarResidente } from '../residente/AvatarResidente'
import { getResidentesResumo, type ResidenteResumo } from '../../services/plantao'
import { cn } from '../../lib/utils'

const BOTTOM_SHEET =
  'max-sm:bottom-0 max-sm:left-0 max-sm:top-auto max-sm:max-h-[92vh] max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-b-none max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]'

/**
 * Entrada global de Emergência (header, ao lado dos alertas). Um toque nunca
 * executa nada crítico: abre o diálogo, pede o residente (ou usa o do
 * prontuário aberto) e oferece só ações que já existem. Resumo de emergência
 * e encaminhamento entram aqui quando existirem (EMG) — sem placeholders.
 * Aparece só para quem lê residentes; o backend continua decidindo cada rota.
 */
export function Emergencia({ compacto = false }: { compacto?: boolean }) {
  const { pode } = usePermissoes()
  const [aberto, setAberto] = useState(false)
  if (!pode('residentes:ler')) return null

  return (
    <>
      <button
        type="button"
        onClick={() => setAberto(true)}
        aria-haspopup="dialog"
        aria-expanded={aberto}
        aria-label="Emergência"
        className={cn(
          'inline-flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-full border border-red-300 bg-card px-3 text-sm font-semibold text-red-700 transition-colors hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500',
          compacto && 'px-2.5',
        )}
      >
        <Siren className="size-5 shrink-0" aria-hidden="true" />
        <span className={cn(compacto && 'max-[400px]:sr-only')}>Emergência</span>
      </button>
      <Dialog open={aberto} onOpenChange={setAberto}>
        {aberto && (
          <DialogContent title="Emergência" focarConteudo className={BOTTOM_SHEET}>
            <ConteudoEmergencia onFechar={() => setAberto(false)} />
          </DialogContent>
        )}
      </Dialog>
    </>
  )
}

function ConteudoEmergencia({ onFechar }: { onFechar: () => void }) {
  const { pathname } = useLocation()
  const doProntuario = matchPath('/residentes/:id', pathname)?.params.id ?? null
  const [residentes, setResidentes] = useState<ResidenteResumo[] | null>(null)
  const [erro, setErro] = useState(false)
  const [escolhido, setEscolhido] = useState<string | null>(doProntuario)
  const [busca, setBusca] = useState('')

  useEffect(() => {
    getResidentesResumo().then(setResidentes).catch(() => setErro(true))
  }, [])

  const filtrados = useMemo(() => {
    const termo = busca.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim()
    const lista = residentes ?? []
    return termo
      ? lista.filter(r => r.nome.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().includes(termo))
      : lista
  }, [residentes, busca])

  const residente = residentes?.find(r => r.id === escolhido)
  if (escolhido) {
    const nome = residente?.nome ?? 'Residente'
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 rounded-lg bg-muted p-3">
          <AvatarResidente nome={nome} foto={residente?.foto} className="size-12" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-semibold">{nome}</div>
            <button type="button" onClick={() => setEscolhido(null)} className="min-h-[44px] text-sm font-medium text-primary hover:underline">
              Trocar residente
            </button>
          </div>
        </div>
        <Link
          to={`/residentes/${escolhido}`}
          onClick={onFechar}
          className="flex min-h-[56px] items-center gap-3 rounded-xl border border-border px-4 font-semibold hover:bg-muted"
        >
          <FileText className="size-5 text-primary" aria-hidden="true" />
          <span className="flex-1">Abrir prontuário</span>
          <ChevronRight className="size-5 text-muted-foreground" aria-hidden="true" />
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Para qual residente?</p>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <input
          type="search"
          aria-label="Buscar residente"
          placeholder="Buscar pelo nome"
          className="input min-h-[48px] pl-9"
          value={busca}
          onChange={e => setBusca(e.target.value)}
        />
      </div>
      {erro ? (
        <p className="text-sm font-medium text-danger" role="alert">Não foi possível carregar os residentes.</p>
      ) : residentes === null ? (
        <p className="text-sm text-muted-foreground">Carregando residentes…</p>
      ) : filtrados.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nenhum residente encontrado.</p>
      ) : (
        <ul className="max-h-[50vh] space-y-1 overflow-y-auto" aria-label="Residentes">
          {filtrados.map(r => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => setEscolhido(r.id)}
                className="flex min-h-[52px] w-full items-center gap-3 rounded-lg px-2 text-left hover:bg-muted"
              >
                <AvatarResidente nome={r.nome} foto={r.foto} />
                <span className="flex-1 truncate font-medium">{r.nome}</span>
                <ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
