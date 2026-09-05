import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import type { Funcionario, FuncionarioCreate, FuncionarioUpdate, Perfil } from '../../types/equipe'
import { UF_VALIDAS, REGULATED_PROFESSIONS } from '../../types/equipe'

interface FuncionarioFormModalProps {
  open: boolean
  onClose: () => void
  funcionario?: Funcionario | null
  perfis?: Perfil[]
  onSubmit: (data: FuncionarioCreate | FuncionarioUpdate) => Promise<{ senha_temporaria?: string | null }>
}

const defaultForm: FuncionarioCreate = {
  nome: '', cpf: '', telefone: '', email: '', cargo: '',
  profissao: '', conselho_profissional: '', numero_conselho: '', uf_conselho: '',
  criar_usuario: false, perfil_id: '',
}

function isRegulated(profissao: string) {
  return REGULATED_PROFESSIONS.includes(profissao.toLowerCase() as typeof REGULATED_PROFESSIONS[number])
}

function formatCPF(v: string) {
  const d = v.replace(/\D/g, '')
  return d.replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d{1,2})$/, '$1-$2')
}

function formatPhone(v: string) {
  const d = v.replace(/\D/g, '')
  if (d.length <= 10) return d.replace(/(\d{2})(\d)/, '($1) $2').replace(/(\d{4})(\d)/, '$1-$2')
  return d.replace(/(\d{2})(\d)/, '($1) $2').replace(/(\d{5})(\d)/, '$1-$2')
}

function formFromFuncionario(funcionario: Funcionario | null | undefined): FuncionarioCreate {
  if (funcionario) {
    return {
      nome: funcionario.nome,
      cpf: funcionario.cpf || '',
      telefone: funcionario.telefone || '',
      email: funcionario.email || '',
      cargo: funcionario.cargo || '',
      profissao: funcionario.profissao || '',
      conselho_profissional: funcionario.conselho_profissional || '',
      numero_conselho: funcionario.numero_conselho || '',
      uf_conselho: funcionario.uf_conselho || '',
    }
  }
  return { ...defaultForm }
}

export function FuncionarioFormModal({ open, onClose, funcionario, perfis = [], onSubmit }: FuncionarioFormModalProps) {
  const isEdit = !!funcionario
  const [form, setForm] = useState<FuncionarioCreate>(() => formFromFuncionario(funcionario))
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [senhaTemp, setSenhaTemp] = useState<string | null>(null)

  // O componente permanece montado com o modal fechado; sincroniza o
  // formulário a cada abertura (criação x edição de funcionários distintos).
  useEffect(() => {
    if (open) {
      setForm(formFromFuncionario(funcionario))
      setMsg('')
      setSenhaTemp(null)
    }
  }, [open, funcionario])

  const showConselho = isRegulated(form.profissao || '') ||
    !!(form.conselho_profissional || form.numero_conselho || form.uf_conselho)

  function update<K extends keyof FuncionarioCreate>(key: K, value: FuncionarioCreate[K]) {
    const next = { ...form, [key]: value }
    if (key === 'profissao' && !isRegulated(value as string)) {
      next.conselho_profissional = ''
      next.numero_conselho = ''
      next.uf_conselho = ''
    }
    if (key === 'cpf') next.cpf = formatCPF(value as string)
    if (key === 'telefone') next.telefone = formatPhone(value as string)
    setForm(next)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setMsg('')
    setSaving(true)
    try {
      const payload: any = { ...form }
      if (payload.cpf) payload.cpf = payload.cpf.replace(/\D/g, '')
      if (!payload.cpf) delete payload.cpf
      if (!payload.telefone) delete payload.telefone
      if (!payload.email) delete payload.email
      if (!payload.cargo) delete payload.cargo
      if (!payload.profissao) delete payload.profissao
      if (!payload.conselho_profissional) delete payload.conselho_profissional
      if (!payload.numero_conselho) delete payload.numero_conselho
      if (!payload.uf_conselho) delete payload.uf_conselho
      if (isEdit) {
        delete payload.criar_usuario
        delete payload.perfil_id
      } else {
        if (!payload.criar_usuario) {
          delete payload.perfil_id
        }
      }
      const result = await onSubmit(payload)
      if (result?.senha_temporaria) {
        setSenhaTemp(result.senha_temporaria)
      } else {
        handleClose()
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao salvar')
    } finally {
      setSaving(false)
    }
  }

  function handleClose() {
    setForm(isEdit ? {
      nome: funcionario!.nome, cpf: funcionario!.cpf || '', telefone: funcionario!.telefone || '',
      email: funcionario!.email || '', cargo: funcionario!.cargo || '', profissao: funcionario!.profissao || '',
      conselho_profissional: funcionario!.conselho_profissional || '', numero_conselho: funcionario!.numero_conselho || '',
      uf_conselho: funcionario!.uf_conselho || '',
    } : { ...defaultForm })
    setMsg('')
    setSenhaTemp(null)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title={isEdit ? 'Editar funcionário' : 'Novo funcionário'}>
      {senhaTemp ? (
        <div className="space-y-4">
          <div className="text-center">
            <div className="w-14 h-14 rounded-full bg-emerald-50 flex items-center justify-center mx-auto mb-3">
              <span className="text-2xl">✅</span>
            </div>
            <h4 className="font-semibold text-textMain">Funcionário criado com acesso</h4>
            <p className="text-sm text-textMuted mt-1">Senha temporária para o novo usuário:</p>
          </div>
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
            <label className="text-xs text-textMuted font-medium">Senha temporária</label>
            <div className="mt-1 p-3 bg-white rounded-lg border border-slate-200 font-mono text-sm break-all select-all">
              {senhaTemp}
            </div>
          </div>
          <p className="text-xs text-textMuted text-center">
            O usuário deverá alterar esta senha no primeiro acesso.
            <br />Anote ou copie — esta senha não será exibida novamente.
          </p>
          <button onClick={handleClose} className="btn-primary w-full">Fechar</button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs text-textMuted font-medium">Nome completo *</label>
            <input className="input mt-1" value={form.nome} onChange={e => update('nome', e.target.value)} required minLength={2} maxLength={255} />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-textMuted font-medium">CPF</label>
              <input className="input mt-1" value={form.cpf || ''} onChange={e => update('cpf', e.target.value)} placeholder="000.000.000-00" maxLength={14} />
            </div>
            <div>
              <label className="text-xs text-textMuted font-medium">Telefone</label>
              <input className="input mt-1" value={form.telefone || ''} onChange={e => update('telefone', e.target.value)} placeholder="(00) 00000-0000" maxLength={20} />
            </div>
          </div>

          <div>
            <label className="text-xs text-textMuted font-medium">E-mail</label>
            <input className="input mt-1" type="email" value={form.email || ''} onChange={e => update('email', e.target.value)} placeholder="email@exemplo.com" />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-textMuted font-medium">Cargo</label>
              <input className="input mt-1" value={form.cargo || ''} onChange={e => update('cargo', e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-textMuted font-medium">Profissão</label>
              <input className="input mt-1" value={form.profissao || ''} onChange={e => update('profissao', e.target.value)} placeholder="Ex: Enfermeiro, Técnico..." />
            </div>
          </div>

          {showConselho && (
            <div className="p-3 rounded-xl bg-blue-50 border border-blue-100 space-y-3">
              <p className="text-xs text-primary font-medium">📋 Dados do conselho profissional (obrigatórios)</p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-textMuted font-medium">Conselho *</label>
                  <input className="input mt-1" value={form.conselho_profissional || ''} onChange={e => update('conselho_profissional', e.target.value)} placeholder="Ex: COREN" required />
                </div>
                <div>
                  <label className="text-xs text-textMuted font-medium">Nº Registro *</label>
                  <input className="input mt-1" value={form.numero_conselho || ''} onChange={e => update('numero_conselho', e.target.value)} required />
                </div>
                <div>
                  <label className="text-xs text-textMuted font-medium">UF *</label>
                  <select className="input mt-1" value={form.uf_conselho || ''} onChange={e => update('uf_conselho', e.target.value)} required>
                    <option value="">UF</option>
                    {UF_VALIDAS.map(uf => <option key={uf} value={uf}>{uf}</option>)}
                  </select>
                </div>
              </div>
            </div>
          )}

          {!isEdit && (
            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200">
              <label className="flex items-start gap-3 cursor-pointer min-h-[44px]">
                <input
                  type="checkbox"
                  checked={!!form.criar_usuario}
                  onChange={e => update('criar_usuario', e.target.checked)}
                  className="mt-1 w-5 h-5 rounded border-slate-300 text-primary focus:ring-primary"
                />
                <div>
                  <span className="font-medium text-sm text-textMain">Criar usuário com acesso ao sistema</span>
                  <p className="text-xs text-textMuted mt-0.5">Uma senha temporária será gerada automaticamente.</p>
                </div>
              </label>
              {form.criar_usuario && perfis.length > 0 && (
                <div className="mt-3">
                  <label className="text-xs text-textMuted font-medium">Perfil de acesso</label>
                  <select className="input mt-1" value={form.perfil_id || ''} onChange={e => update('perfil_id', e.target.value)}>
                    <option value="">Selecione o perfil</option>
                    {perfis.filter(p => p.situacao === 'ativo').map(p => (
                      <option key={p.id} value={p.id}>{p.nome}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}

          {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}

          <div className="flex gap-3">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancelar</button>
            <button type="submit" className="btn-primary flex-1" disabled={saving}>
              {saving ? 'Salvando...' : isEdit ? 'Salvar alterações' : 'Cadastrar'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
