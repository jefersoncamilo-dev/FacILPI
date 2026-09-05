import { useState } from 'react'
import type { Funcionario } from '../../types/equipe'

interface FuncionarioCardProps {
  funcionario: Funcionario
  perfilNome?: string
  onEdit: (f: Funcionario) => void
  onConcederAcesso: (f: Funcionario) => void
  onVincular: (f: Funcionario) => void
  onRevogarAcesso: (f: Funcionario) => void
  onInativar: (f: Funcionario) => void
}

const situacaoBadge: Record<string, string> = {
  ativo: 'badge-success',
  afastado: 'badge-warning',
  inativo: 'badge-danger',
}

const situacaoLabel: Record<string, string> = {
  ativo: 'Ativo',
  afastado: 'Afastado',
  inativo: 'Inativo',
}

export function FuncionarioCard({ funcionario, perfilNome, onEdit, onConcederAcesso, onVincular, onRevogarAcesso, onInativar }: FuncionarioCardProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const temAcesso = !!funcionario.usuario_id

  return (
    <div className="card hover:shadow-cardHover transition min-w-0">
      <div className="flex items-start gap-3">
        <div className="w-11 h-11 rounded-full bg-primaryLight flex items-center justify-center font-bold text-primary text-base shrink-0">
          {funcionario.nome[0]?.toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-textMain truncate">{funcionario.nome}</div>
          <div className="text-xs text-textMuted mt-0.5">
            {funcionario.profissao || funcionario.cargo || 'Sem função definida'}
          </div>
        </div>
        <div className="relative shrink-0">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="w-10 h-10 rounded-full hover:bg-slate-100 flex items-center justify-center text-textMuted"
            aria-label="Ações"
          >
            ⋮
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-full mt-1 bg-white rounded-xl shadow-lg border border-slate-100 py-1 z-50 min-w-[180px]">
                <button
                  className="w-full text-left px-4 py-3 text-sm hover:bg-slate-50 flex items-center gap-2 min-h-[44px]"
                  onClick={() => { setMenuOpen(false); onEdit(funcionario) }}
                >
                  <span className="text-textMuted">✏️</span> Editar
                </button>
                {!temAcesso && funcionario.situacao === 'ativo' && (
                  <button
                    className="w-full text-left px-4 py-3 text-sm hover:bg-slate-50 flex items-center gap-2 min-h-[44px] text-primary"
                    onClick={() => { setMenuOpen(false); onConcederAcesso(funcionario) }}
                  >
                    <span>🔑</span> Conceder acesso
                  </button>
                )}
                {!temAcesso && funcionario.situacao === 'ativo' && (
                  <button
                    className="w-full text-left px-4 py-3 text-sm hover:bg-slate-50 flex items-center gap-2 min-h-[44px] text-primary"
                    onClick={() => { setMenuOpen(false); onVincular(funcionario) }}
                  >
                    <span>🔗</span> Vincular usuário existente
                  </button>
                )}
                {temAcesso && (
                  <button
                    className="w-full text-left px-4 py-3 text-sm hover:bg-slate-50 flex items-center gap-2 min-h-[44px] text-danger"
                    onClick={() => { setMenuOpen(false); onRevogarAcesso(funcionario) }}
                  >
                    <span>🚫</span> Revogar acesso
                  </button>
                )}
                {funcionario.situacao !== 'inativo' && (
                  <button
                    className="w-full text-left px-4 py-3 text-sm hover:bg-slate-50 flex items-center gap-2 min-h-[44px] text-danger"
                    onClick={() => { setMenuOpen(false); onInativar(funcionario) }}
                  >
                    <span>👁️‍🗨️</span> Inativar funcionário
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <span className={situacaoBadge[funcionario.situacao] || 'badge-warning'}>
          {situacaoLabel[funcionario.situacao] || funcionario.situacao}
        </span>
        {temAcesso ? (
          <span className="badge-success">Acesso: {perfilNome || 'Ativo'}</span>
        ) : (
          <span className="px-2.5 py-1 rounded-full text-xs font-semibold inline-flex items-center gap-1 bg-slate-50 text-textMuted border border-slate-200">
            Sem acesso ao sistema
          </span>
        )}
      </div>

      {(funcionario.cpf || funcionario.telefone || funcionario.email || funcionario.conselho_profissional) && (
        <div className="mt-3 text-xs text-textMuted space-y-1">
          {funcionario.cpf && <div>CPF: {funcionario.cpf}</div>}
          {funcionario.email && <div>E-mail: {funcionario.email}</div>}
          {funcionario.telefone && <div>Tel: {funcionario.telefone}</div>}
          {funcionario.conselho_profissional && (
            <div>{funcionario.conselho_profissional}: {funcionario.numero_conselho}/{funcionario.uf_conselho}</div>
          )}
        </div>
      )}
    </div>
  )
}
