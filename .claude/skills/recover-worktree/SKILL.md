---
name: recover-worktree
description: Analisa e recupera com segurança uma branch/worktree FacILPI com alterações locais, divergência de base ou arquivos paralelos. Use antes de sync/rebase/merge quando houver working tree suja ou trabalho não commitado.
---

# Recuperação segura de worktree

Comece obrigatoriamente em READ_ONLY. A primeira execução desta skill nunca deve alterar arquivos, index, branch ou refs.

## Diagnóstico

1. Confirme `pwd` e raiz do repositório.
2. Capture branch, HEAD, `git status --short` e `git worktree list`.
3. Separe mudanças staged, unstaged e untracked.
4. Para cada arquivo alterado, classifique: trabalho da Issue atual, alteração paralela conhecida, mudança acidental ou ainda não classificada.
5. Compare a branch com a base remota/integrada autorizada.
6. Identifique conflitos prováveis antes de propor qualquer sync.
7. Preserve todos os arquivos não relacionados e especialmente trabalho não commitado.

## Proibições durante diagnóstico

Não executar `reset`, `clean`, `checkout --`, `restore`, `stash`, `merge`, `rebase`, `cherry-pick`, troca de branch, commit, push ou edição.

## Plano de recuperação

Produza comandos exatos e explique para cada um:
- o que muda;
- o que preserva;
- risco;
- rollback;
- pré-condição.

Só execute a fase mutável após aprovação humana explícita do plano.

## Regra anti-loop

Não tente múltiplas estratégias de Git em sequência. Escolha uma estratégia após o diagnóstico. Se aparecer estado diferente do previsto, pare e reavalie antes do próximo comando.
