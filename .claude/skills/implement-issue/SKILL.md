---
name: implement-issue
description: Implementa uma Issue FacILPI já autorizada em BUILD, preservando escopo, tenant, RBAC, autoria, histórico e writer lock. Use somente quando a implementação estiver explicitamente autorizada.
---

# BUILD controlado de Issue

Antes de editar, confirme que existe autorização explícita de BUILD e que Issue, branch, base e writer lock estão definidos.

## Pré-flight

- `pwd`
- `git rev-parse --show-toplevel`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short`
- `git worktree list`

Se repositório, branch, HEAD esperado ou working tree divergirem do autorizado, pare e reporte. Não use reset/clean/checkout destrutivo para corrigir.

## Implementação

1. Leia a Issue e o PLAN aprovado.
2. Abra somente código, migration e testes diretamente relacionados.
3. Faça a menor mudança que satisfaça o contrato.
4. Preserve alterações não relacionadas e arquivos não rastreados desconhecidos.
5. Não amplie escopo, não refatore por conveniência e não crie automações de negócio não autorizadas.
6. Mantenha tenant, autoria, RBAC, histórico e auditoria coerentes com as fontes de verdade atuais.
7. Se precisar mudar schema, use migration incremental e valide SQLite/PostgreSQL conforme aplicável.

## Validação e anti-loop

- Rode primeiro o teste específico.
- Corrija com hipótese explícita baseada no erro.
- Não repita a mesma tentativa sem nova evidência.
- Após duas tentativas justificadas com o mesmo sintoma sem progresso, pare e reporte.
- Rode testes históricos diretamente afetados.
- Faça uma única regressão completa no gate final quando exigida.
- Nunca enfraqueça teste para obter verde.

## Não autorizado automaticamente

Não fazer push, merge, fechar Issue, force push, reset hard, clean destrutivo, rebase compartilhado, remover volume, tocar banco oficial/homologação/produção ou alterar segredo/infra compartilhada sem aprovação explícita.

## Saída

Use o handoff padrão do projeto e informe exatamente o que foi alterado, testes executados, resultado, riscos e próxima ação. Não declare integração antes do merge confirmado no GitHub.
