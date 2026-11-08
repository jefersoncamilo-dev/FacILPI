import { useCallback, useEffect, useState } from 'react'
import { api } from '../services/api'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'
import type { GrauDependencia } from '../services/avaliacoes'
import { grauDaApi, type GrauNaTela } from '../lib/grau'

const PAGINA = 100
// Teto de segurança: 20 páginas = 2.000 registros de grau (com histórico).
const MAX_PAGINAS = 20

type Estado = { status: 'sem_acesso' | 'carregando' | 'erro' } | { status: 'ok'; ativos: Map<string, string> }

/**
 * UX-GRAU: grau oficial ATIVO de cada residente da ILPI da sessão, a partir
 * de GET /graus-dependencia/ (paginado). Só consulta com `grau_dependencia:ler`
 * confirmada pelo backend; sem ela, `grauDe` devolve undefined (nada de cor
 * nem de ordem). Consultado e sem grau ativo → null ("Sem grau").
 * Nunca usa o campo legado `grau_dependencia` do residente.
 */
export function useGrausAtivos() {
  const { pode, status: permissoes } = usePermissoesOuPadrao()
  const podeLer = permissoes === 'ok' && pode('grau_dependencia:ler')
  const [estado, setEstado] = useState<Estado>({ status: podeLer ? 'carregando' : 'sem_acesso' })

  useEffect(() => {
    if (!podeLer) {
      setEstado({ status: 'sem_acesso' })
      return
    }
    let vivo = true
    setEstado({ status: 'carregando' })
    ;(async () => {
      const ativos = new Map<string, string>()
      for (let pagina = 0; pagina < MAX_PAGINAS; pagina++) {
        const { data } = await api.get<GrauDependencia[]>('/graus-dependencia/', { params: { skip: pagina * PAGINA, limit: PAGINA } })
        for (const g of data || []) if (g.situacao === 'ativo') ativos.set(g.residente_id, g.classificacao)
        if (!data || data.length < PAGINA) break
      }
      if (vivo) setEstado({ status: 'ok', ativos })
    })().catch(() => { if (vivo) setEstado({ status: 'erro' }) })
    return () => { vivo = false }
  }, [podeLer])

  const grauDe = useCallback(
    (residenteId: string): GrauNaTela => (estado.status === 'ok' ? grauDaApi(estado.ativos.get(residenteId) ?? null) : undefined),
    [estado],
  )

  return { status: estado.status, grauDe }
}
