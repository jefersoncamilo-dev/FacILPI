# Project Status — FacILPI

> Snapshot de referência para onboarding. Não é substituto da verificação do GitHub. Sempre confirme branch/Issue/PR/HEAD quando o estado atual for relevante.

## Base integrada de referência

A linha integrada utilizada pelo projeto é `fase-3b/funcionarios-usuarios-vinculos`, com a cadeia Alembic chegando até `027_passagem_plantao` (021–027 vieram da Central de Alertas e da Camada Operacional, Fases 1–5). O estado pode avançar; consulte GitHub antes de iniciar trabalho.

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
- Matriz de permissões clínicas/institucionais.
- Admissão ponta a ponta.
- Infraestrutura de testes backend protegida contra uso do banco oficial.

## Estado funcional importante

### Prontuário longitudinal
D.4 é a próxima frente funcional em recuperação/correção no fluxo atual. O contrato aprovado o trata como projeção read-only de fatos oficiais, não como nova tabela genérica de eventos. Não assuma que D.4 está integrado sem verificar GitHub.

### Camada Operacional (Fases 1–5 integradas)
Fluxo diário completo: inicia plantão → área/residentes → prioridades/atividades → assume → resolve na origem → a fonte encerra → passagem → próximo turno confirma. Regras em `docs/DOMAIN_RULES.md`; visão e Fases 6–14 (fora do ciclo, sem design técnico) em `docs/ROADMAP.md`.

Decisões de produto pendentes: (1) alerta de doses sem registro para o cuidador — hoje segue `plantao:ler`, como o Meu Plantão; (2) doses/cuidados que saem da janela de 24 h encerram o estado do alerta como "resolvido pela fonte" sem registro. As migrations 021–027 precisam ser aplicadas em ordem em qualquer ambiente persistente — decisão humana, nunca automática.

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
