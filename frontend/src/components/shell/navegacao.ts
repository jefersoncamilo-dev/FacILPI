import {
  ArrowLeftRight,
  BedDouble,
  ClipboardCheck,
  ClipboardList,
  FileText,
  HeartPulse,
  LayoutDashboard,
  NotebookPen,
  TriangleAlert,
  UserPlus,
  Users,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'

/**
 * UX-01 (#83): navegação por TAREFA, não por módulo do backend.
 *
 * `permissao` é a chave que a tela exige no backend; sem ela, o item some.
 * `emBreve` marca telas cuja jornada ainda não foi entregue (a rota mostra um
 * aviso honesto) — com a Issue que a substitui.
 *
 * Fora do menu por não terem tela nem jornada nesta fase (GAP registrado na
 * UX-01): Cuidados Diários, Medicação, Agenda, Estoque, Financeiro, Portal da
 * Família, Relatórios, Supervisão, Compliance, Auditoria, Configurações e
 * Alertas. As rotas continuam existindo e explicam a situação.
 */
export interface ItemNav {
  to: string
  label: string
  icon: LucideIcon
  permissao?: string
  emBreve?: { issue: number }
}

export interface GrupoNav {
  titulo: string
  itens: ItemNav[]
}

export const NAVEGACAO: GrupoNav[] = [
  {
    titulo: 'Visão geral',
    itens: [{ to: '/', label: 'Início', icon: LayoutDashboard }],
  },
  {
    titulo: 'Plantão',
    itens: [
      { to: '/plantao', label: 'Meu Plantão', icon: ClipboardList, permissao: 'plantao:ler' },
      { to: '/sinais', label: 'Sinais Vitais', icon: HeartPulse, permissao: 'sinais_vitais:ler' },
      { to: '/intercorrencias', label: 'Intercorrências', icon: TriangleAlert, permissao: 'intercorrencias:ler' },
      { to: '/passagem', label: 'Passagem de Plantão', icon: ArrowLeftRight, permissao: 'plantao:ler' },
    ],
  },
  {
    titulo: 'Residentes',
    itens: [
      { to: '/residentes', label: 'Residentes', icon: Users, permissao: 'residentes:ler' },
      { to: '/admissoes', label: 'Admissões', icon: UserPlus, permissao: 'admissoes:ler' },
      { to: '/avaliacoes', label: 'Avaliações', icon: ClipboardCheck, permissao: 'avaliacoes:ler' },
      { to: '/plano', label: 'Plano de Cuidados', icon: NotebookPen, permissao: 'planos_cuidados:ler' },
      { to: '/documentos', label: 'Documentos', icon: FileText, permissao: 'documentos:ler' },
      { to: '/quartos', label: 'Quartos e Leitos', icon: BedDouble, permissao: 'quartos_leitos:ler' },
    ],
  },
  {
    titulo: 'Gestão',
    itens: [{ to: '/equipe', label: 'Equipe', icon: UsersRound, permissao: 'funcionarios:ler' }],
  },
]

/** Item do menu correspondente à rota atual (detalhe herda o item pai). */
export function itemDaRota(pathname: string): { grupo: GrupoNav; item: ItemNav } | null {
  for (const grupo of NAVEGACAO) {
    for (const item of grupo.itens) {
      if (item.to === '/' ? pathname === '/' : pathname === item.to || pathname.startsWith(`${item.to}/`)) {
        return { grupo, item }
      }
    }
  }
  return null
}
