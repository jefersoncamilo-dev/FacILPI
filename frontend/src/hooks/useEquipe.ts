import { useState, useCallback, useEffect } from 'react'
import { equipeApi } from '../services/equipe'
import { CONTEXT_CHANGED_EVENT } from '../types/context'
import type {
  Funcionario, FuncionarioCreate, FuncionarioUpdate,
  User, UsuarioAdminCreate, UsuarioAdminUpdate,
  Perfil, PerfilAdminCreate, Permissao,
} from '../types/equipe'

export type Tab = 'funcionarios' | 'usuarios' | 'perfis'

export function useEquipe() {
  const [funcionarios, setFuncionarios] = useState<Funcionario[]>([])
  const [usuarios, setUsuarios] = useState<User[]>([])
  const [perfis, setPerfis] = useState<Perfil[]>([])
  const [permissoes, setPermissoes] = useState<Permissao[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('funcionarios')
  const [situacaoFilter, setSituacaoFilter] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const clearError = useCallback(() => setError(null), [])

  const loadFuncionarios = useCallback(async (situacao?: string | null) => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await equipeApi.listFuncionarios(situacao ?? undefined)
      setFuncionarios(data)
    } catch (e: any) {
      setError(e.response?.data?.detail?.message || e.response?.data?.detail || 'Erro ao carregar funcionários')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadUsuarios = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await equipeApi.listUsuarios()
      setUsuarios(data)
    } catch (e: any) {
      setError(e.response?.data?.detail?.message || e.response?.data?.detail || 'Erro ao carregar usuários')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadPerfis = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await equipeApi.listPerfis()
      setPerfis(data.filter(p => p.escopo === 'ilpi'))
    } catch (e: any) {
      setError(e.response?.data?.detail?.message || e.response?.data?.detail || 'Erro ao carregar perfis')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadPermissoes = useCallback(async () => {
    try {
      const { data } = await equipeApi.listPermissoes()
      setPermissoes(data)
    } catch (e: any) {
      setError(e.response?.data?.detail?.message || e.response?.data?.detail || 'Erro ao carregar permissões')
    }
  }, [])

  const createFuncionario = useCallback(async (data: FuncionarioCreate) => {
    const { data: created } = await equipeApi.createFuncionario(data)
    setFuncionarios(prev => [created, ...prev])
    return created
  }, [])

  const updateFuncionario = useCallback(async (id: string, data: FuncionarioUpdate) => {
    const { data: updated } = await equipeApi.updateFuncionario(id, data)
    setFuncionarios(prev => prev.map(f => f.id === id ? updated : f))
    return updated
  }, [])

  const inativarFuncionario = useCallback(async (id: string) => {
    await equipeApi.inativarFuncionario(id)
    setFuncionarios(prev => prev.map(f => f.id === id ? { ...f, situacao: 'inativo' as const } : f))
  }, [])

  const vincularUsuario = useCallback(async (funcionarioId: string, usuarioId: string) => {
    const { data: updated } = await equipeApi.vincularUsuario(funcionarioId, usuarioId)
    setFuncionarios(prev => prev.map(f => f.id === funcionarioId ? updated : f))
    return updated
  }, [])

  const desvincularUsuario = useCallback(async (funcionarioId: string) => {
    await equipeApi.desvincularUsuario(funcionarioId)
    setFuncionarios(prev => prev.map(f => f.id === funcionarioId ? { ...f, usuario_id: null } : f))
  }, [])

  const createUsuario = useCallback(async (data: UsuarioAdminCreate) => {
    const { data: created } = await equipeApi.createUsuario(data)
    const user: User = {
      id: created.id,
      nome: created.nome,
      email: created.email,
      ativo: true,
      is_superuser: false,
      exige_troca_senha: true,
    }
    setUsuarios(prev => [user, ...prev])
    return created
  }, [])

  const updateUsuario = useCallback(async (id: string, data: UsuarioAdminUpdate) => {
    const { data: updated } = await equipeApi.updateUsuario(id, data)
    setUsuarios(prev => prev.map(u => u.id === id ? updated : u))
    return updated
  }, [])

  const resetPassword = useCallback(async (id: string) => {
    const { data } = await equipeApi.resetPassword(id)
    return data.senha_temporaria
  }, [])

  const revogarAcesso = useCallback(async (usuarioId: string) => {
    await equipeApi.revogarAcesso(usuarioId)
    // A revogação desativa o vínculo ILPI no backend (User.ativo permanece
    // inalterado). Sincroniza com a fonte de verdade em vez de inventar estado.
    await loadUsuarios()
  }, [loadUsuarios])

  const createPerfil = useCallback(async (data: PerfilAdminCreate) => {
    const { data: created } = await equipeApi.createPerfil(data)
    setPerfis(prev => [...prev, created])
    return created
  }, [])

  const updatePerfilPermissoes = useCallback(async (perfilId: string, permissoesChave: string[]) => {
    await equipeApi.updatePermissoes(perfilId, permissoesChave)
  }, [])

  const filteredFuncionarios = funcionarios.filter(f => {    const matchesSituacao = !situacaoFilter || f.situacao === situacaoFilter
    const matchesSearch = !searchQuery ||
      f.nome.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (f.cpf || '').includes(searchQuery) ||
      (f.email || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (f.profissao || '').toLowerCase().includes(searchQuery.toLowerCase())
    return matchesSituacao && matchesSearch
  })

  const filteredUsuarios = usuarios.filter(u => {
    return !searchQuery ||
      u.nome.toLowerCase().includes(searchQuery.toLowerCase()) ||
      u.email.toLowerCase().includes(searchQuery.toLowerCase())
  })

  // Recarrega os dados tenant-scoped sempre que o contexto ativo trocar.
  useEffect(() => {
    const onContextChanged = () => {
      setError(null)
      void loadFuncionarios()
      void loadUsuarios()
      void loadPerfis()
    }
    window.addEventListener(CONTEXT_CHANGED_EVENT, onContextChanged)
    return () => window.removeEventListener(CONTEXT_CHANGED_EVENT, onContextChanged)
  }, [loadFuncionarios, loadUsuarios, loadPerfis])

  return {
    funcionarios, usuarios, perfis, permissoes,
    loading, error, tab, situacaoFilter, searchQuery,
    filteredFuncionarios, filteredUsuarios,
    setTab, setSituacaoFilter, setSearchQuery, clearError,
    loadFuncionarios, loadUsuarios, loadPerfis, loadPermissoes,
    createFuncionario, updateFuncionario, inativarFuncionario,
    vincularUsuario, desvincularUsuario,
    createUsuario, updateUsuario, resetPassword, revogarAcesso,
    createPerfil, updatePerfilPermissoes,
  }
}
