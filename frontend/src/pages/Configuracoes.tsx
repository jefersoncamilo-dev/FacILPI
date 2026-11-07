import { useEffect, useState, type FormEvent } from 'react'
import { Lock } from 'lucide-react'
import { mensagemDeErro } from '../services/api'
import { configuracoesApi, type Configuracoes as Dados } from '../services/configuracoes'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Alert, Skeleton } from '../components/ui/feedback'
import { EmptyState } from '../components/ui/states'

const CAMPOS: { chave: keyof Dados; rotulo: string; tipo?: string }[] = [
  { chave: 'nome_fantasia', rotulo: 'Nome fantasia' },
  { chave: 'telefone', rotulo: 'Telefone' },
  { chave: 'email', rotulo: 'E-mail', tipo: 'email' },
  { chave: 'endereco', rotulo: 'Endereço' },
  { chave: 'municipio', rotulo: 'Município' },
  { chave: 'uf', rotulo: 'UF' },
  { chave: 'responsavel_legal', rotulo: 'Responsável legal' },
  { chave: 'responsavel_tecnico', rotulo: 'Responsável técnico' },
  { chave: 'capacidade', rotulo: 'Capacidade (residentes)', tipo: 'number' },
  { chave: 'licenca_sanitaria', rotulo: 'Licença sanitária' },
  { chave: 'validade_licenca', rotulo: 'Validade da licença', tipo: 'date' },
  { chave: 'fuso_horario', rotulo: 'Fuso horário' },
]

/** Dados da instituição da sessão. Razão social e CNPJ vêm da Plataforma. */
export function Configuracoes() {
  const { pode } = usePermissoesOuPadrao()
  const [dados, setDados] = useState<Dados | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [erro, setErro] = useState<string | null>(null)
  const [proibido, setProibido] = useState(false)
  const [aviso, setAviso] = useState<{ tipo: 'success' | 'error'; texto: string } | null>(null)
  const [salvando, setSalvando] = useState(false)

  function aplicar(d: Dados) {
    setDados(d)
    setForm(Object.fromEntries(CAMPOS.map(c => [c.chave, d[c.chave] == null ? '' : String(d[c.chave])])))
  }

  useEffect(() => {
    configuracoesApi.ler().then(aplicar).catch(e => {
      if (e?.response?.status === 403) setProibido(true)
      else setErro(mensagemDeErro(e, 'Não foi possível carregar as configurações.'))
    })
  }, [])

  async function salvar(e: FormEvent) {
    e.preventDefault()
    setSalvando(true)
    setAviso(null)
    try {
      const corpo = Object.fromEntries(CAMPOS.map(c => [
        c.chave,
        form[c.chave] === '' ? null : c.tipo === 'number' ? Number(form[c.chave]) : form[c.chave],
      ]))
      aplicar(await configuracoesApi.salvar(corpo as Partial<Dados>))
      setAviso({ tipo: 'success', texto: 'Configurações salvas.' })
    } catch (err) {
      setAviso({ tipo: 'error', texto: mensagemDeErro(err, 'Não foi possível salvar.') })
    } finally {
      setSalvando(false)
    }
  }

  if (proibido) return <EmptyState icon={Lock} title="Sem acesso às configurações" description="Peça acesso ao administrador da instituição." />
  if (erro) return <Alert variant="error">{erro}</Alert>
  if (!dados) return <Skeleton className="h-64 w-full rounded-card" />
  const editavel = pode('configuracoes:atualizar')

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-titulo-tela text-brand-ink">Configurações</h1>
        <p className="mt-1 text-apoio text-muted-foreground">{dados.razao_social}{dados.cnpj ? ` · CNPJ ${dados.cnpj}` : ''}</p>
      </header>
      {aviso && <Alert variant={aviso.tipo}>{aviso.texto}</Alert>}
      <form onSubmit={salvar} className="grid gap-4 md:grid-cols-2">
        {CAMPOS.map(c => (
          <div key={c.chave} className="space-y-1">
            <Label htmlFor={c.chave}>{c.rotulo}</Label>
            <Input id={c.chave} type={c.tipo || 'text'} disabled={!editavel} value={form[c.chave] ?? ''}
              onChange={e => setForm(f => ({ ...f, [c.chave]: e.target.value }))} />
          </div>
        ))}
        {editavel && <div className="md:col-span-2"><Button type="submit" disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar'}</Button></div>}
      </form>
    </div>
  )
}
