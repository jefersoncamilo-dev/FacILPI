import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { listarInstituicoes, LIMITE_LISTAGEM } from '../services/platform'
import { mensagemDeErro, formatDate } from '../services/api'
import { rotuloSituacao, ehAtiva, ehInativa } from '../types/platform'
import type { Instituicao } from '../types/platform'

function Selo({ situacao }: { situacao: string }) {
  const cor = ehAtiva(situacao)
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : ehInativa(situacao)
      ? 'bg-slate-100 text-slate-600 border-slate-200'
      : 'bg-amber-50 text-amber-800 border-amber-200'
  return (
    <span className={`inline-block text-xs font-medium px-2 py-1 rounded-lg border ${cor}`}>
      {rotuloSituacao(situacao)}
    </span>
  )
}

export function PlatformInstituicoes() {
  const [instituicoes, setInstituicoes] = useState<Instituicao[] | null>(null)
  const [erro, setErro] = useState('')
  const [busca, setBusca] = useState('')

  useEffect(() => {
    let ativo = true
    listarInstituicoes()
      .then(dados => {
        if (ativo) setInstituicoes(dados)
      })
      .catch(e => {
        if (ativo) setErro(mensagemDeErro(e, 'Não foi possível carregar as instituições.'))
      })
    return () => {
      ativo = false
    }
  }, [])

  const filtradas = useMemo(() => {
    if (!instituicoes) return []
    const termo = busca.trim().toLowerCase()
    if (!termo) return instituicoes
    return instituicoes.filter(item =>
      [item.razao_social, item.nome_fantasia, item.municipio, item.cnpj]
        .filter(Boolean)
        .some(valor => String(valor).toLowerCase().includes(termo)),
    )
  }, [instituicoes, busca])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold text-primaryDeep">Instituições</h1>
        <Link to="/platform/instituicoes/nova" className="btn-primary ml-auto min-h-[44px] px-4 py-2 text-sm">
          Nova ILPI
        </Link>
      </div>

      <input
        className="input"
        placeholder="Buscar por nome, município ou CNPJ"
        value={busca}
        onChange={e => setBusca(e.target.value)}
        aria-label="Buscar instituições"
      />

      {erro && (
        <div role="alert" className="text-sm p-3 rounded-xl bg-amber-50 text-amber-800 border border-amber-200">
          {erro}
        </div>
      )}

      {!instituicoes && !erro && <p className="text-sm text-textMuted">Carregando instituições...</p>}

      {instituicoes && instituicoes.length === 0 && (
        <div className="card text-center space-y-2">
          <p className="font-medium">Nenhuma instituição cadastrada.</p>
          <p className="text-sm text-textMuted">
            Comece criando a primeira ILPI cliente em <strong>Nova ILPI</strong>.
          </p>
        </div>
      )}

      {instituicoes && instituicoes.length > 0 && filtradas.length === 0 && (
        <p className="text-sm text-textMuted">Nenhuma instituição corresponde à busca.</p>
      )}

      <ul className="space-y-3">
        {filtradas.map(item => (
          <li key={item.id}>
            <Link
              to={`/platform/instituicoes/${item.id}`}
              className="card block hover:border-primary transition-colors"
            >
              <div className="flex flex-wrap items-start gap-2">
                <div className="min-w-0">
                  <div className="font-semibold truncate">
                    {item.nome_fantasia?.trim() || item.razao_social}
                  </div>
                  <div className="text-xs text-textMuted truncate">
                    {[item.municipio, item.uf].filter(Boolean).join(' / ') || 'Localidade não informada'}
                  </div>
                </div>
                <div className="ml-auto text-right shrink-0">
                  <Selo situacao={item.situacao} />
                  <div className="text-xs text-textMuted mt-1">
                    Criada em {formatDate(item.created_at)}
                  </div>
                </div>
              </div>
            </Link>
          </li>
        ))}
      </ul>

      {instituicoes && instituicoes.length >= LIMITE_LISTAGEM && (
        <p className="text-xs text-textMuted">
          Exibindo as {LIMITE_LISTAGEM} instituições mais recentes. A busca acima filtra apenas
          esta lista.
        </p>
      )}
    </div>
  )
}
