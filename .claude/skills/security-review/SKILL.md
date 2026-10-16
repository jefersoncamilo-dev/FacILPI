---
name: security-review
description: Faz revisão READ_ONLY de segurança funcional/técnica do FacILPI, com foco em tenant, RBAC, autoria, histórico, banco e vazamento cross-tenant.
---

# Security review

Trabalhe READ_ONLY salvo autorização explícita posterior para uma Issue de correção.

## Verifique

- Tenant deriva da sessão/contexto e está aplicado desde a consulta/mutação.
- Relações pai/filho validam mesmo tenant.
- Cross-tenant não revela existência.
- Autoria/executor clínico-assistencial deriva da identidade autenticada quando aplicável.
- RBAC é validado no backend e não inferido apenas pela profissão.
- Platform Superuser não obtém acesso clínico implícito.
- Histórico/correções não são destruídos por PUT/DELETE genérico quando o domínio exige versão/estorno/substituição.
- Não existem dual-writes para estados críticos.
- Migrations/constraints/FKs sustentam invariantes importantes quando necessário.
- Testes exercitam pelo menos happy path, sem permissão, cross-tenant e spoofing de tenant/autoria nos módulos críticos.
- Banco oficial e segredos não aparecem em fixtures, logs ou scripts de teste.

## Escopo

Não corrija achados durante a revisão. Para cada problema, forneça evidência, gravidade, impacto, arquivos envolvidos, teste que deveria comprovar a correção e proposta de Issue separada.

## Critério de parada e anti-loop

Não refaça a auditoria inteira a cada achado novo; registre o achado e continue cobrindo o restante do escopo. Não reabra ou reverifique uma evidência já confirmada nesta revisão sem fato novo. Ao cobrir todos os itens de "Verifique" e registrar os achados correspondentes, finalize a revisão. Se algo não puder ser confirmado após uma tentativa razoável, marque `NÃO CONFIRMADO` e siga para a conclusão em vez de insistir.

## Saída

Classifique cada achado como P0/P1/P2/P3 ou `SEM_ACHADO`, sem dramatizar. Diferencie falha confirmada, risco provável e oportunidade de melhoria.
