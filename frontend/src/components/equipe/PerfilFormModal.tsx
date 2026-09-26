import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import { Alert } from '../ui/feedback'
import { equipeApi } from '../../services/equipe'
import type { Perfil, PerfilAdminCreate, PerfilPermissoes, Permissao } from '../../types/equipe'
import { rotuloAcao, rotuloModulo } from '../../lib/rotulos'

interface PerfilFormModalProps {
  open: boolean
  onClose: () => void
  perfil?: Perfil | null
  permissoes: Permissao[]
  allPerfis: Perfil[]
  onSubmitPerfil: (data: PerfilAdminCreate) => Promise<Perfil>
  onSubmitPermissoes: (perfilId: string, permissoes: string[]) => Promise<void>
  /** Sem `perfis:atribuir_permissao`, o perfil existente abre só para leitura. */
  somenteLeitura?: boolean
}

/**
 * Permissões atuais do perfil (UX-10 / #98). Antes a tela partia de "tudo
 * marcado" e o PUT, que substitui a lista inteira, concedia o que a pessoa não
 * desmarcou. Agora: perfil novo começa vazio; perfil existente parte do que o
 * backend diz que ele tem, e sem essa leitura não há edição.
 */
type Atuais =
  | { status: 'novo' }
  | { status: 'carregando' }
  | { status: 'erro' }
  | { status: 'ok'; dados: PerfilPermissoes }

export function PerfilFormModal({ open, onClose, perfil, permissoes, onSubmitPerfil, onSubmitPermissoes, somenteLeitura = false }: PerfilFormModalProps) {
  const [form, setForm] = useState<{ nome: string; chave: string; descricao: string }>(() => {
    if (perfil) return { nome: perfil.nome, chave: perfil.chave, descricao: perfil.descricao || '' }
    return { nome: '', chave: '', descricao: '' }
  })
  const [selectedPermissoes, setSelectedPermissoes] = useState<Set<string>>(() => new Set())
  const [atuais, setAtuais] = useState<Atuais>({ status: 'novo' })
  const [isEditingPermissoes, setIsEditingPermissoes] = useState(false)
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [createdPerfil, setCreatedPerfil] = useState<Perfil | null>(perfil || null)

  // O componente permanece montado com o modal fechado; sincroniza os
  // dados exibidos a cada abertura (novo perfil x gerenciar perfil distinto).
  useEffect(() => {
    if (!open) return
    setForm(perfil ? { nome: perfil.nome, chave: perfil.chave, descricao: perfil.descricao || '' } : { nome: '', chave: '', descricao: '' })
    setSelectedPermissoes(new Set())
    setMsg('')
    setCreatedPerfil(perfil || null)
    setIsEditingPermissoes(false)
    if (!perfil) { setAtuais({ status: 'novo' }); return }
    let vigente = true
    setAtuais({ status: 'carregando' })
    equipeApi.getPermissoesPerfil(perfil.id)
      .then(({ data }) => {
        if (!vigente) return
        setAtuais({ status: 'ok', dados: data })
        setSelectedPermissoes(new Set(data.permissoes.map(p => p.chave)))
      })
      .catch(() => { if (vigente) setAtuais({ status: 'erro' }) })
    return () => { vigente = false }
  }, [open, perfil])

  const permissoesAgrupadas = permissoes
    .filter(p => !p.chave.includes('*'))
    .reduce<Record<string, Permissao[]>>((acc, p) => {
      if (!acc[p.modulo]) acc[p.modulo] = []
      acc[p.modulo].push(p)
      return acc
    }, {})

  const originais = atuais.status === 'ok' ? new Set(atuais.dados.permissoes.map(p => p.chave)) : new Set<string>()
  const adicionadas = [...selectedPermissoes].filter(c => !originais.has(c))
  const removidas = [...originais].filter(c => !selectedPermissoes.has(c))
  // Perfil novo: edita a partir do vazio. Existente: só com a leitura em mãos,
  // com permissão para atribuir e sem permissão fora do catálogo local (que o
  // PUT apagaria).
  const podeEditar = atuais.status === 'novo' || (atuais.status === 'ok' && atuais.dados.editavel && !somenteLeitura)

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
    setSelectedPermissoes(new Set())
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
    if (!createdPerfil || !podeEditar) return
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

  const semMudanca = atuais.status === 'ok' && adicionadas.length === 0 && removidas.length === 0

  return (
    <Modal open={open} onClose={handleClose} title={perfil ? (podeEditar ? 'Editar perfil' : 'Permissões do perfil') : 'Novo perfil'}>
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

            {atuais.status === 'carregando' && <p className="text-sm text-textMuted" role="status">Carregando as permissões atuais…</p>}
            {atuais.status === 'erro' && (
              <Alert variant="error" title="Não foi possível carregar as permissões atuais">
                Para não alterar o perfil sem saber o que ele tem hoje, a edição fica indisponível. Tente abrir novamente.
              </Alert>
            )}
            {atuais.status === 'ok' && !podeEditar && (
              <div className="space-y-3">
                {!atuais.dados.editavel && (
                  <Alert variant="warning" title="Edição indisponível nesta tela">
                    Este perfil tem permissões de módulos que não são geridos aqui ({[...new Set(atuais.dados.permissoes.filter(p => !p.editavel).map(p => rotuloModulo(p.modulo)))].join(', ')}). Salvar por esta tela as removeria.
                  </Alert>
                )}
                <ListaSomenteLeitura dados={atuais.dados} />
              </div>
            )}

            {podeEditar && (
              <>
                <p className="text-xs text-textMuted mb-3">
                  {atuais.status === 'ok' ? 'Marcadas: o que este perfil pode fazer hoje. ' : 'Selecione as permissões que este perfil poderá utilizar. '}
                  Apenas permissões compatíveis com escopo institucional estão disponíveis.
                </p>
                <div className="space-y-3 max-h-[50vh] overflow-auto pr-1">
                  {Object.entries(permissoesAgrupadas).map(([modulo, lista]) => (
                    <div key={modulo} className="border border-slate-200 rounded-xl overflow-hidden">
                      <div className="px-3 py-2 bg-slate-50 border-b border-slate-200">
                        <span className="text-xs font-semibold text-textMain">{rotuloModulo(modulo)}</span>
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
                              <span className="text-sm text-textMain">{rotuloAcao(p.acao)}</span>
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
              </>
            )}
          </div>

          {podeEditar && atuais.status === 'ok' && !semMudanca && (
            <p className="text-xs text-textMain" role="status">
              Ao salvar: {adicionadas.length > 0 && <strong className="text-emerald-800">+{adicionadas.length} concedida(s)</strong>}
              {adicionadas.length > 0 && removidas.length > 0 && ' · '}
              {removidas.length > 0 && <strong className="text-red-700">−{removidas.length} retirada(s)</strong>}
            </p>
          )}

          {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}

          <div className="flex gap-3">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">{podeEditar ? 'Cancelar' : 'Fechar'}</button>
            {podeEditar && (
              <button onClick={handleSavePermissoes} className="btn-primary flex-1" disabled={saving || semMudanca}>
                {saving ? 'Salvando...' : 'Salvar permissões'}
              </button>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

/** O que o perfil pode fazer, agrupado por módulo, sem controles de edição. */
export function ListaSomenteLeitura({ dados }: { dados: PerfilPermissoes }) {
  if (dados.permissoes.length === 0) return <p className="text-sm text-textMuted">Este perfil ainda não tem nenhuma permissão.</p>
  const grupos = dados.permissoes.reduce<Record<string, PerfilPermissoes['permissoes']>>((acc, p) => {
    (acc[p.modulo] ||= []).push(p)
    return acc
  }, {})
  return (
    <dl className="space-y-2">
      {Object.entries(grupos).map(([modulo, itens]) => (
        <div key={modulo} className="rounded-lg border border-slate-200 px-3 py-2">
          <dt className="text-xs font-semibold text-textMain">{rotuloModulo(modulo)}</dt>
          <dd className="mt-1 flex flex-wrap gap-1.5">
            {itens.map(p => (
              <span key={p.chave} title={p.descricao || undefined} className="rounded-full bg-slate-100 px-2 py-1 text-xs text-textMain">{rotuloAcao(p.acao)}</span>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  )
}
