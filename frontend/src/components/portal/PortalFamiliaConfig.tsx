import { useEffect, useState } from 'react'
import { api, mensagemDeErro } from '../../services/api'
import { Button } from '../ui/button'
import { Alert } from '../ui/feedback'

// #303: o que o portal da família mostra nesta ILPI. Tudo começa bloqueado e o
// portal começa desligado; a equipe decide o que liberar. O backend é quem aplica.
export const CATEGORIAS_PORTAL: { id: string; rotulo: string; descricao: string }[] = [
  { id: 'medicacao', rotulo: 'Remédios', descricao: 'Quantos remédios previstos foram dados nos últimos 30 dias.' },
  { id: 'alimentacao', rotulo: 'Alimentação', descricao: 'Quanto das refeições foi comido, em média (30 dias).' },
  { id: 'atividades', rotulo: 'Atividades e cuidados', descricao: 'Quantos cuidados programados foram feitos (30 dias).' },
  { id: 'bem_estar', rotulo: 'Peso', descricao: 'Pesagens registradas nos últimos 30 dias.' },
  { id: 'recados', rotulo: 'Recados da equipe', descricao: 'Recados escritos pela equipe para a família.' },
  { id: 'agenda', rotulo: 'Agenda', descricao: 'Compromissos dos próximos 30 dias.' },
  { id: 'mensalidades', rotulo: 'Mensalidades', descricao: 'Valores, vencimentos e situação.' },
]

interface Config { ativo: boolean; categorias: string[] }

export function PortalFamiliaConfig() {
  const [config, setConfig] = useState<Config | null>(null)
  const [aviso, setAviso] = useState<{ tipo: 'success' | 'error'; texto: string } | null>(null)
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    api.get<Config>('/portal/config').then(r => setConfig(r.data))
      .catch(e => setAviso({ tipo: 'error', texto: mensagemDeErro(e, 'Não foi possível carregar o portal da família.') }))
  }, [])

  async function salvar() {
    if (!config) return
    setSalvando(true)
    setAviso(null)
    try {
      setConfig((await api.put<Config>('/portal/config', config)).data)
      setAviso({ tipo: 'success', texto: 'Portal da família atualizado.' })
    } catch (e) {
      setAviso({ tipo: 'error', texto: mensagemDeErro(e, 'Não foi possível salvar.') })
    } finally {
      setSalvando(false)
    }
  }

  const alternar = (id: string) => setConfig(c => c && ({
    ...c, categorias: c.categorias.includes(id) ? c.categorias.filter(x => x !== id) : [...c.categorias, id],
  }))

  return (
    <section aria-labelledby="portal-config" className="space-y-4 rounded-card border border-border bg-card p-4">
      <div>
        <h2 id="portal-config" className="font-semibold text-foreground">Portal da família</h2>
        <p className="text-apoio text-muted-foreground">
          Escolha o que os familiares com portal liberado podem ver. Nada aparece enquanto o portal estiver desligado.
        </p>
      </div>
      {aviso && <Alert variant={aviso.tipo}>{aviso.texto}</Alert>}
      {config && (
        <>
          <label className="flex min-h-[44px] items-center gap-3 font-medium">
            <input type="checkbox" className="size-5" checked={config.ativo}
              onChange={e => setConfig({ ...config, ativo: e.target.checked })} />
            Portal ligado nesta instituição
          </label>
          <fieldset className="space-y-2" disabled={!config.ativo}>
            <legend className="text-sm font-semibold text-muted-foreground">O que a família pode ver</legend>
            {CATEGORIAS_PORTAL.map(c => (
              <label key={c.id} className="flex min-h-[44px] items-start gap-3">
                <input type="checkbox" className="mt-1 size-5" checked={config.categorias.includes(c.id)} onChange={() => alternar(c.id)} />
                <span><span className="font-medium">{c.rotulo}</span><span className="block text-apoio text-muted-foreground">{c.descricao}</span></span>
              </label>
            ))}
          </fieldset>
          <Button type="button" onClick={() => { void salvar() }} disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar portal'}</Button>
        </>
      )}
    </section>
  )
}
