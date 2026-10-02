import { useEffect, useRef, useState } from 'react'
import { Mic, Square } from 'lucide-react'
import { cn } from '../../lib/utils'

/**
 * UX-01D — ditado SÓ no aparelho.
 *
 * Fluxo: falar → transcrever → revisar o texto no campo → confirmar no botão
 * de salvar do formulário. O áudio nunca chega à página (a API de fala do
 * navegador só devolve texto): nada é gravado, anexado ou enviado ao backend
 * além do texto que a pessoa revisou e salvou. Nada é interpretado.
 *
 * Exigência de privacidade: reconhecimento LOCAL (`processLocally`). No modo
 * padrão os navegadores mandam o áudio para a nuvem do fabricante (Google,
 * Microsoft, Apple); por isso, sem o modo local disponível, o botão não
 * aparece — nunca há fallback para a nuvem.
 */

const IDIOMA = 'pt-BR'

type Disponibilidade = 'unavailable' | 'downloadable' | 'downloading' | 'available'

interface ReconhecimentoLocal {
  lang: string
  continuous: boolean
  interimResults: boolean
  processLocally?: boolean
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
  start: () => void
  stop: () => void
}

interface ConstrutorReconhecimento {
  new (): ReconhecimentoLocal
  available?: (o: { langs: string[]; processLocally: boolean }) => Promise<Disponibilidade>
  install?: (o: { langs: string[]; processLocally: boolean }) => Promise<boolean>
}

function construtor(): ConstrutorReconhecimento | null {
  const w = window as unknown as { SpeechRecognition?: ConstrutorReconhecimento; webkitSpeechRecognition?: ConstrutorReconhecimento }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

/** Só 'available'/'downloadable' com processamento local; qualquer dúvida = indisponível. */
export async function disponibilidadeLocal(): Promise<Disponibilidade> {
  const SR = construtor()
  if (!SR || typeof SR.available !== 'function') return 'unavailable'
  try {
    return await SR.available({ langs: [IDIOMA], processLocally: true })
  } catch {
    return 'unavailable'
  }
}

/**
 * Botão "Ditar" que acrescenta o texto reconhecido ao campo (`onTexto`). Fica
 * oculto quando o aparelho não transcreve localmente.
 */
export function BotaoDitar({ onTexto, rotulo }: { onTexto: (texto: string) => void; rotulo: string }) {
  const [estado, setEstado] = useState<Disponibilidade | 'verificando'>('verificando')
  const [ouvindo, setOuvindo] = useState(false)
  const [aviso, setAviso] = useState('')
  const rec = useRef<ReconhecimentoLocal | null>(null)

  useEffect(() => {
    let vivo = true
    void disponibilidadeLocal().then(d => { if (vivo) setEstado(d) })
    return () => { vivo = false; rec.current?.stop() }
  }, [])

  if (estado !== 'available' && estado !== 'downloadable') return null

  async function alternar() {
    if (ouvindo) { rec.current?.stop(); return }
    const SR = construtor()
    if (!SR) return
    setAviso('')
    if (estado === 'downloadable') {
      // Pacote de voz baixado UMA vez para o aparelho; o reconhecimento segue local.
      setAviso('Preparando a voz no aparelho…')
      const ok = await SR.install?.({ langs: [IDIOMA], processLocally: true }).catch(() => false)
      if (!ok) { setAviso('Não foi possível preparar a voz neste aparelho.'); return }
      setEstado('available')
    }
    const r = new SR()
    // Garantia de privacidade: sem a propriedade, o navegador poderia usar a nuvem.
    if (!('processLocally' in r)) { setEstado('unavailable'); return }
    r.processLocally = true
    r.lang = IDIOMA
    r.continuous = true
    r.interimResults = false
    let texto = ''
    r.onresult = e => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) texto += `${texto ? ' ' : ''}${e.results[i][0].transcript.trim()}`
      }
    }
    r.onerror = e => setAviso(e.error === 'not-allowed' ? 'Permita o microfone para ditar.' : 'Não foi possível transcrever. Tente de novo ou digite.')
    r.onend = () => {
      setOuvindo(false)
      rec.current = null
      if (texto.trim()) {
        onTexto(texto.trim())
        setAviso('Texto ditado. Revise antes de salvar.')
      }
    }
    rec.current = r
    setOuvindo(true)
    setAviso('Ouvindo… toque em Parar quando terminar.')
    r.start()
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={() => void alternar()}
        aria-pressed={ouvindo}
        aria-label={ouvindo ? `Parar ditado — ${rotulo}` : `Ditar — ${rotulo}`}
        className={cn(
          'inline-flex min-h-[44px] items-center gap-2 rounded-lg border px-3 text-sm font-medium',
          ouvindo ? 'border-red-300 bg-red-50 text-red-800' : 'border-border hover:bg-muted',
        )}
      >
        {ouvindo ? <Square className="size-4" aria-hidden="true" /> : <Mic className="size-4" aria-hidden="true" />}
        {ouvindo ? 'Parar' : 'Ditar'}
      </button>
      {aviso && <span className="text-sm text-muted-foreground" role="status">{aviso}</span>}
    </div>
  )
}
