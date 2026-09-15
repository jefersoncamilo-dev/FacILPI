import { useCallback, useEffect, useMemo, useState } from 'react'
import { formatDateTime, mensagemDeErro } from '../services/api'
import { Modal } from '../components/Modal'
import {
  PLANTAO_LIMIT_PADRAO,
  PLANTAO_ORIGENS,
  encerrarIntercorrencia,
  getPlantao,
  getResidentesResumo,
  registrarAdministracao,
  registrarExecucaoCuidado,
  type PlantaoItem,
  type PlantaoOrigem,
  type ResultadoCuidado,
  type ResultadoDose,
} from '../services/plantao'

const ROTULO_ORIGEM: Record<PlantaoOrigem, string> = {
  cuidado: 'Cuidado',
  medicacao: 'Medicação',
  intercorrencia: 'Intercorrência',
}

const ICONE_ORIGEM: Record<PlantaoOrigem, string> = {
  cuidado: '🛎️',
  medicacao: '💊',
  intercorrencia: '⚠️',
}

const ACAO_ORIGEM: Record<PlantaoOrigem, string> = {
  cuidado: 'Registrar execução',
  medicacao: 'Registrar administração',
  intercorrencia: 'Encerrar',
}

type Filtro = 'todos' | PlantaoOrigem

// Estado do formulário da ação. Um só objeto porque os três formulários são
// pequenos e mutuamente exclusivos — só um modal fica aberto por vez.
interface FormAcao {
  resultadoCuidado: ResultadoCuidado
  resultadoDose: ResultadoDose
  quantidade: string
  justificativa: string
  observacao: string
  desfecho: string
}

const FORM_VAZIO: FormAcao = {
  resultadoCuidado: 'executada',
  resultadoDose: 'administrada',
  quantidade: '',
  justificativa: '',
  observacao: '',
  desfecho: '',
}

function atrasado(item: PlantaoItem, agora: number): boolean {
  if (!item.previsto_em) return false
  return new Date(item.previsto_em).getTime() < agora
}

export function MeuPlantao() {
  const [itens, setItens] = useState<PlantaoItem[]>([])
  const [carregando, setCarregando] = useState(true)
  // `erro` separado de lista vazia: sem essa distinção um 403 viraria
  // "nenhuma pendência" na tela do plantonista.
  const [erro, setErro] = useState('')
  const [nomes, setNomes] = useState<Record<string, string>>({})
  const [filtro, setFiltro] = useState<Filtro>('todos')

  const [itemAberto, setItemAberto] = useState<PlantaoItem | null>(null)
  const [form, setForm] = useState<FormAcao>(FORM_VAZIO)
  const [erroAcao, setErroAcao] = useState('')
  const [salvando, setSalvando] = useState(false)

  const carregar = useCallback(async () => {
    setCarregando(true)
    try {
      const data = await getPlantao()
      setItens(data)
      setErro('')
    } catch (e) {
      // A lista é zerada junto com o erro para não exibir dados obsoletos
      // ao lado de uma mensagem de falha.
      setItens([])
      setErro(mensagemDeErro(e, 'Não foi possível carregar o plantão.'))
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => { carregar() }, [carregar])

  useEffect(() => {
    // Auxiliar: a falha aqui não vira erro de tela, só mantém o id como rótulo.
    getResidentesResumo()
      .then(lista => setNomes(Object.fromEntries(lista.map(r => [r.id, r.nome]))))
      .catch(() => setNomes({}))
  }, [])

  const agora = Date.now()

  const contagens = useMemo(() => {
    const base: Record<Filtro, number> = { todos: itens.length, cuidado: 0, medicacao: 0, intercorrencia: 0 }
    for (const item of itens) base[item.origem] += 1
    return base
  }, [itens])

  const lista = filtro === 'todos' ? itens : itens.filter(item => item.origem === filtro)
  const atrasados = itens.filter(item => atrasado(item, agora)).length

  function abrir(item: PlantaoItem) {
    setItemAberto(item)
    setForm(FORM_VAZIO)
    setErroAcao('')
  }

  function fechar() {
    setItemAberto(null)
    setErroAcao('')
  }

  // Espelha as validações condicionais dos schemas do backend para não gastar
  // uma ida ao servidor com um 422 previsível.
  function validar(item: PlantaoItem): string {
    if (item.origem === 'cuidado') {
      if (form.resultadoCuidado !== 'executada' && !form.justificativa.trim()) {
        return 'Justificativa obrigatória para recusa ou omissão.'
      }
      return ''
    }
    if (item.origem === 'medicacao') {
      if (form.resultadoDose === 'administrada') {
        const quantidade = Number(form.quantidade)
        if (!form.quantidade.trim() || Number.isNaN(quantidade) || quantidade <= 0) {
          return 'Informe a quantidade realizada (maior que zero).'
        }
      } else if (!form.justificativa.trim()) {
        return 'Justificativa obrigatória para recusa ou omissão.'
      }
      return ''
    }
    if (!form.desfecho.trim()) return 'Informe o desfecho da intercorrência.'
    return ''
  }

  async function confirmar() {
    if (!itemAberto) return
    const invalido = validar(itemAberto)
    if (invalido) { setErroAcao(invalido); return }

    setSalvando(true)
    setErroAcao('')
    // O instante do registro é o de agora: o plantonista está anotando o que
    // acabou de acontecer. Data retroativa exige a tela do próprio módulo.
    const ocorrido_em = new Date().toISOString()
    try {
      if (itemAberto.origem === 'cuidado') {
        await registrarExecucaoCuidado({
          ocorrencia_id: itemAberto.registro_id,
          resultado: form.resultadoCuidado,
          ocorrido_em,
          ...(form.observacao.trim() ? { observacao: form.observacao.trim() } : {}),
          ...(form.justificativa.trim() ? { justificativa: form.justificativa.trim() } : {}),
        })
      } else if (itemAberto.origem === 'medicacao') {
        await registrarAdministracao({
          dose_prevista_id: itemAberto.registro_id,
          resultado: form.resultadoDose,
          ocorrido_em,
          ...(form.resultadoDose === 'administrada' ? { quantidade_realizada: Number(form.quantidade) } : {}),
          ...(form.justificativa.trim() ? { justificativa: form.justificativa.trim() } : {}),
          ...(form.observacao.trim() ? { observacao: form.observacao.trim() } : {}),
        })
      } else {
        await encerrarIntercorrencia(itemAberto.registro_id, form.desfecho.trim())
      }
      fechar()
      await carregar()
    } catch (e) {
      // Conflito de concorrência (outro plantonista já registrou) chega aqui.
      // A projeção é recarregada para que a lista atrás do modal reflita a
      // realidade, e a mensagem do backend fica visível.
      setErroAcao(mensagemDeErro(e, 'Não foi possível registrar.'))
      await carregar()
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-primaryDeep">Meu Plantão</h1>
        <p className="text-textMuted text-sm">Pendências das próximas 24 horas — cuidados, doses e intercorrências abertas</p>
      </div>

      <div className="card p-2 flex gap-2 overflow-auto">
        {([{ value: 'todos' as Filtro, label: 'Todos' }, ...PLANTAO_ORIGENS]).map(opcao => (
          <button
            key={opcao.value}
            onClick={() => setFiltro(opcao.value as Filtro)}
            className={`px-4 py-2 rounded-xl text-sm font-medium whitespace-nowrap min-h-[44px] ${filtro === opcao.value ? 'bg-primary text-white' : 'bg-slate-100 text-textMuted hover:bg-slate-200'}`}
          >
            {opcao.label} ({contagens[opcao.value as Filtro]})
          </button>
        ))}
      </div>

      {atrasados > 0 && !erro && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm font-medium text-warning">⏰ {atrasados} {atrasados === 1 ? 'pendência atrasada' : 'pendências atrasadas'}</span>
        </div>
      )}

      {itens.length >= PLANTAO_LIMIT_PADRAO && !erro && (
        <div className="card border-l-4 border-l-warning py-3">
          <span className="text-sm text-textMuted">Exibindo as primeiras {PLANTAO_LIMIT_PADRAO} pendências. Pode haver mais no período.</span>
        </div>
      )}

      {carregando ? (
        <div className="card py-16 text-center text-textMuted">Carregando plantão…</div>
      ) : erro ? (
        <div className="card py-10 text-center" role="alert">
          <div className="text-4xl mb-2">⚠️</div>
          <p className="text-sm text-danger font-medium">{erro}</p>
          <button onClick={carregar} className="btn-primary mt-4 inline-flex">Tentar novamente</button>
        </div>
      ) : (
        <div className="grid gap-3">
          {lista.map(item => (
            <div
              key={`${item.origem}:${item.registro_id}`}
              className={`card flex gap-4 items-start border-l-4 ${item.prioridade === 'alta' ? 'border-l-danger' : item.prioridade === 'media' ? 'border-l-warning' : 'border-l-success'}`}
            >
              <div className="w-10 h-10 rounded-full bg-primaryLight flex items-center justify-center" aria-hidden="true">{ICONE_ORIGEM[item.origem]}</div>
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{item.descricao}</div>
                <div className="text-xs text-textMuted mt-1">
                  {ROTULO_ORIGEM[item.origem]} • {nomes[item.residente_id] || item.residente_id}
                  {item.previsto_em ? ` • ${formatDateTime(item.previsto_em)}` : ''}
                  {item.prioridade ? ` • ${item.prioridade}` : ''}
                </div>
                {atrasado(item, agora) && <span className="badge-warning mt-2 inline-block">Atrasada</span>}
              </div>
              <button onClick={() => abrir(item)} className="btn-primary text-sm px-4 py-2">
                {ACAO_ORIGEM[item.origem]}
              </button>
            </div>
          ))}
          {lista.length === 0 && (
            <div className="card py-16 text-center text-textMuted">Nenhuma pendência neste filtro</div>
          )}
        </div>
      )}

      <Modal open={itemAberto !== null} onClose={fechar} title={itemAberto ? ACAO_ORIGEM[itemAberto.origem] : ''}>
        {itemAberto && (
          <div className="space-y-3">
            <div className="text-sm text-textMuted">{itemAberto.descricao}</div>

            {itemAberto.origem === 'cuidado' && (
              <>
                <label className="block text-sm font-medium" htmlFor="resultado-cuidado">Resultado</label>
                <select
                  id="resultado-cuidado"
                  className="input"
                  value={form.resultadoCuidado}
                  onChange={e => setForm({ ...form, resultadoCuidado: e.target.value as ResultadoCuidado })}
                >
                  <option value="executada">Executada</option>
                  <option value="recusada">Recusada</option>
                  <option value="omitida">Omitida</option>
                </select>
                {form.resultadoCuidado !== 'executada' && (
                  <input
                    className="input"
                    placeholder="Justificativa (obrigatória)"
                    value={form.justificativa}
                    onChange={e => setForm({ ...form, justificativa: e.target.value })}
                  />
                )}
                <input
                  className="input"
                  placeholder="Observação (opcional)"
                  value={form.observacao}
                  onChange={e => setForm({ ...form, observacao: e.target.value })}
                />
              </>
            )}

            {itemAberto.origem === 'medicacao' && (
              <>
                <label className="block text-sm font-medium" htmlFor="resultado-dose">Resultado</label>
                <select
                  id="resultado-dose"
                  className="input"
                  value={form.resultadoDose}
                  onChange={e => setForm({ ...form, resultadoDose: e.target.value as ResultadoDose })}
                >
                  <option value="administrada">Administrada</option>
                  <option value="recusada">Recusada</option>
                  <option value="omitida">Omitida</option>
                </select>
                {form.resultadoDose === 'administrada' ? (
                  <input
                    className="input"
                    type="number"
                    min="0"
                    step="any"
                    placeholder="Quantidade realizada (obrigatória)"
                    value={form.quantidade}
                    onChange={e => setForm({ ...form, quantidade: e.target.value })}
                  />
                ) : (
                  <input
                    className="input"
                    placeholder="Justificativa (obrigatória)"
                    value={form.justificativa}
                    onChange={e => setForm({ ...form, justificativa: e.target.value })}
                  />
                )}
                <input
                  className="input"
                  placeholder="Observação (opcional)"
                  value={form.observacao}
                  onChange={e => setForm({ ...form, observacao: e.target.value })}
                />
              </>
            )}

            {itemAberto.origem === 'intercorrencia' && (
              <input
                className="input"
                placeholder="Desfecho (obrigatório)"
                value={form.desfecho}
                onChange={e => setForm({ ...form, desfecho: e.target.value })}
              />
            )}

            {erroAcao && <div className="text-sm text-danger" role="alert">{erroAcao}</div>}

            <button onClick={confirmar} disabled={salvando} className="btn-primary w-full disabled:opacity-60">
              {salvando ? 'Registrando…' : 'Confirmar'}
            </button>
          </div>
        )}
      </Modal>
    </div>
  )
}
