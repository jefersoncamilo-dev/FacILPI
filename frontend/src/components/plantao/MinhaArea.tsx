import { Link } from 'react-router-dom'
import { ArrowRight, Inbox, UserRound } from 'lucide-react'
import { formatDateTime } from '../../services/api'
import type { MeuPlantaoResumo } from '../../services/meuPlantao'
import { plantaoDesde } from '../../services/alertas'
import { ItemAlerta } from '../alertas/ItemAlerta'

/**
 * "Minha área agora" (#126): o recorte do plantão pela responsabilidade — só
 * aparece com plantão ativo em alguma área e só com o que o perfil lê. As
 * ações levam ao módulo de origem; nenhum formulário é duplicado aqui.
 */
export function MinhaArea({ resumo, podeAssumir, onMudou }: { resumo: MeuPlantaoResumo; podeAssumir: boolean; onMudou: () => void }) {
  if (!resumo.plantao || resumo.areas.length === 0) return null
  const emAtencao = (resumo.residentes ?? []).filter(r => r.em_atencao)
  const partes = [
    resumo.areas.map(a => a.nome).join(', '),
    resumo.residentes !== null ? `${resumo.residentes.length} ${resumo.residentes.length === 1 ? 'residente' : 'residentes'}` : null,
    resumo.residentes !== null ? `${emAtencao.length} em atenção` : null,
    resumo.prioridades !== null ? `${resumo.prioridades.length} ${resumo.prioridades.length === 1 ? 'prioridade' : 'prioridades'}` : null,
  ].filter(Boolean)
  const atrasadas = resumo.atividades?.atrasadas ?? []
  const proximas = resumo.atividades?.proximas ?? []

  return (
    <section aria-label="Minha área agora" className="space-y-4 rounded-card border border-primary/40 bg-card p-4 shadow-card sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg font-semibold text-foreground">Minha área agora</h2>
        <p className="text-sm text-muted-foreground">{partes.join(' · ')}</p>
      </div>

      {resumo.passagens_a_receber !== null && resumo.passagens_a_receber > 0 && (
        <Link to="/passagem" className="flex min-h-[44px] items-center gap-2 rounded-md border border-orange-200 bg-orange-50 px-3 text-sm font-semibold text-orange-900">
          <Inbox className="size-4" aria-hidden="true" />
          {resumo.passagens_a_receber === 1 ? '1 passagem de plantão aguardando você' : `${resumo.passagens_a_receber} passagens de plantão aguardando você`}
          <ArrowRight className="ml-auto size-4" aria-hidden="true" />
        </Link>
      )}

      {emAtencao.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">Residentes em atenção</h3>
          <ul className="space-y-1">
            {emAtencao.map(r => (
              <li key={r.id} className="flex flex-wrap items-center gap-x-2 text-sm">
                <UserRound className="size-4 text-muted-foreground" aria-hidden="true" />
                <Link to={`/residentes/${r.id}`} className="inline-flex min-h-[44px] items-center font-medium text-primary hover:underline">{r.nome}</Link>
                {r.local && <span className="text-muted-foreground">{r.local}</span>}
                <span className="text-xs text-orange-800">{r.motivos.join(' · ')}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {resumo.prioridades !== null && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">Prioridades da área</h3>
          {resumo.prioridades.length === 0
            ? <p className="text-sm text-muted-foreground">Nada pedindo atenção na sua área agora.</p>
            : (
              <ul className="space-y-2">
                {resumo.prioridades.map(a => <li key={a.id}><ItemAlerta alerta={a} podeAssumir={podeAssumir} onMudou={onMudou} /></li>)}
              </ul>
            )}
        </div>
      )}

      {resumo.atividades !== null && (
        <div className="space-y-2">
          <p className="text-sm text-slate-700">
            Atividades da área: <span className="font-semibold">{atrasadas.length} atrasada{atrasadas.length === 1 ? '' : 's'}</span>
            {' · '}{proximas.length} nas próximas horas
            {proximas[0]?.previsto_em ? ` (a próxima às ${formatDateTime(proximas[0].previsto_em)})` : ''}.
          </p>
          {atrasadas.length > 0 && (
            <>
              <ul aria-label="Atividades atrasadas" className="space-y-1 text-sm">
                {atrasadas.map(a => (
                  <li key={a.registro_id}>
                    <span className="font-medium">{a.residente_nome ?? 'Residente'}</span>
                    {' · '}{a.origem === 'medicacao' ? 'Dose de medicação' : a.descricao}
                    {a.previsto_em ? ` · previsto ${formatDateTime(a.previsto_em)}` : ''}
                  </li>
                ))}
              </ul>
              <Link
                to={plantaoDesde(atrasadas[0].previsto_em)}
                className="inline-flex min-h-[44px] items-center gap-1 rounded-md bg-brand-soft px-3 text-sm font-semibold text-primary hover:underline"
              >
                Registrar as atrasadas <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </>
          )}
        </div>
      )}
    </section>
  )
}
