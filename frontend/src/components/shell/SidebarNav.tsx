import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import {
  itensVisiveis,
  moduloDaRota,
  modulosVisiveis,
  rotaDoHub,
  type ItemAtivo,
  type ModuloGrupo,
  type ModuloLink,
  type Pode,
} from './navegacao'

/**
 * UX-00B: sidebar híbrida em accordion.
 *
 * - Um grupo aberto por vez; o grupo da rota ativa abre sozinho.
 * - A escolha da pessoa fica na aba (`sessionStorage`), e vale ao reabrir o
 *   menu ou recarregar fora de um grupo. Grupo que sumiu (troca de contexto,
 *   permissão) é ignorado.
 * - `comHub` (UX-00C): o nome do módulo é link para o hub (`/modulos/<id>`)
 *   e o chevron é um botão separado que só expande/recolhe. Sem hubs, o
 *   cabeçalho inteiro é um só botão — nunca um link para tela inexistente.
 */
export const CHAVE_GRUPO_ABERTO = 'facilpi:nav:grupo'

/** UX-00C: `/modulos/:modulo` existe; o nome do módulo abre o hub. */
const HUBS_DISPONIVEIS = true

function lerGrupoSalvo(): string | null {
  try {
    return sessionStorage.getItem(CHAVE_GRUPO_ABERTO)
  } catch {
    return null
  }
}

function salvarGrupo(id: string | null) {
  try {
    sessionStorage.setItem(CHAVE_GRUPO_ABERTO, id ?? '')
  } catch {
    // Armazenamento bloqueado: o accordion segue funcionando só em memória.
  }
}

/** Grupo aberto: o da rota ativa; fora de grupo, o último escolhido na aba. */
function useGrupoAberto(grupos: ModuloGrupo[], grupoAtivo: string | null) {
  const visivel = (id: string | null) => !!id && grupos.some(g => g.id === id)
  const [aberto, setAberto] = useState<string | null>(() => {
    if (grupoAtivo) return grupoAtivo
    const salvo = lerGrupoSalvo()
    return visivel(salvo) ? salvo : null
  })

  // Navegar para uma tela de outro grupo abre esse grupo.
  useEffect(() => {
    if (grupoAtivo) {
      setAberto(grupoAtivo)
      salvarGrupo(grupoAtivo)
    }
  }, [grupoAtivo])

  function alternar(id: string) {
    const proximo = aberto === id ? null : id
    setAberto(proximo)
    salvarGrupo(proximo)
  }

  return { aberto: visivel(aberto) ? aberto : null, alternar }
}

export function SecoesNavegacao({ pode }: { pode: Pode }) {
  const { pathname } = useLocation()
  const modulos = modulosVisiveis(pode)
  const grupos = modulos.filter((m): m is ModuloGrupo => m.tipo === 'grupo')
  const atual = moduloDaRota(pathname)
  const grupoAtivo = atual?.modulo.tipo === 'grupo' ? atual.modulo.id : null
  const { aberto, alternar } = useGrupoAberto(grupos, grupoAtivo)

  return (
    <ul className="space-y-0.5">
      {modulos.map(modulo =>
        modulo.tipo === 'link' ? (
          <li key={modulo.id}><ItemRaiz modulo={modulo} /></li>
        ) : (
          <li key={modulo.id}>
            <SidebarGrupo
              modulo={modulo}
              itens={itensVisiveis(modulo, pode)}
              ativo={grupoAtivo === modulo.id}
              aberto={aberto === modulo.id}
              comHub={HUBS_DISPONIVEIS}
              onAlternar={() => alternar(modulo.id)}
            />
          </li>
        ),
      )}
    </ul>
  )
}

const linha = 'flex min-h-[44px] items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors'

function ItemRaiz({ modulo }: { modulo: ModuloLink }) {
  const Icone = modulo.icon
  return (
    <NavLink
      to={modulo.to}
      end={modulo.to === '/'}
      className={({ isActive }) =>
        cn(
          linha,
          isActive
            ? 'bg-brand-soft font-semibold text-accent-foreground'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground',
        )
      }
    >
      <Icone className="size-[18px] shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{modulo.label}</span>
    </NavLink>
  )
}

export function SidebarGrupo({
  modulo,
  itens,
  ativo,
  aberto,
  comHub,
  onAlternar,
}: {
  modulo: ModuloGrupo
  itens: ItemAtivo[]
  /** A rota atual pertence a este módulo. */
  ativo: boolean
  aberto: boolean
  comHub: boolean
  onAlternar: () => void
}) {
  const Icone = modulo.icon
  const idLista = `nav-grupo-${modulo.id}`
  // Módulo ativo: peso, cor do ícone e, recolhido, fundo — nunca só a cor.
  const tomCabecalho = ativo
    ? cn('font-semibold text-foreground', !aberto && 'bg-muted')
    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
  const icone = <Icone className={cn('size-[18px] shrink-0', ativo && 'text-primary')} aria-hidden="true" />
  const chevron = (
    <ChevronDown
      className={cn('size-4 shrink-0 transition-transform motion-reduce:transition-none', aberto && 'rotate-180')}
      aria-hidden="true"
    />
  )

  return (
    <div>
      {comHub ? (
        <div className={cn('flex items-center rounded-lg', tomCabecalho)}>
          <NavLink to={rotaDoHub(modulo)} className={cn(linha, 'min-w-0 flex-1 pr-1')}>
            {icone}
            <span className="min-w-0 flex-1 truncate">{modulo.label}</span>
          </NavLink>
          {/* Nome estável; o estado vai em aria-expanded. */}
          <button
            type="button"
            onClick={onAlternar}
            aria-expanded={aberto}
            aria-controls={idLista}
            aria-label={`Submenu de ${modulo.label}`}
            className="flex size-11 shrink-0 items-center justify-center rounded-lg hover:bg-muted"
          >
            {chevron}
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={onAlternar}
          aria-expanded={aberto}
          aria-controls={idLista}
          className={cn(linha, 'w-full text-left', tomCabecalho)}
        >
          {icone}
          <span className="min-w-0 flex-1 truncate">{modulo.label}</span>
          {chevron}
        </button>
      )}

      <ul id={idLista} hidden={!aberto} className="ml-[21px] mt-0.5 space-y-0.5 border-l border-border pl-2">
        {itens.map(item => (
          <li key={item.id}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                cn(
                  linha,
                  'relative',
                  isActive
                    ? 'bg-brand-soft font-semibold text-accent-foreground before:absolute before:-left-[9px] before:inset-y-2 before:w-[3px] before:rounded-full before:bg-primary'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )
              }
            >
              <item.icon className="size-4 shrink-0" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  )
}
