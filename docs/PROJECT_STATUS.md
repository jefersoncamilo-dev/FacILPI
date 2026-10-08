# Project Status — FacILPI

> Snapshot de referência para onboarding. Não é substituto da verificação do GitHub. Sempre confirme branch/Issue/PR/HEAD quando o estado atual for relevante.

## Base integrada de referência

A linha integrada utilizada pelo projeto é `fase-3b/funcionarios-usuarios-vinculos`, com a cadeia Alembic chegando até `028_alerta_expirado` (021–027 vieram da Central de Alertas e da Camada Operacional, Fases 1–5; 028 do estado "expirado sem registro", #132). O estado pode avançar; consulte GitHub antes de iniciar trabalho.

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
- Infraestrutura de testes backend protegida contra uso do banco oficial.

## Estado funcional importante

### Prontuário longitudinal
D.4 é a próxima frente funcional em recuperação/correção no fluxo atual. O contrato aprovado o trata como projeção read-only de fatos oficiais, não como nova tabela genérica de eventos. Não assuma que D.4 está integrado sem verificar GitHub.

### Camada Operacional (Fases 1–5 integradas)
Fluxo diário completo: inicia plantão → área/residentes → prioridades/atividades → assume → resolve na origem → a fonte encerra → passagem → próximo turno confirma. Regras em `docs/DOMAIN_RULES.md`; visão e Fases 6–14 (fora do ciclo, sem design técnico) em `docs/ROADMAP.md`.

Decisões de produto aplicadas e publicadas (homologação técnica das Fases 1–5 concluída: apta para Produto/UX/UI):
- **#131 (PR #134):** alerta de dose e doses previstas (Central, Meu Plantão, passagem) só com permissão de medicação (`administracoes:ler`); `plantao:ler` sozinho não concede — cuidador e Administrador da ILPI não veem dose.
- **#132 (PR #133, migration 028):** cuidado/dose que sai da janela de 24 h sem registro encerra o estado do alerta como `expirado` (encerramento `janela`), nunca como "resolvido pela fonte".

As migrations 021–028 precisam ser aplicadas em ordem em qualquer ambiente persistente — decisão humana, nunca automática; no ambiente de homologação publicado a cadeia está em 028 (aplicada antes do deploy do #133).

### Meu Plantão — UX-01
Integrado (#139–#145): G1, G3, registro rápido (Realizado / Recusado / Não realizado, motivo obrigatório nas exceções), três visões e filtros, fila padrão a partir de 24 h atrás (atrasados visíveis), seleção múltipla, registro em lote (uma execução e uma auditoria por cuidado; "Marcar até 1 h" no atalho de grupo), cards compactos com foto/iniciais, Emergência (abre o prontuário), título com o nome do funcionário e grau ativo na fila para quem tem `plantao:ler` (o histórico do grau continua exigindo `grau_dependencia:ler`). Regras em `docs/DOMAIN_RULES.md`.

Não integrado: ditado por voz no aparelho (UX-01D, PR #144) e a tela de correção de registros (decisão A: Enfermagem, RT e administrador corrigem via estorno com `execucoes:corrigir`; cuidador registra mas não corrige; sem exclusão; só cuidados). G4 (percentual de refeição), G5 (concluídos/expirados) e G7 ("outro horário") seguem adiados.

### Auditoria geral (11/10/2026) — decisões e riscos conhecidos
- **Situação do residente:** a API ainda aceita `situacao`/`data_admissao` do cliente no cadastro e na edição genéricos; a decisão foi manter como está. Só a Admissão ativa o residente pelas telas atuais. Risco conhecido, não corrigido.
- **Adiados (exigem migration/RBAC):** autoria por FK em avaliações, sinais vitais e intercorrências (hoje nome em texto) e retirada das permissões clínicas de escrita do template `ilpi_admin` (herança das migrations 006–014).
- **Antes da VPS:** rate limit de login em memória por `client.host` (proxy/múltiplos workers), JWT em `localStorage` sem CSP.
- **Dependências:** vulnerabilidades restantes do `npm audit` exigem Tailwind 4 e React Router 7 (upgrades maiores, sem decisão).
- **Branches:** `main` está muitos commits atrás da linha integrada; a promoção para `main` ainda não tem critério definido.

### Passagem de Plantão
Persistida desde a Fase 4 (027) como registro do que foi comunicado, não fonte clínica: consome fontes oficiais/projeções sem duplicá-las. A integração com o Prontuário longitudinal (D.4) segue posterior.

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
O CI do GitHub Actions está configurado e é a validação integrada autoritativa: três jobs — `Frontend (testes, TypeScript, build)`, `Backend (SQLite)` e `Backend (PostgreSQL)`. Homologação cloud e produção **não** estão configuradas; a VPS é a próxima frente. Verifique a situação atual antes de qualquer ação operacional.

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
