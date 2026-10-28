import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, mensagemDeErro } from '../../services/api'
import { usePermissoesOuPadrao } from '../../context/PermissoesContext'
import { Modal } from '../Modal'

/**
 * M13 (#194): familiares e responsáveis no Resumo, sobre o CRUD de /familiares.
 * Lista só com `familiares:ler` e já filtrada no backend por residente; criar e
 * editar seguem `familiares:criar`/`familiares:atualizar`. O tenant vem da
 * sessão: nada de `ilpi_id` no payload, e `residente_id` só no POST (imutável).
 * A lista mostra o necessário para contato; CPF e endereço ficam no formulário.
 */
export interface Familiar {
  id: string
  residente_id: string
  nome: string
  cpf?: string | null
  parentesco?: string | null
  telefone?: string | null
  email?: string | null
  endereco?: string | null
  tipo_responsabilidade?: string | null
  autorizacao_acesso?: boolean | null
}

type Campos = 'nome' | 'parentesco' | 'tipo_responsabilidade' | 'telefone' | 'email' | 'cpf' | 'endereco'
type Formulario = Record<Campos, string>

const VAZIO: Formulario = { nome: '', parentesco: '', tipo_responsabilidade: '', telefone: '', email: '', cpf: '', endereco: '' }

const CAMPOS: { campo: Campos; rotulo: string; tipo?: string; dica?: string }[] = [
  { campo: 'nome', rotulo: 'Nome' },
  { campo: 'parentesco', rotulo: 'Parentesco', dica: 'Ex.: filha, sobrinho' },
  { campo: 'tipo_responsabilidade', rotulo: 'Responsabilidade', dica: 'Ex.: responsável legal, contato principal' },
  { campo: 'telefone', rotulo: 'Telefone', tipo: 'tel' },
  { campo: 'email', rotulo: 'E-mail', tipo: 'email' },
  { campo: 'cpf', rotulo: 'CPF' },
  { campo: 'endereco', rotulo: 'Endereço' },
]

// Campo vazio vira null: o backend não guarda texto em branco como valor.
function payloadDe(f: Formulario): Record<Campos, string | null> {
  const p = {} as Record<Campos, string | null>
  for (const { campo } of CAMPOS) p[campo] = f[campo].trim() || null
  return p
}

function FamiliarModal({
  residenteId,
  familiar,
  open,
  onClose,
  onSalvo,
}: {
  residenteId: string
  familiar: Familiar | null
  open: boolean
  onClose: () => void
  onSalvo: () => void
}) {
  const [form, setForm] = useState<Formulario>(VAZIO)
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    if (!open) return
    setErro('')
    setForm(familiar ? Object.fromEntries(CAMPOS.map(({ campo }) => [campo, familiar[campo] ?? ''])) as Formulario : VAZIO)
  }, [open, familiar])

  async function salvar(e: FormEvent) {
    e.preventDefault()
    if (!form.nome.trim()) { setErro('Informe o nome.'); return }
    setSalvando(true)
    setErro('')
    try {
      if (familiar) await api.put(`/familiares/${familiar.id}`, payloadDe(form))
      else await api.post('/familiares/', { residente_id: residenteId, ...payloadDe(form) })
      onSalvo()
    } catch (err) {
      setErro(mensagemDeErro(err, 'Não foi possível salvar o familiar.'))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={familiar ? 'Editar familiar' : 'Cadastrar familiar'}>
      <form onSubmit={salvar} className="space-y-3">
        {CAMPOS.map(({ campo, rotulo, tipo, dica }) => (
          <div key={campo}>
            <label className="block text-sm font-medium mb-1" htmlFor={`familiar-${campo}`}>{rotulo}</label>
            <input
              id={`familiar-${campo}`}
              className="input"
              type={tipo ?? 'text'}
              placeholder={dica}
              value={form[campo]}
              onChange={e => setForm(f => ({ ...f, [campo]: e.target.value }))}
            />
          </div>
        ))}
        {erro && <p role="alert" className="text-sm text-danger">{erro}</p>}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="btn-secondary w-full sm:w-auto">Cancelar</button>
          <button type="submit" disabled={salvando} className="btn-primary w-full sm:w-auto disabled:opacity-60">
            {salvando ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export function FamiliaresResidente({ residenteId }: { residenteId: string }) {
  const { pode, status } = usePermissoesOuPadrao()
  // Fora do provider (testes isolados) ou com permissões carregando, nada consulta.
  const pronto = status !== 'carregando' && status !== 'sem_provider' && pode('familiares:ler')
  const podeCriar = pode('familiares:criar')
  const podeEditar = pode('familiares:atualizar')
  const [lista, setLista] = useState<Familiar[] | null>(null)
  const [erro, setErro] = useState(false)
  const [editando, setEditando] = useState<Familiar | null>(null)
  const [aberto, setAberto] = useState(false)
  const [sucesso, setSucesso] = useState('')

  const carregar = useCallback(() => {
    setErro(false)
    Promise.resolve()
      .then(() => api.get<Familiar[]>('/familiares/', { params: { residente_id: residenteId } }))
      .then(r => setLista(r.data || []))
      .catch(() => setErro(true))
  }, [residenteId])

  useEffect(() => {
    if (!pronto) return
    setLista(null)
    carregar()
  }, [pronto, carregar])

  if (!pronto) return null

  return (
    <section className="card space-y-2 p-4 md:col-span-2" aria-label="Familiares e responsáveis">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Familiares e responsáveis</h2>
        {podeCriar && (
          <button
            type="button"
            onClick={() => { setSucesso(''); setEditando(null); setAberto(true) }}
            className="text-sm text-primary hover:underline inline-flex items-center min-h-[44px]"
          >
            + Cadastrar
          </button>
        )}
      </div>
      {sucesso && <p role="status" className="text-sm text-success">{sucesso}</p>}
      {erro ? (
        <p className="text-sm text-danger">Não foi possível carregar.</p>
      ) : lista === null ? (
        <p className="text-sm text-muted-foreground">Carregando…</p>
      ) : lista.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nenhum familiar cadastrado.</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {lista.map(f => (
            <li key={f.id} className="flex flex-wrap items-start justify-between gap-2 py-2">
              <div className="min-w-0">
                <p className="font-medium text-foreground">
                  {f.nome}
                  {f.parentesco && <span className="font-normal text-muted-foreground"> · {f.parentesco}</span>}
                </p>
                {f.tipo_responsabilidade && <p className="text-muted-foreground">{f.tipo_responsabilidade}</p>}
                {(f.telefone || f.email) && (
                  <p className="text-muted-foreground break-words">
                    {f.telefone && <a href={`tel:${f.telefone}`} className="text-primary hover:underline">{f.telefone}</a>}
                    {f.telefone && f.email && ' · '}
                    {f.email}
                  </p>
                )}
              </div>
              {podeEditar && (
                <button
                  type="button"
                  onClick={() => { setSucesso(''); setEditando(f); setAberto(true) }}
                  className="text-sm text-primary hover:underline inline-flex items-center min-h-[44px]"
                  aria-label={`Editar ${f.nome}`}
                >
                  Editar
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <FamiliarModal
        residenteId={residenteId}
        familiar={editando}
        open={aberto}
        onClose={() => setAberto(false)}
        onSalvo={() => {
          setAberto(false)
          setSucesso(editando ? 'Familiar atualizado.' : 'Familiar cadastrado.')
          carregar()
        }}
      />
    </section>
  )
}
