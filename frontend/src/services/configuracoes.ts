import { api } from './api'

export interface Configuracoes {
  id: string
  razao_social: string
  cnpj: string | null
  situacao: string
  nome_fantasia: string | null
  endereco: string | null
  municipio: string | null
  uf: string | null
  telefone: string | null
  email: string | null
  responsavel_legal: string | null
  responsavel_tecnico: string | null
  capacidade: number | null
  licenca_sanitaria: string | null
  validade_licenca: string | null
  fuso_horario: string | null
}

export const configuracoesApi = {
  ler: () => api.get<Configuracoes>('/configuracoes/').then(r => r.data),
  salvar: (dados: Partial<Configuracoes>) => api.put<Configuracoes>('/configuracoes/', dados).then(r => r.data),
}
