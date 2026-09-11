---
name: plan-issue
description: Analisa uma Issue do FacILPI em modo READ_ONLY antes de qualquer implementação. Use quando o usuário pedir PLAN, diagnóstico, escopo, causa raiz, riscos, arquivos ou estratégia de testes.
---

# PLAN de Issue

Trabalhe em READ_ONLY. Não edite arquivos, não crie commits, não mude branch, não rode migrações mutáveis e não execute comandos destrutivos.

## Sequência

1. Identifique Issue, branch esperada, base e objetivo.
2. Confirme repositório/worktree, branch, HEAD e `git status --short`.
3. Leia a Issue e apenas os documentos/arquivos necessários.
4. Descreva comportamento atual e causa raiz com evidência.
5. Liste arquivos provavelmente dentro do escopo e arquivos explicitamente fora.
6. Avalie explicitamente impacto em frontend, backend, banco/migration, multi-tenant, RBAC/permissões, autoria/identidade, auditoria, testes e documentação.
7. Para dado criado/alterado, verifique possíveis repercussões em residente, familiares, prontuário, PAIS, tarefas/rotina, agenda, medicação, alertas, dashboard, passagem de plantão, quarto/leito, estoque, financeiro, equipe e auditoria. Identificar repercussão não autoriza integração automática.
8. Classifique cada impacto como SIM, NÃO ou NÃO CONFIRMADO, com justificativa curta.
9. Defina quais documentos versionados precisam mudar se a Issue alterar arquitetura, contrato funcional, segurança, fluxo, permissões, banco, testes ou roadmap. Se nenhum, justifique.
10. Defina a menor estratégia de BUILD e a sequência de testes.
11. Registre riscos, dúvidas e critérios de parada.

## Eficiência

- Não varra o repositório inteiro.
- Use `git diff`, busca por símbolos, migrations e testes relacionados antes de leitura ampla.
- Não execute full regression em PLAN.
- Não reabra arquivo já analisado sem nova evidência ou dúvida concreta.
- Se uma informação crítica não puder ser confirmada, marque como não confirmada.

## Saída

Issue:
Branch esperada:
Base:
HEAD verificado:
Objetivo:
Comportamento atual:
Causa raiz:
Escopo permitido:
Fora de escopo:
Arquivos prováveis:
Impacto frontend:
Impacto backend:
Impacto banco/migration:
Impacto multi-tenant:
Impacto RBAC/permissões:
Impacto autoria/identidade:
Impacto auditoria:
Impacto testes:
Documentação impactada:
Repercussões entre módulos:
Testes necessários:
Riscos/pendências:
Plano de BUILD:
Writer lock recomendado:

Finalize com `READY_FOR_DECISION`, nunca `READY_FOR_BUILD` por conta própria.
