---
name: review-pr
description: Fazer revisão independente READ_ONLY de Pull Request do FacILPI, verificando escopo, causa raiz, segurança, testes, migrations e documentação sem modificar a branch revisada.
---

# Review PR

## Modo obrigatório
READ_ONLY / REVIEW_ONLY. O revisor não escreve na branch que está revisando.

## Antes da revisão
1. Confirme Issue, PR, branch head, base e SHAs atuais no GitHub.
2. Leia a Issue e critérios de aceite.
3. Analise o diff da PR antes de abrir arquivos fora do escopo.
4. Não confie apenas no relatório do implementador.

## Checklist
- O diff resolve a Issue sem ampliar escopo?
- A causa raiz foi tratada?
- Há alterações não relacionadas?
- Tenant vem da sessão e cross-tenant não vaza existência?
- Autoria/executor vêm da identidade autenticada quando aplicável?
- RBAC respeita menor privilégio e Platform Superuser não ganha acesso clínico implícito?
- Histórico/auditoria foram preservados?
- Migration nova é necessária e segura? Se houver migration, use também `/review-migration`.
- Testes comprovam comportamento e não foram enfraquecidos?
- SQLite/PostgreSQL foram cobertos quando o risco exigir?
- Banco oficial e ambientes compartilhados permaneceram protegidos?
- Documentação impactada foi atualizada ou a ausência foi justificada?
- Frontend/backend/Prisma-banco/multi-tenant/RBAC/autoria/auditoria foram avaliados explicitamente?

## Anti-loop
Não refaça toda a auditoria após cada achado. Registre evidência concreta por arquivo/trecho. Se faltar evidência, marque como não confirmado em vez de especular.

## Saída
Classifique como APPROVE_CANDIDATE, CHANGES_REQUIRED ou BLOCKED. Liste achados por severidade, evidência, impacto, correção esperada e testes necessários. Não faça merge, não feche Issue e não altere código.
