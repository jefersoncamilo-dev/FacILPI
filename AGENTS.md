# AGENTS — FacILPI

## Objetivo

FacILPI é um SaaS de gestão para Instituições de Longa Permanência para Idosos (ILPI). O produto deve ser simples para usuários com pouca familiaridade com tecnologia, mobile-first, multi-tenant, modular, auditável, compatível com RBAC e preparado para integrações futuras sem transformar a ILPI em um sistema hospitalar por padrão.

## Fonte oficial da verdade

Quando o estado atual importar, use esta ordem:
1. GitHub: Issues, Pull Requests, commits, CI e branch/base oficiais.
2. Documentação versionada atual do repositório.
3. Decisões registradas no Control Tower.
4. Chats/agentes especializados.
5. Memória conversacional.

Nunca considere Issue, branch, teste, correção ou funcionalidade concluída apenas porque um agente relatou que concluiu. Confirme no GitHub.

## Documentação atual

Antes de implementar, leia apenas o necessário para a Issue:
- `docs/PROJECT_STATUS.md`: snapshot do estado integrado; confirme GitHub quando atualidade for crítica.
- `docs/PROJECT_GOVERNANCE.md`: fluxo de engenharia e gates.
- `docs/ARCHITECTURE.md`: arquitetura e fontes de verdade.
- `docs/DOMAIN_RULES.md`: regras funcionais consolidadas.
- `docs/ROADMAP.md`: macro atual.

`Project.md`, `Prompt.txt`, `README.md` e `config/*.md` nasceram na fase inicial. Continuam úteis como histórico e referência parcial, mas não substituem código, migrations, testes, Issues/PRs e os documentos atuais quando houver conflito.

## Fluxo obrigatório de engenharia

Necessidade → análise funcional → Issue → branch isolada → implementação → testes locais → Pull Request → revisão independente → homologação → aprovação humana → merge.

- Uma Issue = uma branch = um Pull Request, salvo decisão explícita registrada.
- Nunca escrever diretamente na branch base integrada.
- Nunca permitir dois writers simultâneos na mesma branch ou working tree.
- Não ampliar escopo silenciosamente.
- Preserve alterações não relacionadas.
- Problemas fora do escopo devem ser documentados separadamente.
- PLAN/READ_ONLY nunca autoriza BUILD.

## Checagem antes de qualquer escrita

Confirme:
- Issue autorizada.
- branch e base.
- HEAD esperado e HEAD atual.
- repositório/worktree correto.
- `git status --short`.
- comportamento atual e causa raiz.
- arquivos dentro e fora do escopo.
- impacto frontend, backend, banco/migrations, tenant, RBAC, autoria e auditoria.
- testes que comprovarão o comportamento.

Se houver divergência, pare e reporte. Não tente "consertar" a árvore com reset/clean/checkout destrutivo.

## Segurança e dados

Nunca:
- confiar em `ilpiId`/tenant enviado pelo frontend quando deve vir da sessão;
- confiar em autoria clínica/assistencial enviada pelo frontend quando deve vir da identidade autenticada;
- expor senha, hash, token, cookie, segredo ou connection string;
- remover filtro multi-tenant para simplificar;
- usar Platform Superuser como acesso clínico implícito;
- inferir permissões clínicas apenas pela profissão;
- apagar histórico clínico/assistencial concluído para facilitar correção;
- executar ação destrutiva em banco oficial, homologação ou produção;
- executar migrate/reset em banco persistente sem autorização explícita;
- permitir IA tomar decisão clínica automaticamente.

Cross-tenant deve evitar vazamento de existência; quando o contrato do módulo usar 404, preserve-o.

## Banco e testes

Bancos devem ser classificados explicitamente como `OFFICIAL`, `PRODUCTION`, `HOMOLOGATION` ou `DISPOSABLE_TEST` antes de ação destrutiva.

- `storage/app.db` e `backend/storage/app.db` são protegidos contra testes automatizados.
- Testes backend devem usar infraestrutura descartável/sintética e os guards já existentes.
- Não copiar, migrar, seedar ou depender do conteúdo do banco oficial em testes.
- Não alterar migrations históricas para acomodar nova funcionalidade; criar migration incremental quando necessária.
- SQLite e PostgreSQL descartáveis devem ser usados conforme o risco/escopo da mudança.

Sequência eficiente de validação:
1. teste específico afetado;
2. backend diretamente relacionado;
3. PostgreSQL descartável quando estrutura/tenant/RBAC/banco exigir;
4. uma regressão completa final, não após cada microcorreção.

Não enfraquecer testes, remover asserts, adicionar skip ou hardcode apenas para obter verde.

## Regra anti-loop

Escolha uma hipótese/abordagem baseada em evidência e execute-a. Não releia o repositório inteiro nem repita o mesmo teste sem nova informação.

Após uma correção justificada, rode o teste afetado. Se o mesmo problema persistir após no máximo duas tentativas sem nova evidência, pare, resuma a hipótese, evidências, mudanças e bloqueio. Não faça iteração aleatória.

Evite full regression repetida. Não indexe ou leia arquivos sem relação com a Issue. Use diffs, buscas e testes direcionados.

## Princípios funcionais

Pergunte sempre: "Se este dado for criado ou alterado aqui, onde ele deve repercutir no restante do sistema?"

Considere residente, familiares, prontuário, PAIS, rotina, agenda, medicamentos, alertas, dashboard, Meu Plantão, passagem de plantão, quarto/leito, estoque, financeiro, equipe e auditoria. Identificar repercussão não autoriza criar integração automática; automação exige justificativa operacional e escopo aprovado.

Fontes de verdade críticas devem permanecer únicas. Não criar dual-write apenas para compatibilidade aparente.

## Ações irreversíveis ou compartilhadas

Sem aprovação humana explícita, não executar `git reset --hard`, `git clean -fd/-fdx`, force push, amend de commit publicado, rebase de branch compartilhada, exclusão de branch remota, remoção recursiva de arquivos, `DROP`, `TRUNCATE`, DELETE em massa, reset de banco, `docker compose down -v`, remoção de volume persistente, deploy, merge de PR, fechamento de Issue ou alteração de segredo/credencial/infra compartilhada.

Quando uma ação desse tipo parecer necessária, pare e informe comando pretendido, motivo, impacto e rollback.

## Handoff obrigatório

Ao transferir trabalho, informe:

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

Nunca invente campos não confirmados.
