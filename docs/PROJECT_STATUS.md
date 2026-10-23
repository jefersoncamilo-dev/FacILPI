# Project Status — FacILPI

> Snapshot de referência para onboarding. Não é substituto da verificação do GitHub. Sempre confirme branch/Issue/PR/HEAD quando o estado atual for relevante.

## Base integrada de referência

A linha integrada utilizada pelo projeto é `fase-3b/funcionarios-usuarios-vinculos`, com a cadeia Alembic chegando até `030_saida_residente` (021–027 vieram da Central de Alertas e da Camada Operacional, Fases 1–5; 028 do estado "expirado sem registro", #132; 029 da autoria por usuário; 030 da saída do residente). A 029 foi para a `main` na v0.6.0 (PR #160); a aplicação na homologação está pendente de confirmação humana (`docs/RUNBOOK_HOMOLOGACAO.md`). O estado pode avançar; consulte GitHub antes de iniciar trabalho.

## Capacidades integradas confirmadas na linha de referência

- Fundação FastAPI/SQLAlchemy/Alembic e frontend React/Vite/Tailwind.
- Autenticação/bootstrap e contexto de segurança.
- RBAC e perfis.
- Isolamento multi-tenant.
- Funcionários, usuários e vínculos.
- Residentes.
- Familiares/responsáveis.
- Documentos.
- Quarto/leito, ocupação, ausências e histórico.
- Avaliações.
- Grau de dependência com histórico e confirmação humana.
- Sinais vitais.
- Intercorrências.
- Medicação: medicamento, prescrição, programação, dose prevista e administração.
- Plano de Cuidados/PAIS: plano, necessidades, metas e intervenções.
- Rotina assistencial: programação, ocorrência e execução.
- Central de Alertas e Pendências: projeção calculada a cada consulta, RBAC por origem, ID estável, natureza/prazo e localização mínima (021–023).
- Estado persistente do alerta: assumir, em atendimento, liberar; resolução só pela fonte (026).
- Escala operacional: áreas, turnos, plantão real e responsabilidade temporal append-only (024); escala planejada × plantão real, ausência, substituição simples e cobertura (025).
- Passagem de plantão persistida: resumo montado pelo servidor, observações curtas e recebimento com a situação atual da fonte (027).
- Meu Plantão como destino operacional do turno (área, residentes, prioridades, atividades, passagens a receber) e pós-login.
- Meu Plantão operacional (UX-00/UX-01, #138–#145): registro rápido de cuidado, visões por horário/cuidado/residente, filtros, seleção múltipla e registro em lote com persistência individual; local do residente (G3) e grau de dependência ativo (decisão C) na própria fila; horizonte de cuidados e doses renovado na leitura (G1, #139).
- Matriz de permissões clínicas/institucionais.
- Admissão ponta a ponta.
- Saída do residente (N2, #171, migration 030): óbito, transferência, desligamento e retorno à família, com estorno; regras em `docs/DOMAIN_RULES.md`.
- Infraestrutura de testes backend protegida contra uso do banco oficial.

## Estado funcional importante

### Prontuário longitudinal
As Issues do D.4 (#21 backend, #27 frontend) estão fechadas. O contrato aprovado o trata como projeção read-only de fatos oficiais, não como nova tabela genérica de eventos. O PLAN do M20 (20/10/2026) confirmou a aderência ao contrato (paginação por cursor no SQL, um evento por transição, estornos e substituições visíveis). A Passagem de Plantão não entra no prontuário. N1 (#169): cada evento traz `autor_id` (UUID ou nulo) e `autor_nome` resolvido no servidor, com o nome em texto como fallback antes da 029; só o PAIS tem link de tela (`/plano/:id`), as demais origens vêm sem link. Follow-ups: #163, #164, #165 e #166.

### Camada Operacional (Fases 1–5 integradas)
Fluxo diário completo: inicia plantão → área/residentes → prioridades/atividades → assume → resolve na origem → a fonte encerra → passagem → próximo turno confirma. Regras em `docs/DOMAIN_RULES.md`; visão e Fases 6–14 (fora do ciclo, sem design técnico) em `docs/ROADMAP.md`.

Decisões de produto aplicadas e publicadas (homologação técnica das Fases 1–5 concluída: apta para Produto/UX/UI):
- **#131 (PR #134):** alerta de dose e doses previstas (Central, Meu Plantão, passagem) só com permissão de medicação (`administracoes:ler`); `plantao:ler` sozinho não concede — cuidador e Administrador da ILPI não veem dose.
- **#132 (PR #133, migration 028):** cuidado/dose que sai da janela de 24 h sem registro encerra o estado do alerta como `expirado` (encerramento `janela`), nunca como "resolvido pela fonte".

As migrations 021–028 precisam ser aplicadas em ordem em qualquer ambiente persistente — decisão humana, nunca automática; no ambiente de homologação publicado a cadeia está em 028 (aplicada antes do deploy do #133).

### Meu Plantão — UX-01
Integrado (#139–#145): G1, G3, registro rápido (Realizado / Recusado / Não realizado, motivo obrigatório nas exceções), três visões e filtros, fila padrão a partir de 24 h atrás (atrasados visíveis), seleção múltipla, registro em lote (uma execução e uma auditoria por cuidado; "Marcar até 1 h" no atalho de grupo), cards compactos com foto/iniciais, Emergência (abre o prontuário), título com o nome do funcionário e grau ativo na fila para quem tem `plantao:ler` (o histórico do grau continua exigindo `grau_dependencia:ler`). Regras em `docs/DOMAIN_RULES.md`.

Também integrado: ditado por voz no aparelho (UX-01D, #144). Correção de registros (UX-01F, decisão A): Enfermagem, RT e administrador corrigem via estorno com `execucoes:corrigir` no próprio Meu Plantão; cuidador registra mas não corrige; sem exclusão; só cuidados — confirme no GitHub se o PR já foi integrado. G4 (percentual de refeição), G5 (concluídos/expirados) e G7 ("outro horário") seguem adiados.

### Auditoria geral (11/10/2026) — decisões e riscos conhecidos
- **Situação do residente:** fora do contrato de escrita desde o M14 (#172): o cadastro nasce "Em admissao", só a Admissão ativa e só a saída (N2, #171) tira de "Ativo"; `situacao`/`data_admissao` enviados no cadastro ou na edição genéricos são ignorados.
- **Autoria por FK:** integrada em avaliações, sinais vitais e intercorrências (029, PR #158); o nome em texto segue como foto. A exibição legível no prontuário é o N1.
- **Adiado (exige migration/RBAC):** retirada das permissões clínicas de escrita do template `ilpi_admin` (herança das migrations 006–014).
- **Borda (SEC-02):** o IP real do cliente já chega ao backend atrás do Caddy (`FORWARDED_ALLOW_IPS` restrito à rede `edge_api`, ENV-1/HIGH-1), e o uvicorn roda com 1 worker — o rate limit de login em memória vale para o processo inteiro; com mais workers ele precisaria de armazenamento compartilhado. A CSP está no `docker/Caddyfile`, medida contra o build de produção. O JWT segue em `localStorage`; a CSP sem script inline reduz o risco, e a saída para cookie fica como decisão futura.
- **Dependências:** vulnerabilidades restantes do `npm audit` exigem Tailwind 4 e React Router 7 (upgrades maiores, sem decisão).
- **Branches:** a `main` foi promovida a partir da linha integrada pelo PR #160 (20/10/2026, v0.6.0), com conteúdo igual ao da `fase-3b`. A `fase-3b` continua sendo a linha integrada; a `main` só avança por promoção.

### Critério de promoção para a `main` (decisão D4, 20/10/2026)
Uma promoção da `fase-3b` para a `main` exige:
1. os três jobs de CI verdes (Frontend, Backend SQLite, Backend PostgreSQL);
2. homologação com contas sintéticas;
3. migrations aplicadas em ordem no ambiente de homologação, por decisão humana;
4. aprovação explícita do responsável no PR de promoção.

### Passagem de Plantão
Persistida desde a Fase 4 (027) como registro do que foi comunicado, não fonte clínica: consome fontes oficiais/projeções sem duplicá-las. Não integra o Prontuário longitudinal (decisão do M20).

### Frontend
Existe frontend funcional, mas a consolidação visual/mobile-first definitiva ainda é uma etapa posterior ao hardening do núcleo operacional. Não iniciar redesign amplo dentro de uma Issue backend.

### Backup, cópia off-host e disaster recovery
```
OFF_HOST_COPY              = VERIFIED
OFF_HOST_RECOVERY_CHAIN    = VERIFIED
POSTGRES_DISASTER_RESTORE  = VERIFIED
DISASTER_RECOVERY_OFF_HOST = VERIFIED
BACKUP_DR                  = CLOSED
READY_FOR_VPS              = YES
```

Provado de ponta a ponta com dados **sintéticos**, com o ambiente de origem destruído no meio do ensaio: `pg_dump -Fc` real → `age` → Backblaze B2 com Object Lock COMPLIANCE → verificação independente por credencial read-only separada → destruição da origem (containers e volumes em zero, payload local apagado) → recuperação **exclusivamente** off-host → `pg_restore` em PostgreSQL novo → validação pela aplicação: contagens iguais à linha de base, SHA-256 do anexo conferido contra `documentos.arquivo_hash`, download autenticado íntegro e token do ambiente anterior rejeitado.

Ferramental: `ops/backup.sh`, `ops/restore.sh`, `ops/offhost_upload.sh`, `ops/offhost_verify.sh`, `ops/offhost_fetch.sh` e `ops/drill/*`, com suíte dirigida em `ops/offhost_test.sh`. Operação e custódia em `docs/RUNBOOK_BACKUP_RESTORE.md` e `docs/RUNBOOK_OFFHOST.md`.

Pendências conhecidas desta frente, **nenhuma bloqueando a VPS**: lifecycle rule do bucket (GATE-5), instalação na VPS (GATE-7) e os testes negativos de `DeleteObject` do GATE-6, não executados porque DELETE permaneceu proibido em todos os gates.

### CI / cloud / produção
O CI do GitHub Actions está configurado e é a validação integrada autoritativa: três jobs — `Frontend (testes, TypeScript, build)`, `Backend (SQLite)` e `Backend (PostgreSQL)`. Existe uma homologação publicada (`docs/RUNBOOK_HOMOLOGACAO.md`): API e frontend no Render, publicados automaticamente **a partir da `main`** (desde 16/10/2026; antes publicavam a `fase-3b`), banco PostgreSQL no Neon (cadeia em 028 no último registro; confirmar se a 029 já foi aplicada). A `v0.5.0` (`aa2bd10`) foi a primeira versão promovida, e a v0.6.0 veio pelo PR #160 (sem release publicada no GitHub); o frontend publicado tem os cabeçalhos de segurança do SEC-02. Produção não está configurada; a VPS com o `docker-compose.yml` (Caddy + PostgreSQL próprio, `docs/RUNBOOK_PILOT.md`) é a frente seguinte. Verifique a situação atual antes de qualquer ação operacional.

```
FEATURE_FREEZE = ACTIVE
PILOT_GO       = NOT_EVALUATED
REAL_DATA      = BLOCKED
```

## Documentos históricos

`Project.md`, `Prompt.txt`, `README.md` e `config/*.md` foram criados na fase inicial e podem conter arquitetura ou instruções superadas. Use-os como referência histórica/parcial. Em conflito, prevalecem GitHub/código integrado, documentação atual em `docs/` e decisões posteriores registradas.

## Banco oficial

O projeto possui proteção explícita para que testes automatizados não utilizem bancos persistentes oficiais. Antes de qualquer teste ou migração, confirme os guards/fixtures atuais e o alvo de banco. Nunca trate um caminho de banco como descartável apenas pelo nome.

## Como atualizar este arquivo

Atualize somente em Issue de governança/documentação ou junto de uma mudança cujo escopo explicitamente inclua documentação de status. Registre fatos integrados, não relatórios ainda não mergeados. Evite transformar SHA temporário em regra permanente.
