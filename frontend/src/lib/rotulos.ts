/**
 * Rótulos de exibição (UX-11 / #101). Valores de contrato continuam como o
 * backend grava ("Em admissao", "em_elaboracao", "planos_cuidados:ler"); aqui
 * só se decide como aparecem na tela, acentuados e legíveis. Valor sem rótulo
 * conhecido aparece como veio (texto livre, como a classificação de uma
 * avaliação, nunca é reescrito).
 */

const SITUACAO_RESIDENTE: Record<string, string> = {
  'Em admissao': 'Em admissão',
  'Pre-admissao': 'Pré-admissão',
}

/** Situação do residente (campo `Residente.situacao`). */
export function rotuloSituacaoResidente(valor?: string | null): string {
  if (!valor) return '—'
  return SITUACAO_RESIDENTE[valor] ?? valor
}

const SITUACAO_EVENTO: Record<string, string> = {
  ativo: 'Ativo', ativa: 'Ativa', inativa: 'Inativa', substituido: 'Substituído', revogado: 'Revogado',
  aberta: 'Aberta', encerrada: 'Encerrada', cancelada: 'Cancelada', prevista: 'Prevista',
  rascunho: 'Rascunho', em_elaboracao: 'Em elaboração', em_revisao: 'Em revisão', aprovado: 'Aprovado',
  vigente: 'Vigente', encerrado: 'Encerrado',
  executada: 'Executada', administrada: 'Administrada', recusada: 'Recusada', omitida: 'Omitida',
  alocacao: 'Alocação', transferencia: 'Transferência', liberacao: 'Liberação',
  hospitalizacao: 'Hospitalização', saida_temporaria: 'Saída temporária',
}

/** Situação/resultado de um evento da linha do tempo do prontuário. */
export function rotuloSituacaoEvento(valor?: string | null): string {
  if (!valor) return ''
  return SITUACAO_EVENTO[valor] ?? valor
}

const MODULO: Record<string, string> = {
  admissoes: 'Admissões', administracoes: 'Administração de medicamentos', auditoria: 'Auditoria',
  ausencias: 'Ausências', avaliacoes: 'Avaliações', configuracoes: 'Configurações', documentos: 'Documentos',
  execucoes: 'Execução de cuidados', familiares: 'Familiares', funcionarios: 'Funcionários',
  grau_dependencia: 'Grau de dependência', ilpis: 'Instituições', intercorrencias: 'Intercorrências',
  medicamentos: 'Medicamentos', ocorrencias: 'Ocorrências de cuidado', perfis: 'Perfis', permissoes: 'Permissões',
  planos_cuidados: 'Plano de cuidados', plantao: 'Plantão', prescricoes: 'Prescrições', programacoes: 'Programações de cuidado',
  quartos_leitos: 'Quartos e leitos', residentes: 'Residentes', sinais_vitais: 'Sinais vitais', tarefas: 'Tarefas',
  usuarios: 'Usuários',
}

const ACAO: Record<string, string> = {
  ler: 'Ver', criar: 'Cadastrar', atualizar: 'Editar', inativar: 'Inativar', anexar: 'Anexar',
  aprovar: 'Aprovar', revisar: 'Revisar', encerrar: 'Encerrar', cancelar: 'Cancelar', corrigir: 'Corrigir',
  validar: 'Validar', ativar: 'Ativar', suspender: 'Suspender', avancar: 'Avançar', concluir: 'Concluir',
  reabrir: 'Reabrir', atribuir_perfil: 'Atribuir perfil', atribuir_permissao: 'Atribuir permissões',
  redefinir_senha: 'Redefinir senha', vincular_usuario: 'Vincular usuário',
}

const semSublinhado = (valor: string) => valor.replace(/_/g, ' ')

/** Módulo do catálogo de permissões (`Permissao.modulo`). */
export function rotuloModulo(modulo: string): string {
  return MODULO[modulo] ?? semSublinhado(modulo)
}

/** Ação do catálogo de permissões (`Permissao.acao`). */
export function rotuloAcao(acao: string): string {
  return ACAO[acao] ?? semSublinhado(acao)
}
