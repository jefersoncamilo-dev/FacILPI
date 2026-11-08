import { useCallback, useEffect, useRef, useState } from 'react'
import { getProntuario, type ProntuarioCategoria, type ProntuarioEvento } from '../../services/prontuario'
import { ProntuarioLinhaDoTempo } from './ProntuarioLinhaDoTempo'
import { ProntuarioCarregando, ProntuarioErro } from './ProntuarioEstados'

/**
 * UX-NAV-3: linha do tempo do residente já recortada por categoria
 * (GET /residentes/{id}/prontuario?categoria=). O backend só devolve as origens
 * que a sessão pode ler; a tela não filtra permissão por conta própria.
 */
export function LinhaDoTempoCategoria({
  residenteId,
  categoria,
  titulo,
  vazio,
  versao = 0,
}: {
  residenteId: string
  categoria: ProntuarioCategoria
  titulo: string
  vazio: string
  versao?: number
}) {
  const [eventos, setEventos] = useState<ProntuarioEvento[] | null>(null)
  const [erro, setErro] = useState(false)
  const [cursor, setCursor] = useState<string | null>(null)
  const [carregandoMais, setCarregandoMais] = useState(false)
  const requisicao = useRef(0)

  const carregar = useCallback(() => {
    const n = ++requisicao.current
    setEventos(null)
    setErro(false)
    getProntuario(residenteId, { categoria, limit: 20 })
      .then(r => {
        if (n !== requisicao.current) return
        setEventos(r.items)
        setCursor(r.has_more ? r.next_cursor : null)
      })
      .catch(() => { if (n === requisicao.current) setErro(true) })
  }, [residenteId, categoria])

  useEffect(() => { carregar() }, [carregar, versao])

  async function mais() {
    if (!cursor || carregandoMais) return
    const n = requisicao.current
    setCarregandoMais(true)
    try {
      const r = await getProntuario(residenteId, { categoria, limit: 20, cursor })
      if (n !== requisicao.current) return
      setEventos(prev => [...(prev ?? []), ...r.items])
      setCursor(r.has_more ? r.next_cursor : null)
    } catch {
      setCursor(null)
    } finally {
      setCarregandoMais(false)
    }
  }

  return (
    <section aria-label={titulo} className="space-y-3">
      <h2 className="text-base font-semibold text-foreground">{titulo}</h2>
      {erro ? (
        <ProntuarioErro mensagem="Não foi possível carregar estes registros agora." onRetry={carregar} />
      ) : !eventos ? (
        <ProntuarioCarregando />
      ) : eventos.length === 0 ? (
        <p className="card py-6 text-center text-sm text-muted-foreground">{vazio}</p>
      ) : (
        <>
          <ProntuarioLinhaDoTempo eventos={eventos} />
          {cursor && (
            <div className="text-center">
              <button type="button" onClick={mais} disabled={carregandoMais} className="btn-secondary disabled:opacity-60">
                {carregandoMais ? 'Carregando…' : 'Carregar mais'}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
