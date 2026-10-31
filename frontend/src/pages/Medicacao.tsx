import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { Pill } from 'lucide-react'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { formatDateTime, mensagemDeErro } from '../services/api'
import { getResidentesResumo, type ResidenteResumo } from '../services/plantao'
import {
  SITUACOES,
  ativarPrescricao,
  criarMedicamento,
  criarPrescricao,
  encerrarPrescricao,
  fusoLocal,
  getDosesDoDia,
  getMedicamentos,
  getPrescricoes,
  lerHorarios,
  substituirPrescricao,
  suspenderPrescricao,
  type DosePrevista,
  type Medicamento,
  type Prescricao,
  type PrescricaoNova,
} from '../services/medicacao'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Badge } from '../components/ui/feedback'
import { EmptyState, LoadingState } from '../components/ui/states'

/**
 * M9: prescrições do residente por situação, rascunho com prescritor externo,
 * ativação com horários fixos, suspender/encerrar/substituir com motivo e a
 * grade de doses do dia (só leitura; a administração segue no Meu Plantão).
 * Ações só aparecem com a permissão correspondente; o backend é a autoridade.
 */

type Acao = 'ativar' | 'suspender' | 'encerrar' | 'substituir'

const ROTULO_ACAO: Record<Acao, string> = {
  ativar: 'Ativar',
  suspender: 'Suspender',
  encerrar: 'Encerrar',
  substituir: 'Substituir',
}

const ACOES_POR_SITUACAO: Record<string, Acao[]> = {
  rascunho: ['ativar', 'encerrar'],
  ativa: ['suspender', 'substituir', 'encerrar'],
  suspensa: ['substituir', 'encerrar'],
}

const ROTULO_DOSE: Record<string, string> = {
  prevista: 'Prevista',
  cancelada: 'Cancelada',
}

const VAZIA: Omit<PrescricaoNova, 'residente_id' | 'inicio'> = {
  medicamento_id: '',
  prescritor_nome: '',
  prescritor_categoria: 'Médico',
  prescritor_conselho: 'CRM',
  prescritor_numero: '',
  prescritor_uf: '',
  dose: '',
  unidade: '',
  via: 'oral',
  frequencia: '',
  orientacoes: '',
}

const hoje = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// Campos opcionais vazios não vão ao backend (o schema recusa string vazia).
function limpar(p: PrescricaoNova): PrescricaoNova {
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== '' && v !== undefined)) as unknown as PrescricaoNova
}

function nomeDoMedicamento(p: Prescricao, medicamentos: Medicamento[]): string {
  return p.medicamento_snapshot?.nome || medicamentos.find(m => m.id === p.medicamento_id)?.nome || 'Medicamento'
}

export function Medicacao() {
  const { id: residenteDaRota } = useParams()
  const { pode, status } = usePermissoesOuPadrao()
  // Espera as permissões: recarregar depois desmontaria um formulário já aberto.
  const permissoesProntas = status !== 'carregando'
  const [residentes, setResidentes] = useState<ResidenteResumo[]>([])
  const [residenteId, setResidenteId] = useState(residenteDaRota ?? '')
  const [medicamentos, setMedicamentos] = useState<Medicamento[]>([])
  const [prescricoes, setPrescricoes] = useState<Prescricao[]>([])
  const [doses, setDoses] = useState<DosePrevista[]>([])
  const [carregando, setCarregando] = useState(Boolean(residenteDaRota))
  const [erro, setErro] = useState('')
  const [sucesso, setSucesso] = useState('')

  const podeCriar = pode('prescricoes:criar')
  const podeAtualizar = pode('prescricoes:atualizar')
  const podeCadastrarMedicamento = pode('medicamentos:criar')
  const podeVerDoses = pode('doses_previstas:ler')

  useEffect(() => { if (residenteDaRota) setResidenteId(residenteDaRota) }, [residenteDaRota])

  useEffect(() => {
    if (!permissoesProntas) return
    getResidentesResumo().then(setResidentes).catch(() => setResidentes([]))
    if (pode('medicamentos:ler')) getMedicamentos().then(setMedicamentos).catch(() => setMedicamentos([]))
  }, [pode, permissoesProntas])

  const carregar = useCallback(async () => {
    if (!residenteId || !permissoesProntas) return
    setCarregando(true)
    try {
      setPrescricoes(await getPrescricoes(residenteId))
      setErro('')
    } catch (e) {
      setPrescricoes([])
      setErro(mensagemDeErro(e, 'Não foi possível carregar as prescrições.'))
    } finally {
      setCarregando(false)
    }
    if (podeVerDoses) getDosesDoDia(residenteId).then(setDoses).catch(() => setDoses([]))
  }, [residenteId, podeVerDoses, permissoesProntas])

  useEffect(() => { carregar() }, [carregar])

  const nomeResidente = residentes.find(r => r.id === residenteId)?.nome
  const porPrescricao = useMemo(() => Object.fromEntries(prescricoes.map(p => [p.id, p])), [prescricoes])

  async function executar(promessa: Promise<unknown>, mensagem: string) {
    try {
      await promessa
      setSucesso(mensagem)
      setErro('')
      await carregar()
      return true
    } catch (e) {
      setSucesso('')
      setErro(mensagemDeErro(e, 'Não foi possível concluir a ação.'))
      return false
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Medicação</h1>
        <p className="text-textMuted text-sm">
          {nomeResidente ? `Prescrições de ${nomeResidente}` : 'Prescrições e doses do dia por residente'}
        </p>
      </div>

      {!residenteDaRota && (
        <div className="max-w-md space-y-1">
          <Label htmlFor="med-residente">Residente</Label>
          <select id="med-residente" className="input w-full" value={residenteId}
                  onChange={e => { setResidenteId(e.target.value); setSucesso(''); setErro('') }}>
            <option value="">Selecione o residente</option>
            {residentes.map(r => <option key={r.id} value={r.id}>{r.nome}</option>)}
          </select>
        </div>
      )}
      {residenteDaRota && (
        <Link to={`/residentes/${residenteDaRota}`} className="text-sm font-medium text-primary hover:underline">
          Voltar ao prontuário
        </Link>
      )}

      {sucesso && <Alert variant="success">{sucesso}</Alert>}
      {erro && <Alert variant="error">{erro}</Alert>}

      {!residenteId ? (
        <EmptyState icon={Pill} title="Escolha um residente" description="Selecione o residente para ver as prescrições." />
      ) : carregando && !prescricoes.length ? (
        <LoadingState label="Carregando prescrições…" />
      ) : (
        <>
          {podeCriar && (
            <NovaPrescricao residenteId={residenteId} medicamentos={medicamentos}
                            podeCadastrarMedicamento={podeCadastrarMedicamento}
                            aoCadastrarMedicamento={m => setMedicamentos(l => [...l, m])}
                            aoSalvar={p => executar(criarPrescricao(p), 'Rascunho de prescrição criado.')} />
          )}

          {SITUACOES.map(({ value, label }) => {
            const lista = prescricoes.filter(p => p.situacao === value)
            if (!lista.length) return null
            return (
              <section key={value} aria-label={label} className="space-y-3">
                <h2 className="text-lg font-semibold">{label} ({lista.length})</h2>
                {lista.map(p => (
                  <PrescricaoCartao key={p.id} prescricao={p} nome={nomeDoMedicamento(p, medicamentos)}
                                    podeAtualizar={podeAtualizar} executar={executar} />
                ))}
              </section>
            )
          })}
          {!prescricoes.length && (
            <EmptyState icon={Pill} title="Nenhuma prescrição" description="Este residente ainda não tem prescrições registradas." />
          )}

          {podeVerDoses && (
            <section aria-label="Doses de hoje" className="space-y-2">
              <h2 className="text-lg font-semibold">Doses de hoje</h2>
              <p className="text-sm text-textMuted">Somente leitura. A administração é registrada no Meu Plantão.</p>
              {!doses.length ? (
                <p className="text-sm">Nenhuma dose prevista para hoje.</p>
              ) : (
                <ul className="divide-y rounded-lg border">
                  {[...doses].sort((a, b) => a.previsto_em.localeCompare(b.previsto_em)).map(d => {
                    const p = porPrescricao[d.prescricao_id]
                    return (
                      <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
                        <span>{formatDateTime(d.previsto_em)} · {p ? `${nomeDoMedicamento(p, medicamentos)} ${p.dose} ${p.unidade ?? ''}` : 'Medicação'}</span>
                        <Badge variant={d.situacao === 'cancelada' ? 'neutral' : d.pendente ? 'warning' : 'success'}>
                          {d.situacao === 'prevista' && !d.pendente ? 'Registrada' : (ROTULO_DOSE[d.situacao] ?? d.situacao)}
                        </Badge>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Campo({ id, label, ...props }: { id: string; label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} {...props} />
    </div>
  )
}

function NovaPrescricao({ residenteId, medicamentos, podeCadastrarMedicamento, aoCadastrarMedicamento, aoSalvar }: {
  residenteId: string
  medicamentos: Medicamento[]
  podeCadastrarMedicamento: boolean
  aoCadastrarMedicamento: (m: Medicamento) => void
  aoSalvar: (p: PrescricaoNova) => Promise<boolean>
}) {
  const [aberto, setAberto] = useState(false)
  const [form, setForm] = useState({ ...VAZIA, inicio: hoje() })
  const [novoMedicamento, setNovoMedicamento] = useState('')
  const [erroMedicamento, setErroMedicamento] = useState('')
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }))

  async function cadastrar() {
    try {
      const m = await criarMedicamento(novoMedicamento.trim())
      aoCadastrarMedicamento(m)
      setForm(f => ({ ...f, medicamento_id: m.id }))
      setNovoMedicamento('')
      setErroMedicamento('')
    } catch (e) {
      setErroMedicamento(mensagemDeErro(e, 'Não foi possível cadastrar o medicamento.'))
    }
  }

  async function enviar(e: FormEvent) {
    e.preventDefault()
    if (await aoSalvar(limpar({ ...form, residente_id: residenteId }))) {
      setForm({ ...VAZIA, inicio: hoje() })
      setAberto(false)
    }
  }

  if (!aberto) return <Button onClick={() => setAberto(true)}>Nova prescrição</Button>

  return (
    <form onSubmit={enviar} aria-label="Nova prescrição" className="space-y-4 rounded-lg border p-4">
      <h2 className="text-lg font-semibold">Nova prescrição (rascunho)</h2>
      <p className="text-sm text-textMuted">Transcreva a receita do prescritor. A prescrição só gera doses depois de ativada.</p>
      <div className="space-y-1">
        <Label htmlFor="np-medicamento">Medicamento</Label>
        <select id="np-medicamento" className="input w-full" required value={form.medicamento_id} onChange={set('medicamento_id')}>
          <option value="">Selecione</option>
          {medicamentos.filter(m => m.situacao !== 'inativo').map(m => (
            <option key={m.id} value={m.id}>{[m.nome, m.concentracao].filter(Boolean).join(' ')}</option>
          ))}
        </select>
      </div>
      {podeCadastrarMedicamento && (
        <div className="flex flex-wrap items-end gap-2">
          <Campo id="np-novo-med" label="Cadastrar medicamento" value={novoMedicamento}
                 onChange={e => setNovoMedicamento(e.target.value)} />
          <Button type="button" variant="outline" disabled={!novoMedicamento.trim()} onClick={cadastrar}>Cadastrar</Button>
          {erroMedicamento && <Alert variant="error">{erroMedicamento}</Alert>}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Campo id="np-prescritor" label="Prescritor" required value={form.prescritor_nome} onChange={set('prescritor_nome')} />
        <Campo id="np-categoria" label="Categoria do prescritor" required value={form.prescritor_categoria} onChange={set('prescritor_categoria')} />
        <Campo id="np-conselho" label="Conselho" value={form.prescritor_conselho} onChange={set('prescritor_conselho')} />
        <Campo id="np-numero" label="Número no conselho" value={form.prescritor_numero} onChange={set('prescritor_numero')} />
        <Campo id="np-uf" label="UF" maxLength={2} value={form.prescritor_uf} onChange={set('prescritor_uf')} />
        <Campo id="np-dose" label="Dose" required inputMode="decimal" value={form.dose} onChange={set('dose')} />
        <Campo id="np-unidade" label="Unidade" required placeholder="cp, mL, gotas" value={form.unidade} onChange={set('unidade')} />
        <Campo id="np-via" label="Via" required value={form.via} onChange={set('via')} />
        <Campo id="np-frequencia" label="Frequência" placeholder="de 12 em 12 horas" value={form.frequencia} onChange={set('frequencia')} />
        <Campo id="np-inicio" label="Início" type="date" required value={form.inicio} onChange={set('inicio')} />
      </div>
      <Campo id="np-orientacoes" label="Orientações" value={form.orientacoes} onChange={set('orientacoes')} />
      <div className="flex gap-2">
        <Button type="submit">Salvar rascunho</Button>
        <Button type="button" variant="outline" onClick={() => setAberto(false)}>Cancelar</Button>
      </div>
    </form>
  )
}

function PrescricaoCartao({ prescricao: p, nome, podeAtualizar, executar }: {
  prescricao: Prescricao
  nome: string
  podeAtualizar: boolean
  executar: (promessa: Promise<unknown>, mensagem: string) => Promise<boolean>
}) {
  const [acao, setAcao] = useState<Acao | null>(null)
  const [motivo, setMotivo] = useState('')
  const [horarios, setHorarios] = useState(p.programacao?.horarios.join(', ') ?? '')
  const [dose, setDose] = useState(p.dose)
  const acoes = podeAtualizar ? (ACOES_POR_SITUACAO[p.situacao] ?? []) : []
  const motivoDaSituacao = p.motivo_suspensao || p.motivo_encerramento

  async function confirmar(e: FormEvent) {
    e.preventDefault()
    if (!acao) return
    const programacao = { horarios: lerHorarios(horarios), timezone: fusoLocal(), vigencia_inicio: new Date().toISOString() }
    let promessa: Promise<unknown>
    if (acao === 'ativar') promessa = ativarPrescricao(p.id, programacao)
    else if (acao === 'suspender') promessa = suspenderPrescricao(p.id, motivo.trim())
    else if (acao === 'encerrar') promessa = encerrarPrescricao(p.id, motivo.trim())
    else promessa = substituirPrescricao(p.id, {
      motivo: motivo.trim(),
      programacao,
      prescricao: limpar({
        residente_id: p.residente_id, medicamento_id: p.medicamento_id,
        prescritor_nome: p.prescritor_nome ?? p.prescritor, prescritor_categoria: p.prescritor_categoria ?? '',
        prescritor_conselho: p.prescritor_conselho ?? '', prescritor_numero: p.prescritor_numero ?? '',
        prescritor_uf: p.prescritor_uf ?? '', dose: dose.trim(), unidade: p.unidade ?? '', via: p.via ?? '',
        frequencia: p.frequencia ?? '', inicio: hoje(), orientacoes: p.orientacoes ?? '',
      }),
    })
    const mensagens: Record<Acao, string> = {
      ativar: 'Prescrição ativada.', suspender: 'Prescrição suspensa.',
      encerrar: 'Prescrição encerrada.', substituir: 'Prescrição substituída por nova versão.',
    }
    if (await executar(promessa, mensagens[acao])) setAcao(null)
  }

  const precisaMotivo = acao !== null && acao !== 'ativar'
  const precisaHorarios = acao === 'ativar' || acao === 'substituir'

  return (
    <article aria-label={nome} className="space-y-2 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{nome} — {p.dose} {p.unidade} · {p.via}</p>
          <p className="text-sm text-textMuted">
            {p.frequencia ? `${p.frequencia} · ` : ''}Prescritor: {p.prescritor_nome ?? p.prescritor}
            {p.prescritor_conselho && p.prescritor_numero ? ` (${p.prescritor_conselho} ${p.prescritor_numero}${p.prescritor_uf ? `/${p.prescritor_uf}` : ''})` : ''}
          </p>
          {p.programacao?.horarios?.length ? <p className="text-sm">Horários: {p.programacao.horarios.join(', ')}</p> : null}
          {motivoDaSituacao && <p className="text-sm">Motivo: {motivoDaSituacao}</p>}
          {p.orientacoes && <p className="text-sm">Orientações: {p.orientacoes}</p>}
        </div>
      </div>
      {acoes.length > 0 && !acao && (
        <div className="flex flex-wrap gap-2">
          {acoes.map(a => (
            <Button key={a} variant={a === 'ativar' ? 'default' : 'outline'}
                    onClick={() => { setAcao(a); setMotivo('') }}>{ROTULO_ACAO[a]}</Button>
          ))}
        </div>
      )}
      {acao && (
        <form onSubmit={confirmar} aria-label={`${ROTULO_ACAO[acao]} prescrição`} className="space-y-3 border-t pt-3">
          {acao === 'substituir' && (
            <Campo id={`dose-${p.id}`} label="Nova dose" required value={dose} onChange={e => setDose(e.target.value)} />
          )}
          {precisaHorarios && (
            <Campo id={`horarios-${p.id}`} label="Horários fixos (ex.: 08:00, 20:00)" required value={horarios}
                   onChange={e => setHorarios(e.target.value)} />
          )}
          {precisaMotivo && (
            <Campo id={`motivo-${p.id}`} label="Motivo" required value={motivo} onChange={e => setMotivo(e.target.value)} />
          )}
          <div className="flex gap-2">
            <Button type="submit">Confirmar</Button>
            <Button type="button" variant="outline" onClick={() => setAcao(null)}>Cancelar</Button>
          </div>
        </form>
      )}
    </article>
  )
}
