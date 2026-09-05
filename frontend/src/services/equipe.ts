import { api } from './api'
import type {
  Funcionario, FuncionarioCreate, FuncionarioUpdate,
  User, UsuarioAdminCreate, UsuarioAdminUpdate,
  Perfil, PerfilAdminCreate,
  Permissao,
} from '../types/equipe'

export const equipeApi = {
  listFuncionarios(situacao?: string) {
    const params: Record<string, string> = {}
    if (situacao) params.situacao = situacao
    return api.get<Funcionario[]>('/funcionarios/', { params })
  },

  getFuncionario(id: string) {
    return api.get<Funcionario>(`/funcionarios/${id}`)
  },

  createFuncionario(data: FuncionarioCreate) {
    return api.post<Funcionario>('/funcionarios/', data)
  },

  updateFuncionario(id: string, data: FuncionarioUpdate) {
    return api.put<Funcionario>(`/funcionarios/${id}`, data)
  },

  inativarFuncionario(id: string) {
    return api.delete(`/funcionarios/${id}`)
  },

  vincularUsuario(funcionarioId: string, usuarioId: string) {
    return api.post(`/funcionarios/${funcionarioId}/vincular-usuario`, { usuario_id: usuarioId })
  },

  desvincularUsuario(funcionarioId: string) {
    return api.delete(`/funcionarios/${funcionarioId}/vincular-usuario`)
  },

  listUsuarios() {
    return api.get<User[]>('/usuarios/')
  },

  getUsuario(id: string) {
    return api.get<User>(`/usuarios/${id}`)
  },

  createUsuario(data: UsuarioAdminCreate) {
    return api.post<{ id: string; nome: string; email: string; senha_temporaria: string }>('/usuarios/', data)
  },

  updateUsuario(id: string, data: UsuarioAdminUpdate) {
    return api.put<User>(`/usuarios/${id}`, data)
  },

  resetPassword(id: string) {
    return api.patch<{ senha_temporaria: string }>(`/usuarios/${id}/reset-password`)
  },

  atribuirPerfil(usuarioId: string, perfilId: string) {
    return api.post(`/usuarios/${usuarioId}/perfis`, { perfil_id: perfilId })
  },

  revogarAcesso(usuarioId: string) {
    return api.delete(`/usuarios/${usuarioId}/acesso`)
  },

  listPerfis() {
    return api.get<Perfil[]>('/perfis/')
  },

  createPerfil(data: PerfilAdminCreate) {
    return api.post<Perfil>('/perfis/', data)
  },

  updatePermissoes(perfilId: string, permissoes: string[]) {
    return api.put(`/perfis/${perfilId}/permissoes`, { permissoes })
  },

  listPermissoes() {
    return api.get<Permissao[]>('/permissoes/')
  },
}
