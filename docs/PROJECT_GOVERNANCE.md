# Project Governance — FacILPI

## Authority order

1. GitHub Issues, Pull Requests, commits and CI.
2. Current versioned documentation in the repository.
3. Control Tower decisions.
4. Specialized project chats/agents.
5. Conversational memory.

When the current state matters, verify GitHub. A report from an agent is evidence to review, not proof of integration.

## Standard delivery flow

Need → functional analysis → GitHub Issue → isolated branch/worktree → implementation → targeted tests → Pull Request → independent review → homologation → human approval → merge → production when authorized.

## Writer lock

Only one writer may change a branch/worktree at a time. Reviewers should work READ_ONLY or on separate isolated branches/worktrees. Never let two agents write concurrently to the same worktree.

## Gates

### PLAN / READ_ONLY
Use to understand behavior, root cause, scope, risks, files and tests. No writes, commits, migrations, destructive commands or environment changes.

### BUILD
Requires an authorized Issue, branch, base and writer lock. Modify only the approved scope. Preserve unrelated work.

### VALIDATION
Start with the smallest proof. Add PostgreSQL/disposable integration validation when relevant. Use one final full regression gate when required.

### COMMIT / PR
Commit only scoped changes. Open a PR against the explicitly authorized base. Do not merge merely because tests are green.

### INTEGRATION
Merge only after review and approval. Reconfirm head SHA when merge locking matters.

## Before writing

Confirm Issue, branch, base, expected/current HEAD, working tree/worktrees, current behavior, root cause, allowed files, frontend/backend/database impact, multi-tenant impact, RBAC, authorship/audit and required tests.

If any critical target is unclear or divergent, stop and report rather than auto-correcting repository state.

## Out-of-scope findings

Do not fix silently. Record evidence and propose a separate Issue. Preserve the current Issue's scope.

## Irreversible/shared actions

Human approval is required before force push, hard reset, destructive clean, shared rebase, published amend, remote branch deletion, destructive database actions, persistent Docker volume removal, deploy, merge, closing Issues, or modifying shared secrets/infrastructure.

## Mandatory handoff

Issue:
Branch:
Base:
Objetivo:
Escopo permitido:
O que foi confirmado:
Arquivos alterados:
Testes executados:
Resultado:
Riscos/pendências:
Próxima ação:
Writer lock atual:

Never invent missing values.
