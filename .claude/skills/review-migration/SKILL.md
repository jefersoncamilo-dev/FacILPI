---
name: review-migration
description: Revisar migrations Alembic do FacILPI em modo READ_ONLY, com foco em segurança, compatibilidade SQLite/PostgreSQL, tenant, histórico e rollback. Use antes de aprovar migrations novas ou quando uma Issue tocar schema/banco.
---

# Review Migration

## Modo padrão
READ_ONLY / REVIEW_ONLY. Não altere migration, schema, banco ou código durante a revisão.

## Pré-condições
1. Identifique Issue, branch, base e migration alvo.
2. Confirme que a migration é nova/incremental. Nunca reescreva migration histórica integrada.
3. Classifique qualquer banco envolvido como OFFICIAL, PRODUCTION, HOMOLOGATION ou DISPOSABLE_TEST.
4. Nunca execute operação destrutiva fora de DISPOSABLE_TEST validado positivamente.

## Revisar
- `revision` e `down_revision` coerentes com a cadeia atual.
- upgrade e downgrade explícitos e seguros.
- constraints, índices, FKs e uniques necessários.
- integridade multi-tenant e FKs compostas quando aplicável.
- preservação de histórico e ausência de DELETE físico indevido.
- idempotência quando o contrato da fase exigir.
- compatibilidade SQLite e PostgreSQL 16.
- RBAC/grants sem escalada automática, especialmente Platform Superuser.
- ausência de segredo, URL real ou dependência do banco oficial.
- impacto sobre dados existentes e possibilidade de rollback.

## Validação recomendada
Somente se a Issue autorizar execução: SQLite descartável específico → PostgreSQL descartável específico → testes diretamente afetados. Regressão completa apenas no gate final, não durante cada tentativa.

## Critério de parada
Se houver risco de perda de dados, cadeia Alembic ambígua, necessidade de tocar banco não descartável ou decisão funcional não congelada, pare e reporte. Não improvise correção.

## Saída
Informe PASS/BLOCKED, evidências, riscos, testes necessários, documentação impactada e próxima ação. Não declare migration integrada sem confirmação do GitHub.
