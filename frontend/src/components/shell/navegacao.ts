import {
  ArrowLeftRight,
  BarChart3,
  BedDouble,
  BellRing,
  Boxes,
  Brain,
  Briefcase,
  CalendarClock,
  ClipboardCheck,
  ClipboardList,
  FileText,
  HandHeart,
  HeartHandshake,
  HeartPulse,
  History,
  LayoutDashboard,
  NotebookPen,
  Package,
  Pill,
  Settings,
  Stethoscope,
  Syringe,
  TriangleAlert,
  Activity,
  Apple,
  UserPlus,
  Users,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'

/**
 * UX-00 (navegação + hubs): arquitetura de informação por MÓDULO.
 *
 * - Módulo `link`: destino único na raiz do menu (Início, Central de Alertas,
 *   Meu Plantão). Meu Plantão existe só aqui — nunca dentro de outro módulo.
 * - Módulo `grupo`: nome abre o hub (`/modulos/<id>`), itens são as telas.
 *
 * `status: 'futuro'` declara a arquitetura sem criar tela falsa: item ou
 * módulo futuro NUNCA é exibido (nem no menu, nem no hub), mesmo quando as
 * permissões estão indisponíveis. Ativar = trocar para `ativo` com rota real.
 *
 * `permissao` é a chave que a tela exige no backend; sem ela, o item some.
 * Isso orienta a interface, não autoriza — cada rota do backend decide.
 * `permissaoPlanejada` só documenta a chave prevista para um domínio futuro;
 * não é consultada nem concede nada.
 */
export type StatusNav = 'ativo' | 'futuro'

/** `pode` do PermissoesContext: sem chave, sempre pode. */
export type Pode = (chave?: string) => boolean

interface ItemBase {
  id: string
  label: string
  icon: LucideIcon
  /** Uma linha para o card do hub. */
  descricao: string
}

export interface ItemAtivo extends ItemBase {
  status: 'ativo'
  to: string
  permissao?: string
}

export interface ItemFuturo extends ItemBase {
  status: 'futuro'
  permissaoPlanejada?: string
}

export type ItemNav = ItemAtivo | ItemFuturo

interface ModuloBase {
  id: string
  label: string
  icon: LucideIcon
  status: StatusNav
}

export interface ModuloLink extends ModuloBase {
  tipo: 'link'
  to: string
  permissao?: string
}

export interface ModuloGrupo extends ModuloBase {
  tipo: 'grupo'
  /** Uma linha para o cabeçalho do hub. */
  descricao: string
  itens: ItemNav[]
}

export type ModuloNav = ModuloLink | ModuloGrupo

/** Domínio multidisciplinar futuro: cada profissão com chave própria, sem acesso cruzado. */
function dominioMultidisciplinar(id: string, label: string, icon: LucideIcon, descricao: string): ItemAtivo {
  return { id, label, icon, descricao, status: 'ativo', to: `/multidisciplinar/${id}`, permissao: `multidisciplinar.${id}:ler` }
}

export const MODULOS: ModuloNav[] = [
  { tipo: 'link', id: 'inicio', label: 'Início', icon: LayoutDashboard, status: 'ativo', to: '/' },
  { tipo: 'link', id: 'alertas', label: 'Central de Alertas', icon: BellRing, status: 'ativo', to: '/alertas', permissao: 'alertas:ler' },
  { tipo: 'link', id: 'plantao', label: 'Meu Plantão', icon: ClipboardList, status: 'ativo', to: '/plantao', permissao: 'plantao:ler' },
  {
    tipo: 'grupo',
    id: 'residentes',
    label: 'Residentes',
    icon: Users,
    status: 'ativo',
    descricao: 'Cadastro, entrada e acomodação dos residentes.',
    itens: [
      { id: 'residentes', label: 'Residentes', icon: Users, status: 'ativo', to: '/residentes', permissao: 'residentes:ler', descricao: 'Lista e prontuário de cada residente.' },
      { id: 'admissoes', label: 'Admissões', icon: UserPlus, status: 'ativo', to: '/admissoes', permissao: 'admissoes:ler', descricao: 'Entradas em andamento e concluídas.' },
      { id: 'documentos', label: 'Documentos', icon: FileText, status: 'ativo', to: '/documentos', permissao: 'documentos:ler', descricao: 'Documentos dos residentes e validação.' },
      { id: 'quartos', label: 'Quartos e Leitos', icon: BedDouble, status: 'ativo', to: '/quartos', permissao: 'quartos_leitos:ler', descricao: 'Ocupação, leitos livres e ausências.' },
      { id: 'estoque', label: 'Estoque do Residente', icon: Package, status: 'futuro', permissaoPlanejada: 'estoque_residente:ler', descricao: 'Itens pessoais e de consumo de cada residente.' },
    ],
  },
  {
    tipo: 'grupo',
    id: 'assistencial',
    label: 'Assistencial',
    icon: HeartPulse,
    status: 'ativo',
    descricao: 'Rotina do cuidado: registros, ocorrências e troca de turno.',
    itens: [
      { id: 'agenda', label: 'Agenda', icon: CalendarClock, status: 'ativo', to: '/agenda', permissao: 'agenda:ler', descricao: 'Consultas e compromissos dos residentes.' },
      { id: 'cuidados', label: 'Cuidados', icon: HandHeart, status: 'ativo', to: '/cuidados', permissao: 'programacoes:ler', descricao: 'Cuidados diários programados.' },
      { id: 'sinais', label: 'Sinais Vitais', icon: HeartPulse, status: 'ativo', to: '/sinais', permissao: 'sinais_vitais:ler', descricao: 'Aferições e histórico por residente.' },
      { id: 'intercorrencias', label: 'Intercorrências', icon: TriangleAlert, status: 'ativo', to: '/intercorrencias', permissao: 'intercorrencias:ler', descricao: 'Ocorrências registradas e acompanhamento.' },
      // G8: mesma chave do backend (#125); todo template com plantao:ler também tem esta.
      { id: 'passagem', label: 'Passagem de Plantão', icon: ArrowLeftRight, status: 'ativo', to: '/passagem', permissao: 'passagem_plantao:ler', descricao: 'Resumo do turno para quem assume.' },
    ],
  },
  {
    tipo: 'grupo',
    id: 'multidisciplinar',
    label: 'Multidisciplinar',
    icon: Stethoscope,
    status: 'ativo',
    descricao: 'Avaliações e plano de cuidados compartilhados entre as áreas.',
    itens: [
      { id: 'avaliacoes', label: 'Avaliações', icon: ClipboardCheck, status: 'ativo', to: '/avaliacoes', permissao: 'avaliacoes:ler', descricao: 'Avaliações e grau de dependência.' },
      { id: 'pia', label: 'PIA', icon: FileText, status: 'ativo', to: '/pia', permissao: 'pia:ler', descricao: 'Plano Individual de Atendimento do residente.' },
      { id: 'plano', label: 'Plano de Cuidados', icon: NotebookPen, status: 'ativo', to: '/plano', permissao: 'planos_cuidados:ler', descricao: 'PAIS: objetivos, ações e revisões.' },
      dominioMultidisciplinar('fisioterapia', 'Fisioterapia', Activity, 'Agenda, atendimentos e evoluções da fisioterapia.'),
      dominioMultidisciplinar('nutricao', 'Nutrição', Apple, 'Avaliações nutricionais e plano alimentar.'),
      dominioMultidisciplinar('psicologia', 'Psicologia', Brain, 'Atendimentos e acompanhamentos psicológicos.'),
      dominioMultidisciplinar('servico_social', 'Serviço Social', HeartHandshake, 'Atendimentos, família e acompanhamento social.'),
      dominioMultidisciplinar('enfermagem', 'Enfermagem', Syringe, 'Avaliações, procedimentos e evoluções.'),
    ],
  },
  {
    tipo: 'grupo',
    id: 'farmacia',
    label: 'Farmácia',
    icon: Pill,
    status: 'ativo',
    descricao: 'Estoque, lotes e validades com histórico de movimentos.',
    itens: [
      { id: 'estoque', label: 'Estoque', icon: Boxes, status: 'ativo', to: '/estoque', permissao: 'estoque:ler', descricao: 'Saldo por lote, validade e movimentos.' },
    ],
  },
  {
    tipo: 'grupo',
    id: 'equipe',
    label: 'Equipe',
    icon: UsersRound,
    status: 'ativo',
    descricao: 'Pessoas, acessos e quem responde por cada área.',
    itens: [
      { id: 'funcionarios', label: 'Funcionários', icon: UsersRound, status: 'ativo', to: '/equipe', permissao: 'funcionarios:ler', descricao: 'Cadastro, acessos e perfis.' },
      // #120: quem responde por qual área agora, áreas e turnos.
      { id: 'escala', label: 'Escala', icon: CalendarClock, status: 'ativo', to: '/escala', permissao: 'escala:ler', descricao: 'Áreas, turnos e responsáveis.' },
    ],
  },
  {
    tipo: 'grupo',
    id: 'gestao',
    label: 'Gestão',
    icon: Briefcase,
    status: 'ativo',
    descricao: 'Indicadores e processos da instituição.',
    itens: [
      { id: 'mensalidades', label: 'Mensalidades', icon: FileText, status: 'ativo', to: '/financeiro', permissao: 'financeiro:ler', descricao: 'Controle manual de mensalidades por residente.' },
    ],
  },
  {
    tipo: 'grupo',
    id: 'relatorios',
    label: 'Relatórios',
    icon: BarChart3,
    status: 'ativo',
    descricao: 'Relatórios operacionais e assistenciais.',
    itens: [
      { id: 'resumo', label: 'Resumo da instituição', icon: BarChart3, status: 'ativo', to: '/relatorios', permissao: 'residentes:ler', descricao: 'Residentes, intercorrências e medicação no período.' },
    ],
  },
  {
    tipo: 'grupo',
    id: 'configuracoes',
    label: 'Configurações',
    icon: Settings,
    status: 'ativo',
    descricao: 'Preferências da instituição.',
    itens: [
      { id: 'instituicao', label: 'Instituição', icon: Settings, status: 'ativo', to: '/configuracoes', permissao: 'configuracoes:ler', descricao: 'Dados, contato, licença e fuso.' },
      { id: 'auditoria', label: 'Auditoria', icon: History, status: 'ativo', to: '/auditoria', permissao: 'auditoria:ler', descricao: 'Quem fez o quê e quando.' },
    ],
  },
]

/** Endereço do hub de um módulo-grupo. */
export function rotaDoHub(modulo: ModuloGrupo): string {
  return `/modulos/${modulo.id}`
}

/** Itens do grupo que existem e que a sessão pode abrir. */
export function itensVisiveis(modulo: ModuloGrupo, pode: Pode): ItemAtivo[] {
  if (modulo.status !== 'ativo') return []
  return modulo.itens.filter((i): i is ItemAtivo => i.status === 'ativo' && pode(i.permissao))
}

/** Módulo aparece se existe e tem ao menos um destino permitido. */
export function moduloVisivel(modulo: ModuloNav, pode: Pode): boolean {
  if (modulo.status !== 'ativo') return false
  return modulo.tipo === 'link' ? pode(modulo.permissao) : itensVisiveis(modulo, pode).length > 0
}

export function modulosVisiveis(pode: Pode): ModuloNav[] {
  return MODULOS.filter(m => moduloVisivel(m, pode))
}

/**
 * Grupo ativo pelo slug do hub. `null` para slug desconhecido, módulo futuro
 * ou módulo-link (sem hub): a rota deve redirecionar. Grupo existente sem item
 * permitido NÃO vira `null` — o hub mostra "Sem acesso a este módulo".
 */
export function moduloPorSlug(slug: string | undefined): ModuloGrupo | null {
  const modulo = MODULOS.find(m => m.id === slug)
  return modulo && modulo.tipo === 'grupo' && modulo.status === 'ativo' ? modulo : null
}

function casa(to: string, pathname: string): boolean {
  return to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(`${to}/`)
}

/**
 * Módulo (e item) da rota atual; o detalhe herda o item pai. No hub,
 * `item` é `null`. Só considera destinos ativos.
 */
export function moduloDaRota(pathname: string): { modulo: ModuloNav; item: ItemAtivo | null } | null {
  const hub = /^\/modulos\/([^/]+)\/?$/.exec(pathname)
  if (hub) {
    const modulo = moduloPorSlug(hub[1])
    return modulo ? { modulo, item: null } : null
  }
  for (const modulo of MODULOS) {
    if (modulo.status !== 'ativo') continue
    if (modulo.tipo === 'link') {
      if (casa(modulo.to, pathname)) return { modulo, item: null }
      continue
    }
    for (const item of modulo.itens) {
      if (item.status === 'ativo' && casa(item.to, pathname)) return { modulo, item }
    }
  }
  return null
}
