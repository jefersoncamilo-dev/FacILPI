import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { usePermissoesOuPadrao } from '../context/PermissoesContext'

/**
 * UX-04 (#89): o que situa o residente na instituição, cada item lido da sua
 * fonte oficial e só se a sessão puder ler aquele módulo:
 *  - leito atual: quartos_leitos (ocupado = residente_atual_id);
 *  - ausência ativa: ausencias (data_fim nulo);
 *  - grau de dependência: graus-dependencia (situação "ativo"). O campo
 *    `grau_dependencia` do residente é legado congelado e NÃO é usado aqui.
 * Falha de uma fonte só omite aquele item — nunca inventa valor.
 */
export interface ContextoResidente {
  leito: string | null | undefined
  ausencia: { tipo: 'hospitalizacao' | 'saida_temporaria'; desde: string } | null | undefined
  grau: { classificacao: string; validade: string | null } | null | undefined
}
// undefined = sem permissão ou fonte indisponível (não exibir); null = consultado e inexistente.

type Leito = { id: string; quarto: string; leito: string; unidade?: string | null; residente_atual_id?: string | null }
type Ausencia = { tipo: 'hospitalizacao' | 'saida_temporaria'; data_inicio: string; data_fim: string | null }
type Grau = { classificacao: string; situacao: string; validade: string | null }

// Exceção síncrona (ex.: interceptor) vira rejeição e cai no .catch de quem chama.
function consultar<T>(url: string, config?: object) {
  return Promise.resolve().then(() => api.get<T>(url, config))
}

export function rotuloLeito(l: Pick<Leito, 'quarto' | 'leito' | 'unidade'>): string {
  return [l.unidade, `Quarto ${l.quarto}`, `Leito ${l.leito}`].filter(Boolean).join(' · ')
}

/** Mapa residente → leito atual, para listas (uma consulta só). */
export function useLeitosPorResidente(): Map<string, string> | undefined {
  const { pode, status } = usePermissoesOuPadrao()
  const [mapa, setMapa] = useState<Map<string, string>>()
  const podeLer = pode('quartos_leitos:ler')
  useEffect(() => {
    if (status === 'carregando' || status === 'sem_provider' || !podeLer) return
    consultar<Leito[]>('/quartos_leitos/', { params: { limit: 500 } })
      .then(r => setMapa(new Map((r.data || []).filter(l => l.residente_atual_id).map(l => [l.residente_atual_id as string, rotuloLeito(l)]))))
      .catch(() => setMapa(undefined))
  }, [status, podeLer])
  return mapa
}

export function useContextoResidente(residenteId?: string): ContextoResidente {
  const { pode, status } = usePermissoesOuPadrao()
  const [ctx, setCtx] = useState<ContextoResidente>({ leito: undefined, ausencia: undefined, grau: undefined })
  const podeLeito = pode('quartos_leitos:ler')
  const podeAusencia = pode('ausencias:ler')
  const podeGrau = pode('grau_dependencia:ler')

  useEffect(() => {
    if (!residenteId || status === 'carregando' || status === 'sem_provider') return
    setCtx({ leito: undefined, ausencia: undefined, grau: undefined })
    if (podeLeito) {
      consultar<Leito[]>('/quartos_leitos/', { params: { limit: 500 } })
        .then(r => {
          const l = (r.data || []).find(x => x.residente_atual_id === residenteId)
          setCtx(c => ({ ...c, leito: l ? rotuloLeito(l) : null }))
        })
        .catch(() => undefined)
    }
    if (podeAusencia) {
      consultar<Ausencia[]>('/ausencias/', { params: { residente_id: residenteId } })
        .then(r => {
          const a = (r.data || []).find(x => !x.data_fim)
          setCtx(c => ({ ...c, ausencia: a ? { tipo: a.tipo, desde: a.data_inicio } : null }))
        })
        .catch(() => undefined)
    }
    if (podeGrau) {
      consultar<Grau[]>('/graus-dependencia/', { params: { residente_id: residenteId } })
        .then(r => {
          const g = (r.data || []).find(x => x.situacao === 'ativo')
          setCtx(c => ({ ...c, grau: g ? { classificacao: g.classificacao, validade: g.validade } : null }))
        })
        .catch(() => undefined)
    }
  }, [residenteId, status, podeLeito, podeAusencia, podeGrau])

  return ctx
}

/** Idade em anos completos a partir da data de nascimento (sem alterar o dado). */
export function idade(dataNascimento?: string | null, hoje = new Date()): number | null {
  if (!dataNascimento) return null
  const [a, m, d] = dataNascimento.split('-').map(Number)
  if (!a || !m || !d) return null
  let anos = hoje.getFullYear() - a
  if (hoje.getMonth() + 1 < m || (hoje.getMonth() + 1 === m && hoje.getDate() < d)) anos -= 1
  return anos
}
