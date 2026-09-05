import { useState } from 'react'
import { Modal } from '../Modal'
import type { Funcionario, Perfil } from '../../types/equipe'
import { equipeApi } from '../../services/equipe'

interface ConcederAcessoModalProps {
  open: boolean
  onClose: () => void
  funcionario: Funcionario | null
  perfis: Perfil[]
  onSuccess: (senhaTemporaria: string) => void
}

export function ConcederAcessoModal({ open, onClose, funcionario, perfis, onSuccess }: ConcederAcessoModalProps) {
  const [perfilId, setPerfilId] = useState('')
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [senhaTemp, setSenhaTemp] = useState<string | null>(null)

  function handleClose() {
    setPerfilId('')
    setMsg('')
    setSenhaTemp(null)
    onClose()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!funcionario) return
    setMsg('')
    setSaving(true)
    try {
      const email = funcionario.email || `${funcionario.nome.toLowerCase().replace(/\s+/g, '.')}@temp.com`
      const { data: created } = await equipeApi.createUsuario({
        nome: funcionario.nome,
        email,
        perfil_id: perfilId || undefined,
      })
      await equipeApi.vincularUsuario(funcionario.id, created.id)
      if (created.senha_temporaria) {
        setSenhaTemp(created.senha_temporaria)
        onSuccess(created.senha_temporaria)
      } else {
        handleClose()
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : detail?.message || 'Erro ao conceder acesso')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Conceder acesso ao sistema">
      {senhaTemp ? (
        <div className="space-y-4">
          <div className="text-center">
            <div className="w-14 h-14 rounded-full bg-emerald-50 flex items-center justify-center mx-auto mb-3">
              <span className="text-2xl">✅</span>
            </div>
            <h4 className="font-semibold text-textMain">Acesso concedido</h4>
            <p className="text-sm text-textMuted mt-1">Senha temporária para {funcionario?.nome}:</p>
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
          <div className="p-3 rounded-xl bg-blue-50 border border-blue-100">
            <p className="text-sm text-primary font-medium">Conceder acesso para:</p>
            <p className="text-sm text-textMain font-semibold mt-1">{funcionario?.nome}</p>
            {funcionario?.email && <p className="text-xs text-textMuted mt-0.5">{funcionario.email}</p>}
          </div>

          <div>
            <label className="text-xs text-textMuted font-medium">Perfil de acesso</label>
            <select className="input mt-1" value={perfilId} onChange={e => setPerfilId(e.target.value)}>
              <option value="">Selecione o perfil</option>
              {perfis.filter(p => p.situacao === 'ativo').map(p => (
                <option key={p.id} value={p.id}>{p.nome}</option>
              ))}
            </select>
          </div>

          <p className="text-xs text-textMuted">
            Uma senha temporária será gerada e exibida após a criação. O usuário deverá alterá-la no primeiro acesso.
          </p>

          {msg && <div className="text-sm text-danger bg-red-50 border border-red-200 p-3 rounded-xl">{msg}</div>}

          <div className="flex gap-3">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancelar</button>
            <button type="submit" className="btn-primary flex-1" disabled={saving}>
              {saving ? 'Concedendo...' : 'Conceder acesso'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
