import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import type { Perfil, PerfilAdminCreate, Permissao } from '../../types/equipe'

interface PerfilFormModalProps {
  open: boolean
  onClose: () => void
  perfil?: Perfil | null
  permissoes: Permissao[]
  allPerfis: Perfil[]
  onSubmitPerfil: (data: PerfilAdminCreate) => Promise<Perfil>
  onSubmitPermissoes: (perfilId: string, permissoes: string[]) => Promise<void>
}

export function PerfilFormModal({ open, onClose, perfil, permissoes, allPerfis, onSubmitPerfil, onSubmitPermissoes }: PerfilFormModalProps) {
  const [form, setForm] = useState<{ nome: string; chave: string; descricao: string }>(() => {
    if (perfil) return { nome: perfil.nome, chave: perfil.chave, descricao: perfil.descricao || '' }
    return { nome: '', chave: '', descricao: '' }
  })
  const [selectedPermissoes, setSelectedPermissoes] = useState<Set<string>>(() => {
    if (perfil) {
      return new Set(
        permissoes
          .filter(p => !p.chave.includes('*'))
          .map(p => p.chave)
      )
    }
    return new Set()
  })
  const [isEditingPermissoes, setIsEditingPermissoes] = useState(false)
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [createdPerfil, setCreatedPerfil] = useState<Perfil | null>(perfil || null)

  // O componente permanece montado com o modal fechado; sincroniza os
  // dados exibidos a cada abertura (novo perfil x gerenciar perfil distinto).
  useEffect(() => {
    if (open) {
      setForm(perfil ? { nome: perfil.nome, chave: perfil.chave, descricao: perfil.descricao || '' } : { nome: '', chave: '', descricao: '' })
      setSelectedPermissoes(perfil ? new Set(permissoes.filter(p => !p.chave.includes('*')).map(p => p.chave)) : new Set())
      setMsg('')
      setCreatedPerfil(perfil || null)
      setIsEditingPermissoes(false)
    }
  }, [open, perfil, permissoes])

  const permissoesAgrupadas = permissoes
    .filter(p => !p.chave.includes('*'))
    .reduce<Record<string, Permissao[]>>((acc, p) => {
      if (!acc[p.modulo]) acc[p.modulo] = []
      acc[p.modulo].push(p)
      return acc
    }, {})

  function togglePermissao(chave: string) {
    setSelectedPermissoes(prev => {
      const next = new Set(prev)
      if (next.has(chave)) next.delete(chave)
      else next.add(chave)
      return next
    })
  }

  function handleClose() {
    setForm(perfil ? { nome: perfil.nome, chave: perfil.chave, descricao: perfil.descricao || '' } : { nome: '', chave: '', descricao: '' })
    setSelectedPermissoes(perfil ? new Set(permissoes.filter(p => !p.chave.includes('*')).map(p => p.chave)) : new Set())
    setMsg('')
    setCreatedPerfil(perfil || null)
    setIsEditingPermissoes(false)
    onClose()
  }

  async function handleCreatePerfil(e: React.FormEvent) {
    e.preventDefault()
    setMsg('')
    setSaving(true)
    try {
      const created = await onSubmitPerfil(form)
      setCreatedPerfil(created)
      setIsEditingPermissoes(true)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao criar perfil')
    } finally {
      setSaving(false)
    }
  }

  async function handleSavePermissoes() {
    if (!createdPerfil) return
    setMsg('')
    setSaving(true)
    try {
      await onSubmitPermissoes(createdPerfil.id, Array.from(selectedPermissoes))
      handleClose()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao salvar permissões')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title={perfil ? 'Editar perfil' : 'Novo perfil'}>
      {!isEditingPermissoes && !createdPerfil ? (
        <form onSubmit={handleCreatePerfil} className="space-y-4">
          <div>
            <label className="text-xs text-textMuted font-medium">Nome do perfil *</label>
            <input className="input mt-1" value={form.nome} onChange={e => setForm({ ...form, nome: e.target.value })} required minLength={2} maxLength={100} placeholder="Ex: Enfermeiro Chefe" />
          </div>
          <div>
            <label className="text-xs text-textMuted font-medium">Chave identificadora *</label>
            <input className="input mt-1" value={form.chave} onChange={e => setForm({ ...form, chave: e.target.value })} required minLength={2} maxLength={100} placeholder="Ex: enfermeiro_chefe" />
            <p className="text-xs text-textMuted mt-1">Identificador único do perfil nesta ILPI</p>
          </div>
          <div>
            <label className="text-xs text-textMuted font-medium">Descrição</label>
            <textarea className="input mt-1 min-h-[80px] resize-y" value={form.descricao} onChange={e => setForm({ ...form, descricao: e.target.value })} placeholder="Descreva as responsabilidades deste perfil..." />
          </div>

          <div className="p-3 rounded-xl bg-blue-50 border border-blue-100">
            <p className="text-xs text-primary">
              <strong>Nota:</strong> O perfil <code>platform_superuser</code> não pode ser criado por administradores ILPI. Apenas perfis com escopo institucional são permitidos.
            </p>
          </div>

          {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}

          <div className="flex gap-3">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancelar</button>
            <button type="submit" className="btn-primary flex-1" disabled={saving}>
              {saving ? 'Criando...' : 'Criar perfil'}
            </button>
          </div>
        </form>
      ) : (
        <div className="space-y-4">
          <div className="p-3 rounded-xl bg-slate-50 border border-slate-200">
            <p className="text-xs text-textMuted">Perfil:</p>
            <p className="text-sm font-semibold text-textMain">{createdPerfil?.nome}</p>
            <p className="text-xs text-textMuted">Chave: {createdPerfil?.chave}</p>
          </div>

          <div>
            <h4 className="text-sm font-semibold text-textMain mb-2">Permissões do perfil</h4>
            <p className="text-xs text-textMuted mb-3">
              Selecione as permissões que este perfil poderá utilizar. Apenas permissões compatíveis com escopo institucional estão disponíveis.
            </p>

            <div className="space-y-3 max-h-[50vh] overflow-auto pr-1">
              {Object.entries(permissoesAgrupadas).map(([modulo, lista]) => (
                <div key={modulo} className="border border-slate-200 rounded-xl overflow-hidden">
                  <div className="px-3 py-2 bg-slate-50 border-b border-slate-200">
                    <span className="text-xs font-semibold text-textMain capitalize">{modulo.replace(/_/g, ' ')}</span>
                  </div>
                  <div className="p-2 space-y-1">
                    {lista.map(p => (
                      <label
                        key={p.chave}
                        className="flex items-center gap-2 p-2 rounded-lg hover:bg-slate-50 cursor-pointer min-h-[44px]"
                      >
                        <input
                          type="checkbox"
                          checked={selectedPermissoes.has(p.chave)}
                          onChange={() => togglePermissao(p.chave)}
                          className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary"
                        />
                        <div className="min-w-0">
                          <span className="text-sm text-textMain">{p.acao.replace(/_/g, ' ')}</span>
                          {p.descricao && (
                            <span className="text-xs text-textMuted ml-2">— {p.descricao}</span>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}

          <div className="flex gap-3">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancelar</button>
            <button onClick={handleSavePermissoes} className="btn-primary flex-1" disabled={saving}>
              {saving ? 'Salvando...' : 'Salvar permissões'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
