import { useEffect, useCallback, useState } from 'react'
import { useEquipe } from '../hooks/useEquipe'
import type { Tab } from '../hooks/useEquipe'
import type { Funcionario, User, Perfil } from '../types/equipe'
import { FuncionarioCard } from '../components/equipe/FuncionarioCard'
import { FuncionarioFormModal } from '../components/equipe/FuncionarioFormModal'
import { ConcederAcessoModal } from '../components/equipe/ConcederAcessoModal'
import { VincularUsuarioModal } from '../components/equipe/VincularUsuarioModal'
import { RevogarAcessoModal } from '../components/equipe/RevogarAcessoModal'
import { InativarFuncionarioModal } from '../components/equipe/InativarFuncionarioModal'
import { UsuariosSection } from '../components/equipe/UsuariosSection'
import { PerfilFormModal } from '../components/equipe/PerfilFormModal'

function useModalState<T>(initial: T) {
  const [isOpen, setIsOpen] = useState(false)
  const [data, setData] = useState<T>(initial)

  function open(value: T) {
    setData(value)
    setIsOpen(true)
  }

  function close() {
    setIsOpen(false)
    setData(initial)
  }

  return { isOpen, data, open, close }
}

const situacaoFilters = [
  { value: null, label: 'Todos' },
  { value: 'ativo', label: 'Ativos' },
  { value: 'afastado', label: 'Afastados' },
  { value: 'inativo', label: 'Inativos' },
] as const

const tabConfig: { key: Tab; label: string }[] = [
  { key: 'funcionarios', label: 'Funcionários' },
  { key: 'usuarios', label: 'Usuários' },
  { key: 'perfis', label: 'Perfis' },
]

export function Equipe() {
  const {
    loading, error, tab, situacaoFilter, searchQuery,
    filteredFuncionarios, filteredUsuarios, perfis, permissoes, funcionarios, usuarios,
    setTab, setSituacaoFilter, setSearchQuery, clearError,
    loadFuncionarios, loadUsuarios, loadPerfis, loadPermissoes,
    createFuncionario, updateFuncionario, inativarFuncionario,
    vincularUsuario, desvincularUsuario,
    createUsuario, updateUsuario, resetPassword, revogarAcesso,
    createPerfil, updatePerfilPermissoes,
  } = useEquipe()

  const loadData = useCallback(async () => {
    // Aba Funcionários precisa de perfis (seletores de concessão) e usuários
    // (vincular existente, revogar pelo card) além dos funcionários.
    if (tab === 'funcionarios') await Promise.all([loadFuncionarios(situacaoFilter), loadPerfis(), loadUsuarios()])
    else if (tab === 'usuarios') await loadUsuarios()
    else if (tab === 'perfis') {
      await Promise.all([loadPerfis(), loadPermissoes()])
    }
  }, [tab, situacaoFilter, loadFuncionarios, loadUsuarios, loadPerfis, loadPermissoes])

  useEffect(() => { loadData() }, [loadData])

  const formModal = useModalState<Funcionario | null>(null)
  const concederAcessoModal = useModalState<Funcionario | null>(null)
  const vincularModal = useModalState<Funcionario | null>(null)
  const revogarModal = useModalState<{ funcionario: Funcionario; usuario: User } | null>(null)
  const inativarModal = useModalState<Funcionario | null>(null)
  const perfilModal = useModalState<Perfil | null>(null)

  function handleEditFuncionario(f: Funcionario) {
    formModal.open(f)
  }

  function handleConcederAcesso(f: Funcionario) {
    concederAcessoModal.open(f)
  }

  function handleRevogarAcessoFromCard(f: Funcionario) {
    const u = usuarios.find(u => u.id === f.usuario_id)
    if (u) revogarModal.open({ funcionario: f, usuario: u })
  }

  function handleInativar(f: Funcionario) {
    inativarModal.open(f)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-primaryDeep">Equipe</h1>
          <p className="text-textMuted text-sm">Funcionários, usuários e acessos da instituição</p>
        </div>
        <div className="flex gap-2">
          {(tab === 'funcionarios' || tab === 'usuarios') && (
            <button onClick={() => formModal.open(null)} className="btn-primary">+ Novo funcionário</button>
          )}
          {tab === 'perfis' && (
            <button onClick={() => perfilModal.open(null)} className="btn-primary">+ Novo perfil</button>
          )}
        </div>
      </div>

      <div className="flex gap-1 bg-slate-100 rounded-xl p-1 overflow-x-auto">
        {tabConfig.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 min-w-0 px-2 sm:px-4 py-3 rounded-lg text-[13px] sm:text-sm font-medium transition min-h-[44px] whitespace-nowrap ${
              tab === t.key
                ? 'bg-white text-primary shadow-sm'
                : 'text-textMuted hover:text-textMain'
            }`}
          >
            {t.label}
            {t.key === 'funcionarios' && (
              <span className="ml-1 text-xs opacity-60 hidden min-[420px]:inline">({funcionarios.length})</span>
            )}
            {t.key === 'usuarios' && (
              <span className="ml-1 text-xs opacity-60 hidden min-[420px]:inline">({usuarios.length})</span>
            )}
          </button>
        ))}
      </div>

      <div className="card p-3 space-y-3">
        <input
          className="input"
          placeholder={tab === 'funcionarios' ? 'Buscar por nome, CPF, e-mail ou profissão...' : 'Buscar por nome ou e-mail...'}
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
        {tab === 'funcionarios' && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {situacaoFilters.map(f => (
              <button
                key={f.label}
                onClick={() => setSituacaoFilter(f.value)}
                className={`px-3 py-2 rounded-lg text-xs font-medium whitespace-nowrap transition min-h-[44px] ${
                  situacaoFilter === f.value
                    ? 'bg-primary text-white'
                    : 'bg-slate-100 text-textMuted hover:bg-slate-200'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="card bg-red-50 border-red-200">
          <div className="flex items-start gap-3">
            <span className="text-lg">⚠️</span>
            <div className="flex-1">
              <p className="text-sm text-danger font-medium">{error}</p>
              <button onClick={clearError} className="text-xs text-danger underline mt-1">Dispensar</button>
            </div>
          </div>
        </div>
      )}

      {loading && tab !== 'perfis' && (
        <div className="space-y-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="card animate-pulse">
              <div className="flex gap-3">
                <div className="w-11 h-11 rounded-full bg-slate-200" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-slate-200 rounded w-1/3" />
                  <div className="h-3 bg-slate-100 rounded w-1/2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'funcionarios' && !loading && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {filteredFuncionarios.map(f => (
            <FuncionarioCard
              key={f.id}
              funcionario={f}
              onEdit={handleEditFuncionario}
              onConcederAcesso={handleConcederAcesso}
              onVincular={(func) => vincularModal.open(func)}
              onRevogarAcesso={handleRevogarAcessoFromCard}
              onInativar={handleInativar}
            />
          ))}
          {filteredFuncionarios.length === 0 && (
            <div className="col-span-full card py-16 text-center">
              <span className="text-4xl mb-3 block">👩‍⚕️</span>
              <p className="text-textMuted font-medium">Nenhum funcionário encontrado</p>
              <p className="text-xs text-textMuted mt-1">Cadastre o primeiro funcionário ou ajuste os filtros.</p>
            </div>
          )}
        </div>
      )}

      {tab === 'usuarios' && !loading && (
        <UsuariosSection
          usuarios={usuarios}
          funcionarios={funcionarios}
          perfis={perfis}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          loading={loading}
          onEditUser={async (u) => { await updateUsuario(u.id, { nome: u.nome }) }}
          onResetPassword={resetPassword}
          onRevogarAcesso={(u) => {
            const f = funcionarios.find(f => f.usuario_id === u.id)
            if (f) revogarModal.open({ funcionario: f, usuario: u })
          }}
        />
      )}

      {tab === 'perfis' && !loading && (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {perfis.map(p => (
              <div key={p.id} className="card hover:shadow-cardHover transition min-w-0">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-semibold text-textMain">{p.nome}</div>
                    <div className="text-xs text-textMuted mt-0.5">Chave: {p.chave}</div>
                  </div>
                  <span className={p.situacao === 'ativo' ? 'badge-success' : 'badge-danger'}>
                    {p.situacao === 'ativo' ? 'Ativo' : 'Inativo'}
                  </span>
                </div>
                {p.descricao && (
                  <p className="text-xs text-textMuted mt-2 line-clamp-2">{p.descricao}</p>
                )}
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={() => perfilModal.open(p)}
                    className="text-xs px-3 py-2 rounded-lg border border-slate-200 hover:bg-slate-50 text-textMuted min-h-[44px] min-w-[44px] flex items-center justify-center"
                  >
                    ✏️ Gerenciar
                  </button>
                </div>
              </div>
            ))}
            {perfis.length === 0 && (
              <div className="col-span-full card py-16 text-center">
                <span className="text-4xl mb-3 block">🛡️</span>
                <p className="text-textMuted font-medium">Nenhum perfil encontrado</p>
                <p className="text-xs text-textMuted mt-1">Crie o primeiro perfil institucional.</p>
              </div>
            )}
          </div>

          <div className="card bg-blue-50 border border-blue-100">
            <div className="flex items-start gap-3">
              <span className="text-lg">ℹ️</span>
              <div className="text-xs text-primary space-y-1">
                <p><strong>Perfis</strong> definem o que cada usuário pode fazer no sistema.</p>
                <p>O perfil <code>platform_superuser</code> é exclusivo do escopo global e não pode ser atribuído por administradores ILPI.</p>
                <p>Perfis com escopo <code>ilpi</code> são específicos desta instituição.</p>
              </div>
            </div>
          </div>
        </div>
      )}

      <FuncionarioFormModal
        open={formModal.isOpen}
        onClose={formModal.close}
        funcionario={formModal.data}
        perfis={perfis}
        onSubmit={async (data) => {
          if (formModal.data) {
            const result = await updateFuncionario(formModal.data.id, data)
            return result
          }
          const result = await createFuncionario(data as any)
          return result
        }}
      />

      <ConcederAcessoModal
        open={concederAcessoModal.isOpen}
        onClose={concederAcessoModal.close}
        funcionario={concederAcessoModal.data}
        perfis={perfis}
        onSuccess={() => {
          loadFuncionarios(situacaoFilter)
          loadUsuarios()
        }}
      />

      <VincularUsuarioModal
        open={vincularModal.isOpen}
        onClose={vincularModal.close}
        funcionario={vincularModal.data}
        usuarios={usuarios}
        onConfirm={vincularUsuario}
      />

      <RevogarAcessoModal
        open={revogarModal.isOpen}
        onClose={revogarModal.close}
        funcionario={revogarModal.data?.funcionario || null}
        usuario={revogarModal.data?.usuario || null}
        onConfirm={async (userId) => {
          await revogarAcesso(userId)
          await loadFuncionarios(situacaoFilter)
        }}
      />

      <InativarFuncionarioModal
        open={inativarModal.isOpen}
        onClose={inativarModal.close}
        funcionario={inativarModal.data}
        onConfirm={inativarFuncionario}
      />

      <PerfilFormModal
        open={perfilModal.isOpen}
        onClose={perfilModal.close}
        perfil={perfilModal.data}
        permissoes={permissoes}
        allPerfis={perfis}
        onSubmitPerfil={createPerfil}
        onSubmitPermissoes={updatePerfilPermissoes}
      />
    </div>
  )
}
