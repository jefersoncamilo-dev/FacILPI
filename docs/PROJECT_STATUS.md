# Project Status — FacILPI

> Snapshot de referência para onboarding. Não é substituto da verificação do GitHub. Sempre confirme branch/Issue/PR/HEAD quando o estado atual for relevante.

## Base integrada de referência

Na criação deste documento, a linha integrada utilizada pelo projeto era `fase-3b/funcionarios-usuarios-vinculos`, com a cadeia Alembic chegando até `016_d3_admissao.py`. O estado pode avançar; consulte GitHub antes de iniciar trabalho.

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
- Projeção inicial de Meu Plantão.
- Matriz de permissões clínicas/institucionais.
- Admissão ponta a ponta.
- Infraestrutura de testes backend protegida contra uso do banco oficial.

## Estado funcional importante

### Prontuário longitudinal
D.4 é a próxima frente funcional em recuperação/correção no fluxo atual. O contrato aprovado o trata como projeção read-only de fatos oficiais, não como nova tabela genérica de eventos. Não assuma que D.4 está integrado sem verificar GitHub.

### Passagem de Plantão
D.5 permanece posterior ao Prontuário. Deve consumir fontes oficiais/projeções sem duplicar fonte clínica de verdade.

### Frontend
Existe frontend funcional, mas a consolidação visual/mobile-first definitiva ainda é uma etapa posterior ao hardening do núcleo operacional. Não iniciar redesign amplo dentro de uma Issue backend.

### CI / cloud / produção
Não assuma CI, homologação cloud ou produção como configurados/concluídos. Verifique a situação atual antes de qualquer ação operacional.

## Documentos históricos

`Project.md`, `Prompt.txt`, `README.md` e `config/*.md` foram criados na fase inicial e podem conter arquitetura ou instruções superadas. Use-os como referência histórica/parcial. Em conflito, prevalecem GitHub/código integrado, documentação atual em `docs/` e decisões posteriores registradas.

## Banco oficial

O projeto possui proteção explícita para que testes automatizados não utilizem bancos persistentes oficiais. Antes de qualquer teste ou migração, confirme os guards/fixtures atuais e o alvo de banco. Nunca trate um caminho de banco como descartável apenas pelo nome.

## Como atualizar este arquivo

Atualize somente em Issue de governança/documentação ou junto de uma mudança cujo escopo explicitamente inclua documentação de status. Registre fatos integrados, não relatórios ainda não mergeados. Evite transformar SHA temporário em regra permanente.
