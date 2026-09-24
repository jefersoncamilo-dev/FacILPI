import { useEffect, useState } from 'react'
import { api, formatDate } from '../services/api'
import { Link } from 'react-router-dom'
import { getPlantao, type PlantaoItem } from '../services/plantao'

// Indisponível não é zero. Enquanto a fonte falhar — ou não existir — o cartão
// mostra este traço; exibir 0 afirmaria que não há pendência nenhuma.
const INDISPONIVEL = '—'

// Teto padrão de GET /residentes/ (limit=100 na factory, main.py). Ao atingi-lo a
// tela não sabe o total — mostra "100+" em vez de afirmar exatamente 100.
const LIMITE_LISTAGEM = 100

type Stats = { residentes: number }

export function Dashboard() {
  const [stats, setStats] = useState<Stats>({ residentes: 0 })
  const [residentes, setResidentes] = useState<any[]>([])
  // PH-01: o `.catch(() => ({ data: [] }))` anterior transformava 403 e falha de
  // rede em "0 residentes" e "Ocupação 0%" — os mesmos números que uma ILPI
  // recém-criada mostra legitimamente. A indisponibilidade passa a ser explícita,
  // como já era para pendências e alertas.
  const [residentesIndisponiveis, setResidentesIndisponiveis] = useState(false)
  const [pendencias, setPendencias] = useState<PlantaoItem[]>([])
  const [pendenciasIndisponiveis, setPendenciasIndisponiveis] = useState(false)

  useEffect(() => {
    api.get('/residentes/')
      .then(r => {
        const lista = r.data || []
        setResidentes(lista.slice(0, 5))
        // Zero aqui é resultado legítimo: a consulta respondeu com lista vazia.
        // PH02-03 (#71): sem "Ocupação". O cálculo dividia pela constante 40, que
        // não é a capacidade da ILPI — e residente cadastrado não é leito ocupado.
        setStats({ residentes: lista.length })
        setResidentesIndisponiveis(false)
      })
      .catch(() => {
        setResidentes([])
        setStats({ residentes: 0 })
        setResidentesIndisponiveis(true)
      })
  }, [])

  useEffect(() => {
    // Fonte oficial das pendências do turno é a projeção /plantao/, a mesma
    // consumida por Meu Plantão. Falha marca indisponibilidade explícita.
    getPlantao()
      .then(itens => { setPendencias(itens); setPendenciasIndisponiveis(false) })
      .catch(() => { setPendencias([]); setPendenciasIndisponiveis(true) })
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-primaryDeep">Início</h1>
        <p className="text-textMuted">Visão geral da ILPI — {formatDate(new Date().toISOString())}</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* PH02-03 (#71): "cadastrados", não "ativos" — o número é o total
            existente, e o domínio ainda não tem estado ativo/inativo governado. */}
        <div className="card bg-gradient-to-br from-primary to-primaryDeep text-white border-0">
          <div className="text-sm opacity-90">Residentes cadastrados</div>
          <div className="text-3xl font-bold mt-1">
            {residentesIndisponiveis
              ? INDISPONIVEL
              : stats.residentes >= LIMITE_LISTAGEM ? `${LIMITE_LISTAGEM}+` : stats.residentes}
          </div>
          {residentesIndisponiveis && (
            <div className="text-xs opacity-80 mt-2">Indisponível no momento</div>
          )}
        </div>
        <div className="card">
          <div className="text-sm text-textMuted">Pendências do turno</div>
          <div className="text-3xl font-bold text-warning mt-1">
            {pendenciasIndisponiveis ? INDISPONIVEL : pendencias.length}
          </div>
          {pendenciasIndisponiveis
            ? <span className="text-xs text-textMuted mt-2 inline-block">Indisponível no momento</span>
            : <Link to="/plantao" className="text-xs text-primary font-semibold mt-2 inline-block">Ver Meu Plantão →</Link>}
        </div>
        <div className="card">
          <div className="text-sm text-textMuted">Alertas ativos</div>
          <div className="text-3xl font-bold text-danger mt-1">{INDISPONIVEL}</div>
          <span className="text-xs text-textMuted mt-2 inline-block">Indisponível — sem fonte oficial</span>
        </div>
        {/* PH02-03 (#71): antes "✅ Em dia — Licenças verificadas" fixo no código,
            inclusive para ILPI em configuração e sem rede. Não existe fonte de
            conformidade no sistema; afirmar "em dia" seria fabricar um fato
            regulatório. Mesma convenção do cartão de Alertas. */}
        <div className="card">
          <div className="text-sm text-textMuted">Conformidade</div>
          <div className="text-3xl font-bold text-textMuted mt-1">{INDISPONIVEL}</div>
          <span className="text-xs text-textMuted mt-2 inline-block">Não avaliada — sem fonte oficial</span>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Residentes recentes</h3>
            <Link to="/residentes" className="text-sm text-primary font-semibold">Ver todos</Link>
          </div>
          {residentesIndisponiveis ? (
            <div className="py-10 text-center text-textMuted" role="alert">
              <div className="text-4xl mb-2" aria-hidden="true">⚠️</div>
              <p className="text-sm">Não foi possível carregar os residentes</p>
              <p className="text-xs mt-1">Isso não significa que não há residentes cadastrados.</p>
            </div>
          ) : residentes.length === 0 ? (
            <div className="py-10 text-center text-textMuted">
              <div className="text-4xl mb-2">👥</div>
              <p className="text-sm">Nenhum residente cadastrado</p>
              <Link to="/residentes" className="btn-primary mt-4 inline-flex">Cadastrar residente</Link>
            </div>
          ) : (
            <div className="space-y-3">
              {residentes.map(r => (
                <div key={r.id} className="flex items-center gap-3 p-3 rounded-xl hover:bg-slate-50 border border-transparent hover:border-slate-100">
                  <div className="w-10 h-10 rounded-full bg-primaryLight flex items-center justify-center font-bold text-primary">{r.nome[0]}</div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{r.nome}</div>
                    <div className="text-xs text-textMuted truncate">{r.situacao} • {r.grau_dependencia || 'Sem grau'}</div>
                  </div>
                  {/* PH02-03 (#71): sem selo "Ativo" fixo. A situação real já
                      aparece na linha acima; o selo afirmava "Ativo" até para
                      residente em admissão. */}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Próximas pendências</h3>
            <Link to="/plantao" className="text-sm text-primary font-semibold">Meu Plantão</Link>
          </div>
          {pendenciasIndisponiveis ? (
            <div className="py-10 text-center text-textMuted" role="alert">
              <div className="text-4xl mb-2">⚠️</div>
              <p className="text-sm">Não foi possível carregar as pendências</p>
              <p className="text-xs mt-1">Isso não significa que não há pendências.</p>
            </div>
          ) : pendencias.length === 0 ? (
            <div className="py-10 text-center text-textMuted">
              <div className="text-4xl mb-2">🩺</div>
              <p className="text-sm">Nenhuma pendência no período</p>
              <p className="text-xs mt-1">Cuidados, doses e intercorrências abertas aparecem aqui.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {pendencias.slice(0, 5).map(item => (
                <div key={`${item.origem}:${item.registro_id}`} className="p-3 rounded-xl bg-amber-50 border border-amber-100">
                  <div className="text-sm font-medium">{item.descricao}</div>
                  <div className="text-xs text-textMuted mt-1">{item.origem}{item.prioridade ? ` • ${item.prioridade}` : ''}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card bg-primaryLight/50 border-primaryLight">
        <h3 className="font-semibold text-primaryDeep">Jornada do residente</h3>
        <p className="text-sm text-textMuted mt-1">Pré-admissão → Admissão → Avaliações → Plano de Cuidados/PAIS → Programação → Meu Plantão → Execução → Prontuário → Intercorrências → Passagem de Plantão → Supervisão → Auditoria</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="badge-success">LGPD</span>
          <span className="badge-warning">Isolamento por ILPI</span>
          <span className="badge-danger">Rastreabilidade</span>
        </div>
      </div>
    </div>
  )
}
