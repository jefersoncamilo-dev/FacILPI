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
6. Avalie impacto em frontend, backend, banco/migration, tenant, RBAC, autoria e auditoria.
7. Aplique a regra de repercussão entre módulos sem criar automações não autorizadas.
8. Defina a menor estratégia de BUILD e a sequência de testes.
9. Registre riscos, dúvidas e critérios de parada.

## Eficiência

- Não varra o repositório inteiro.
- Use `git diff`, busca por símbolos, migrations e testes relacionados antes de leitura ampla.
- Não execute full regression em PLAN.
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
Impactos:
Testes necessários:
Riscos/pendências:
Plano de BUILD:
Writer lock recomendado:

Finalize com `READY_FOR_DECISION`, nunca `READY_FOR_BUILD` por conta própria.
