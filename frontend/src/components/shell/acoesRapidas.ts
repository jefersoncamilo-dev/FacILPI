import {
  ArrowLeftRight,
  ClipboardCheck,
  ClipboardList,
  DoorOpen,
  FilePlus2,
  HeartPulse,
  NotebookPen,
  TriangleAlert,
  UserPlus,
  UserRoundPlus,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'

/**
 * Catálogo de ações rápidas do Início (UX-11 / #101). Quem define a lista de
 * cada pessoa é o próprio perfil de acesso: cada ação só aparece com a
 * permissão que o backend exige para ela (o backend continua decidindo cada
 * rota). O destino já abre o cadastro (`?registrar=1`, `?novo=1`,
 * `?ausencia=1`). A ordem muda com o contexto: no turno, registros primeiro;
 * na gestão, processos da instituição primeiro (menor número = antes).
 */
export interface AcaoRapida {
  id: string
  rotulo: string
  icone: LucideIcon
  to: string
  permissao: string
  /** Ações do dia a dia do cuidado: botão preenchido (verde/laranja). */
  destaque?: 'primario' | 'alerta'
  ordem: { operacao: number; gestao: number }
}

export const ACOES_RAPIDAS: AcaoRapida[] = [
  { id: 'sinal', rotulo: 'Registrar sinal vital', icone: HeartPulse, to: '/sinais?registrar=1', permissao: 'sinais_vitais:criar', destaque: 'primario', ordem: { operacao: 1, gestao: 7 } },
  { id: 'intercorrencia', rotulo: 'Registrar intercorrência', icone: TriangleAlert, to: '/intercorrencias?registrar=1', permissao: 'intercorrencias:criar', destaque: 'alerta', ordem: { operacao: 2, gestao: 8 } },
  { id: 'plantao', rotulo: 'Abrir Meu Plantão', icone: ClipboardList, to: '/plantao', permissao: 'plantao:ler', ordem: { operacao: 3, gestao: 9 } },
  { id: 'passagem', rotulo: 'Passagem de plantão', icone: ArrowLeftRight, to: '/passagem', permissao: 'plantao:ler', ordem: { operacao: 4, gestao: 10 } },
  { id: 'ausencia', rotulo: 'Registrar ausência', icone: DoorOpen, to: '/quartos?ausencia=1', permissao: 'ausencias:criar', ordem: { operacao: 5, gestao: 6 } },
  { id: 'avaliacao', rotulo: 'Nova avaliação', icone: ClipboardCheck, to: '/avaliacoes?novo=1', permissao: 'avaliacoes:criar', ordem: { operacao: 6, gestao: 4 } },
  { id: 'admissao', rotulo: 'Nova admissão', icone: UserRoundPlus, to: '/admissoes?novo=1', permissao: 'admissoes:criar', ordem: { operacao: 7, gestao: 1 } },
  { id: 'plano', rotulo: 'Novo plano de cuidados', icone: NotebookPen, to: '/plano?novo=1', permissao: 'planos_cuidados:criar', ordem: { operacao: 8, gestao: 3 } },
  { id: 'documento', rotulo: 'Cadastrar documento', icone: FilePlus2, to: '/documentos?novo=1', permissao: 'documentos:criar', ordem: { operacao: 9, gestao: 5 } },
  { id: 'residente', rotulo: 'Cadastrar residente', icone: UserPlus, to: '/residentes?novo=1', permissao: 'residentes:criar', ordem: { operacao: 10, gestao: 2 } },
  { id: 'funcionario', rotulo: 'Novo funcionário', icone: UsersRound, to: '/equipe?novo=1', permissao: 'funcionarios:criar', ordem: { operacao: 11, gestao: 11 } },
]

/** Ações que o perfil pode executar, na ordem do contexto. */
export function acoesDoPerfil(pode: (chave?: string) => boolean, gestao: boolean): AcaoRapida[] {
  const chave = gestao ? 'gestao' : 'operacao'
  return ACOES_RAPIDAS.filter(a => pode(a.permissao)).sort((a, b) => a.ordem[chave] - b.ordem[chave])
}
