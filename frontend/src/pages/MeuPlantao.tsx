import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlarmClock, BellRing, Clock, Pill, TriangleAlert, type LucideIcon } from 'lucide-react'
import { formatDateTime, mensagemDeErro } from '../services/api'
import { Modal } from '../components/Modal'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Alert } from '../components/ui/feedback'
import { cn } from '../lib/utils'
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

const ICONE_ORIGEM: Record<PlantaoOrigem, LucideIcon> = {
  cuidado: BellRing,
  medicacao: Pill,
  intercorrencia: TriangleAlert,
}

// UX-05 (#91): permissão que cada ação exige no backend. Sem ela, a pendência
// continua visível (informa o turno), mas o botão não é oferecido.
const PERMISSAO_ACAO: Record<PlantaoOrigem, string> = {
  cuidado: 'execucoes:criar',
  medicacao: 'administracoes:criar',
  intercorrencia: 'intercorrencias:atualizar',
}

const SUCESSO_ACAO: Record<PlantaoOrigem, string> = {
  cuidado: 'Execução registrada.',
  medicacao: 'Administração registrada.',
  intercorrencia: 'Intercorrência encerrada.',
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

/**
 * `?desde=` (ISO) amplia o início da projeção para trás — vem da Passagem de
 * Plantão, para que cuidados e doses previstos antes da abertura da tela e
 * ainda sem registro apareçam em "Atrasadas" com as ações de sempre. Sem o
 * parâmetro, a projeção é a padrão do backend (agora → +24 h).
 */
export function lerDesde(valor: string | null, agora = Date.now()): string | null {
  if (!valor) return null
  const t = Date.parse(valor)
  return Number.isFinite(t) && t < agora ? new Date(t).toISOString() : null
}

function atrasado(item: PlantaoItem, agora: number): boolean {
  if (!item.previsto_em) return false
  return new Date(item.previsto_em).getTime() < agora
}

export function MeuPlantao() {
  const { pode } = usePermissoesOuPadrao()
  const [params] = useSearchParams()
  const desde = lerDesde(params.get('desde'))
  const [sucesso, setSucesso] = useState('')
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
      const data = await getPlantao(desde ? { a_partir_de: desde } : {})
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
  }, [desde])

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
    setSucesso('')
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
      const origem = itemAberto.origem
      fechar()
      await carregar()
      setSucesso(SUCESSO_ACAO[origem])
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
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Meu Plantão</h1>
        <p className="text-sm text-muted-foreground">
          {desde
            ? <>Pendências desde {formatDateTime(desde)} e das próximas 24 horas — cuidados, doses e intercorrências abertas · <Link to="/plantao" className="font-medium text-primary hover:underline">ver só a partir de agora</Link></>
            : 'Pendências das próximas 24 horas — cuidados, doses e intercorrências abertas'}
        </p>
      </div>

      <div className="flex gap-2 overflow-x-auto rounded-lg bg-muted p-1" role="group" aria-label="Filtrar por origem">
        {([{ value: 'todos' as Filtro, label: 'Todos' }, ...PLANTAO_ORIGENS]).map(opcao => (
          <button
            key={opcao.value}
            aria-pressed={filtro === opcao.value}
            onClick={() => setFiltro(opcao.value as Filtro)}
            className={cn(
              'min-h-[40px] shrink-0 whitespace-nowrap rounded-md px-3 text-sm font-medium transition-colors',
              filtro === opcao.value ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {opcao.label} ({contagens[opcao.value as Filtro]})
          </button>
        ))}
      </div>

      {sucesso && <Alert variant="success">{sucesso}</Alert>}

      {atrasados > 0 && !erro && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <AlarmClock className="size-4 text-amber-800" aria-hidden="true" />
          <span className="text-sm font-medium text-amber-900">{atrasados} {atrasados === 1 ? 'pendência atrasada' : 'pendências atrasadas'}</span>
        </div>
      )}

      {itens.length >= PLANTAO_LIMIT_PADRAO && !erro && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <span className="text-sm text-muted-foreground">Exibindo as primeiras {PLANTAO_LIMIT_PADRAO} pendências. Pode haver mais no período.</span>
        </div>
      )}

      {carregando ? (
        <div className="card py-16 text-center text-muted-foreground">Carregando plantão…</div>
      ) : erro ? (
        <div className="card py-10 text-center" role="alert">
          <TriangleAlert className="mx-auto mb-3 size-7 text-amber-700" aria-hidden="true" />
          <p className="text-sm font-medium text-red-700">{erro}</p>
          <button onClick={carregar} className="btn-primary mt-4 inline-flex">Tentar novamente</button>
        </div>
      ) : lista.length === 0 ? (
        <div className="card py-16 text-center text-muted-foreground">Nenhuma pendência neste filtro</div>
      ) : (
        <div className="space-y-6">
          {/* UX-05: agrupado pela pergunta do turno — o que já passou da hora, o
              que vem a seguir, e o que não tem horário (intercorrência aberta).
              A ordem dentro de cada grupo é a da projeção oficial. */}
          {[
            { titulo: 'Atrasadas', itens: lista.filter(i => atrasado(i, agora)) },
            { titulo: 'Próximas', itens: lista.filter(i => i.previsto_em && !atrasado(i, agora)) },
            { titulo: 'Sem horário', itens: lista.filter(i => !i.previsto_em) },
          ].filter(g => g.itens.length > 0).map(grupo => (
            <section key={grupo.titulo} aria-label={grupo.titulo} className="space-y-3">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {grupo.titulo} <span className="font-normal">({grupo.itens.length})</span>
              </h2>
              {grupo.itens.map(item => {
                const Icone = ICONE_ORIGEM[item.origem]
                const podeAgir = pode(PERMISSAO_ACAO[item.origem])
                return (
                  <div
                    key={`${item.origem}:${item.registro_id}`}
                    className={cn(
                      'card flex flex-wrap items-start gap-4 border-l-4 sm:flex-nowrap',
                      item.prioridade === 'alta' ? 'border-l-red-600' : item.prioridade === 'media' ? 'border-l-amber-500' : 'border-l-brand',
                    )}
                  >
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-primary" aria-hidden="true">
                      <Icone className="size-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{item.descricao}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {ROTULO_ORIGEM[item.origem]} • {nomes[item.residente_id] || item.residente_id}
                        {item.previsto_em ? ` • ${formatDateTime(item.previsto_em)}` : ''}
                        {item.prioridade ? ` • ${item.prioridade}` : ''}
                      </div>
                      {atrasado(item, agora) && (
                        <span className="badge-warning mt-2 inline-flex"><Clock className="size-3" aria-hidden="true" /> Atrasada</span>
                      )}
                    </div>
                    {podeAgir && (
                      <button onClick={() => abrir(item)} className="btn-primary w-full px-4 py-2 text-sm sm:w-auto">
                        {ACAO_ORIGEM[item.origem]}
                      </button>
                    )}
                  </div>
                )
              })}
            </section>
          ))}
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
