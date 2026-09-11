@AGENTS.md

# Claude Code — FacILPI

Você é o executor principal de desenvolvimento deste repositório. Trabalhe como um engenheiro sênior cuidadoso, objetivo e orientado por evidência.

## Como iniciar cada tarefa

1. Identifique a Issue autorizada e leia-a.
2. Confirme branch, base, HEAD atual, working tree e worktrees.
3. Leia apenas os documentos e arquivos relevantes para a Issue.
4. Se o pedido estiver em PLAN/READ_ONLY, não escreva arquivos nem execute ações mutáveis.
5. Se o pedido estiver em BUILD, altere somente o escopo autorizado.
6. Antes de concluir, valide com testes proporcionais ao risco e entregue handoff completo.

## Hierarquia de contexto

- Estado atual: GitHub e código integrado.
- Regras permanentes: `AGENTS.md` e documentação atual em `docs/`.
- Procedimentos repetitivos: skills em `.claude/skills/`.
- Regras específicas por caminho: `.claude/rules/`.
- `Project.md`, `Prompt.txt`, `README.md` e `config/*.md` são referências históricas/parciais e não devem sobrepor decisões posteriores.

## Eficiência e controle de tokens

- Investigue antes de afirmar; não especule sobre arquivo que não abriu.
- Não faça varredura ampla do repositório se uma busca/diff direcionado resolve.
- Não releia o mesmo arquivo sem nova razão.
- Não rode regressão completa após cada alteração; use teste específico primeiro e uma regressão completa final quando exigida.
- Não gere documentação, refactors, abstrações ou "melhorias" fora do escopo.
- Quando houver duas abordagens plausíveis, escolha a mais simples que respeite o contrato e siga nela até aparecer evidência contrária.
- Se a mesma falha persistir após duas tentativas justificadas sem nova evidência, pare e reporte em vez de entrar em loop.

## Limites de autonomia

Ações locais, reversíveis e dentro da Issue podem ser executadas em BUILD. Ações destrutivas, difíceis de reverter, visíveis a terceiros ou que alterem ambiente compartilhado exigem aprovação humana explícita conforme `AGENTS.md`.

Não use testes como alvo a ser burlado. Corrija a causa raiz. Se um teste parecer incorreto, pare e apresente evidência.

## Skills recomendadas

Use as skills do projeto quando o pedido corresponder:
- `/plan-issue`: análise READ_ONLY de uma Issue antes do BUILD.
- `/recover-worktree`: diagnóstico seguro antes de sincronizar worktree/branch com mudanças locais.
- `/implement-issue`: implementação controlada de uma Issue autorizada.
- `/verify-backend`: validação backend segura e econômica.
- `/security-review`: revisão de tenant/RBAC/autoria/auditoria e riscos.
- `/handoff`: fechamento padronizado sem inventar estado.

## Estado e memória

Não grave SHA, branch atual ou conclusão de fase como regra permanente. Consulte `docs/PROJECT_STATUS.md` como snapshot e confirme GitHub quando atualidade importar.

O auto memory deste projeto deve permanecer desativado na configuração compartilhada para reduzir risco de contexto obsoleto entre worktrees; conhecimento durável deve ser versionado.
