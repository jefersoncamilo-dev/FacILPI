# Architecture — FacILPI

## Visão

FacILPI é um SaaS multi-tenant para ILPIs. O backend concentra regras de negócio, autorização, tenant, autoria, persistência e integrações. O frontend é cliente da API e não deve duplicar autoridade do backend.

## Stack principal

- Backend: FastAPI + SQLAlchemy + Alembic.
- Banco: SQLite local e PostgreSQL compatível para validação/produção conforme ambiente.
- Frontend: React + Vite + Tailwind.
- Infraestrutura: Docker/Compose conforme ambiente autorizado.

## Isolamento multi-tenant

O tenant efetivo deve ser derivado da sessão/contexto de segurança autenticado. Identificadores de ILPI enviados pelo cliente não substituem o contexto do backend quando a regra do módulo exige tenant da sessão.

Consultas e mutações tenant-scoped devem filtrar pelo tenant desde a origem da operação. Relações pai/filho também precisam ser validadas no mesmo tenant. Cross-tenant não deve revelar existência de registros.

## Identidade e autoria

`User` representa autenticação/identidade. `Funcionario` representa a pessoa que atua na ILPI. Vínculos e perfis determinam contexto institucional e permissões.

Autoria técnica, executor assistencial/clínico e usuário que realiza ações devem vir da identidade autenticada quando o contrato assim define. Responsável, designado, revisor e aprovador são papéis funcionais distintos e não devem ser confundidos com executor/autoria.

## RBAC

Permissões são verificadas no backend. Profissão não implica permissão automática. Perfis clínicos/institucionais devem ser atribuídos explicitamente. Platform Superuser administra a plataforma, mas não recebe acesso clínico implícito a tenants.

## Fontes de verdade

Preserve uma única fonte oficial para estados críticos. Evite dual-write e cópias derivadas que possam divergir.

Exemplos consolidados:
- Grau de dependência oficial: histórico específico de graus de dependência, não o campo legado do Residente.
- PAIS: `planos_cuidados` + necessidades + metas + intervenções.
- Rotina assistencial: programação → ocorrência → execução.
- Medicação: medicamento → prescrição → programação → dose prevista → administração.
- Prontuário longitudinal: projeção/agregação de fontes oficiais, não nova fonte de verdade.
- Meu Plantão: projeção operacional, não entidade clínica central.

## Histórico e correção

Registros clínicos/assistenciais históricos não devem ser fisicamente apagados para corrigir informação. Cada módulo deve preservar seu contrato: nova versão, novo registro, estorno/substituição, encerramento ou revogação, conforme o caso.

## PAIS e rotina

Fluxo conceitual:

`PAIS → Necessidade → Meta → Intervenção → Programação → Ocorrência → Execução`

Programação define o cuidado esperado. Ocorrência representa uma realização prevista/materializada. Execução registra o que efetivamente ocorreu. O profissional designado pode ser diferente do executor autenticado.

## Medicação

Fluxo conceitual:

`Medicamento → Prescrição → Programação → Dose Prevista → Administração`

Dose Prevista não é uma tarefa assistencial genérica. Administração possui autoria/executor próprio. Correções devem preservar histórico. Não introduzir classificação automática de adiantamento/atraso ou movimentação de estoque sem contrato aprovado.

## Quarto/leito e presença

Ocupação estrutural de leito e presença física do residente são conceitos distintos. Ausência temporária/hospitalização não deve ser confundida automaticamente com desocupação estrutural.

## Prontuário, Meu Plantão, Passagem e Auditoria

São conceitos distintos:

`Meu Plantão ≠ Prontuário ≠ Passagem de Plantão ≠ Auditoria`

- Meu Plantão: visão operacional do que exige atenção/ação no turno.
- Prontuário: linha longitudinal de fatos oficiais do residente.
- Passagem de Plantão: síntese/transferência entre turnos, preservando origem dos fatos.
- Auditoria: trilha técnica de ações e mudanças.

## Integrações entre módulos

Sempre avaliar repercussões de um novo dado em residente, família, prontuário, PAIS, rotina, agenda, medicação, alertas, dashboard, Meu Plantão, passagem, quarto/leito, estoque, financeiro, equipe e auditoria.

Essa análise não autoriza automação. Integração automática só deve existir quando houver justificativa operacional e escopo aprovado.
