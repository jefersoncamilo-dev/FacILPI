# Roadmap — FacILPI

> Macro atual de referência. O GitHub continua sendo a fonte oficial de estado. Não trate itens planejados como concluídos.

## 1. Fundação e segurança — integrada

Base técnica, autenticação, identidade, tenant, RBAC, auditoria e vínculos institucionais.

## 2. Cadastros seguros — integrada

Residentes, familiares, documentos, quarto/leito, ocupações e ausências com isolamento tenant e histórico.

## 3. Núcleo clínico/assistencial — integrado

Avaliações, grau de dependência, sinais vitais, intercorrências e medicação.

## 4. PAIS e rotina assistencial — integrada

Plano de Cuidados/PAIS, necessidades, metas, intervenções, programação, ocorrências, execuções e projeção inicial de Meu Plantão.

## 5. Matriz institucional de permissões — integrada

Perfis clínicos/institucionais explícitos. Profissão não concede permissão automaticamente. Platform Superuser não recebe acesso clínico implícito.

## 6. Admissão ponta a ponta — integrada

Fluxo próprio de Admissão ligado às fontes oficiais de Residente, documentos, avaliações, quarto/leito e PAIS.

## 7. D.4 — Prontuário longitudinal — próximo gate funcional

Implementar/corrigir como projeção read-only das fontes oficiais, com paginação/cursor real, eventos historicamente honestos e sem tabela duplicadora de prontuário.

Antes do BUILD, recuperar/sincronizar com segurança a worktree/branch de D.4 e preservar alterações locais autorizadas.

## 8. D.5 — Passagem de Plantão

Planejar e implementar após D.4. Usar fatos oficiais e contexto operacional sem criar fonte clínica paralela.

A passagem persistida (encerramento, itens, recebimento) passou a ser a **Fase 4 da Camada Operacional** (seção 16). A UX-09 atual continua como prévia ao vivo.

## 9. Hardening integrado do núcleo

Validar fluxos de ponta a ponta entre:

`Residente → Admissão → PAIS → Rotina → Medicação → Intercorrências → Prontuário → Meu Plantão → Passagem de Plantão`

Resolver inconsistências reais em Issues separadas. Não expandir módulos só para aproveitar contexto.

## 10. Decisão sobre planos históricos pendentes

Revisar formalmente artefatos de PLAN antigos/locais, incluindo o plano C2A conhecido, e converter apenas decisões ainda válidas em Issues aprovadas. Não implementar automaticamente conteúdo de arquivo de PLAN.

## 11. Frontend mobile-first consolidado

Reorganizar UX com Residente no centro, menos ruído visual, poucas cores, ações operacionais claras, acessibilidade e paridade funcional entre celular/tablet/desktop.

## 12. Integração frontend ↔ backend

Fechar contratos reais de API, estados, erros, RBAC e fluxos operacionais sem mocks permanentes.

## 13. E2E e homologação

Cobrir fluxos críticos, regressões cross-tenant, perfis, autoria, medicação, PAIS, rotina, Admissão, Prontuário e Passagem.

## 14. CI, cloud e produção

Configurar CI e ambiente cloud/homologação somente após estabilização suficiente do núcleo. Deploy crítico exige aprovação humana, backup/rollback e validação do ambiente.

## 15. Módulos complementares

Estoque, financeiro, portal da família, agenda ampliada, relatórios e outras frentes entram conforme prioridade operacional. Não inseri-los silenciosamente dentro de Issues do núcleo. Alertas avançados passaram a fazer parte da Camada Operacional (seções 16 e 17).

## 16. Camada Operacional — ciclo atual: Fases 1–5

Registrada em 28/09 (#115). Objetivo do ciclo: o primeiro fluxo operacional diário completo.

`profissional inicia plantão → FacILPI identifica sua área e residentes → apresenta prioridades, atividades e alertas → profissional assume uma situação → atua no módulo de origem → a fonte resolve o alerta → o que continuar aberto entra na passagem de plantão → o próximo turno recebe e confirma`

### Princípios (valem para todas as fases)

- **Alerta não é notificação genérica.** Auditoria registra acontecimentos; alerta destaca o que exige ação, atenção, acompanhamento, resolução ou continuidade entre turnos. Nem toda alteração vira alerta.
- **Resolução automática pela fonte.** Se a fonte deixa de estar pendente (ex.: avaliação realizada), o alerta deixa de existir. Ninguém precisa voltar à Central só para clicar "resolvido".
- **Resolver na origem.** A Central não duplica módulos: cada item leva ao módulo que resolve ("Realizar avaliação", "Abrir PAIS", "Ver intercorrência").
- **RBAC por origem.** Um alerta é visível com `alertas:ler` **mais** a leitura do módulo de origem. `alertas:ler` sozinho não mostra todos os alertas da instituição.
- **RBAC ≠ responsabilidade operacional.** RBAC responde "o que este usuário pode acessar"; responsabilidade responde "pelo que este profissional responde neste plantão". Responsabilidade nunca concede acesso.
- **Sistema informa, profissional decide.** Sem diagnóstico automático, recomendação clínica inventada, faixa clínica arbitrária ou decisão automática de conduta.

### Regras arquiteturais

1. **ID estável do alerta.** O ID é determinístico: `regra:referência[:contexto]`. A referência é o identificador estável da entidade de origem (documento, intercorrência, plano, residente…); o contexto só entra quando a mesma entidade pode originar situações distintas (ex.: etapa da admissão parada). Texto livre entra como hash curto. Nunca entram componentes voláteis (horário atual, posição na lista, contagem). Recalcular a projeção não muda o ID. A Fase 3 associa o estado operacional a esse ID.
2. **Temporalidade da responsabilidade.** Responsabilidade operacional tem vigência (`inicio_em`, `fim_em`) e é append-only: trocar o responsável encerra a vigência anterior e abre outra, nunca reescreve a anterior. Ex.: evento às 14:10 com Ana responsável desde 07:00; Juliana assume a área às 15:00 → o histórico do evento das 14:10 continua mostrando Ana.

### Fase 1 — Alertas e Pendências (PR 1A backend, PR 1B frontend)

- `alertas:ler` para cuidador, enfermagem, médico, responsável técnico e administrativo (migration 023; templates + clones institucionais; sem `platform_superuser`).
- Localização operacional mínima no item (`unidade`, `quarto`, `leito`, `local`), sem exigir `quartos_leitos:ler` e sem conceder acesso ao módulo.
- `natureza` separada de `gravidade` (domínio `alerta | pendencia | informativo | atividade`; nesta fase só `alerta` e `pendencia`). Contagem por natureza.
- Contrato de tempo: `desde` (origem da situação), `prazo` (vencimento real, só quando o domínio fornece), `gerado_em` (metadado da resposta); "agora" é só referência de apresentação do frontend.
- Ordenação determinística: gravidade → alertas antes de pendências → mais atrasado/antigo → ID estável.
- Página "Alertas e Pendências" (Todos, Críticos, Atenção, Pendências; "Prioridade agora"), card que responde o quê/com quem/onde/quando/o que fazer, sino como triagem rápida (mesmo endpoint, até 5 itens, ~60 s), Alertas na navegação inferior mobile.
- **Concluída quando:** cuidador vê só origens autorizadas; enfermagem conforme matriz; gestor preservado; local, tempo, prazo e natureza corretos; sino e Central consistentes; mobile funcional; resolver na origem e resolução automática preservados; tenant isolation confirmada; regressão do gate, build e CI verdes; homologação com contas sintéticas (cuidador, enfermagem, gestor).

### Fase 2 — Escala, plantão e responsabilidade (PR 2A estrutura, PR 2B escala × real)

- 2A: áreas operacionais flexíveis (ala, setor, unidade, grupo — `QuartoLeito.unidade` não é tratada automaticamente como ala), vínculo temporal área ↔ leito, turnos, plantão real (início/fim) e responsabilidade temporal (funcionário, plantão, área, início, fim).
- 2B: escala planejada × plantão real — previsto, presente/efetivo, ausência, substituição simples e cobertura.
- Não é RH: sem folha, ponto, banco de horas ou cálculo salarial.
- **Concluída quando:** escala planejada e plantão real existem; profissional associado a área; ausência e substituição simples funcionam; responsabilidade independente do RBAC; temporalidade correta; tenant isolation; testes focados e gate verdes.

### Fase 3 — Estado persistente do alerta

- Fonte determina se a situação existe → projeção gera o alerta → estado registra o que a equipe fez. Nunca duas fontes concorrentes de verdade.
- Ciclo `novo → assumido → em atendimento → resolvido`, com `assumido_por`, `assumido_em`, `em_atendimento_em`, `resolvido_em`, ligado ao ID estável. A equipe vê "Em atendimento por …".
- A resolução continua vindo da fonte: quando a projeção deixa de gerar o alerta, o estado é encerrado de forma coerente e auditada, sem clique manual.
- **Concluída quando:** alerta pode ser assumido; equipe vê quem assumiu; estado persiste com histórico e auditoria; resolução pela fonte continua; cross-tenant preservado; regressão proporcional verde.

### Fase 4 — Passagem de plantão

- Evolui a UX-09. Parte automática só com dados reais existentes (intercorrências abertas, alertas, pendências, atividades não concluídas, ausências…) + observação manual curta e contextual (categoria, residente opcional, texto curto), sem virar prontuário paralelo.
- O próximo plantão visualiza, identifica o que veio do turno anterior (com a situação atual da fonte) e confirma o recebimento. Auditoria de quem passou/quando e quem recebeu/quando.
- **Concluída quando:** encerramento gera resumo; pendências abertas seguem para o próximo turno; próximo turno visualiza e confirma; histórico/auditoria corretos; testes verdes.

### Fase 5 — Meu Plantão

- Principal destino operacional após o login quando há plantão ativo; o gestor mantém o dashboard institucional. Nenhum acesso legítimo é removido.
- Turno, área, residentes sob responsabilidade, prioridades, atividades atuais e próximas, residentes em atenção, alertas e pendências — filtrados por tenant, RBAC e responsabilidade. Ações levam ao módulo de origem, sem formulários duplicados.
- **Concluída quando:** usuário identifica plantão atual, área, residentes, prioridades, atividades e alertas; acessa a origem; gestor mantém visão ampla; tenant/RBAC corretos; testes verdes.

### Critério final do ciclo 1–5

Demonstrar, com contas e residentes sintéticos: login → plantão ativo identificado → área → residentes sob responsabilidade → prioridades → atividades → alertas autorizados → situação relevante gera alerta → profissional assume → equipe vê quem assumiu → profissional atua no módulo de origem → fonte deixa de gerar alerta → estado encerrado → o que segue aberto entra na passagem → próximo plantão visualiza → próximo plantão confirma recebimento.

### Fora do ciclo atual

Push notification, vibração, som, WebSocket/tempo real avançado, painel de TV, escalonamento automático, faixas clínicas configuráveis, indicadores avançados, motor de regras configurável, IA/predição, equipamentos/manutenção, folha de pagamento, ponto, banco de horas e RH completo. Necessidades desse tipo que aparecerem durante o ciclo são registradas como evolução futura.

## 17. Camada Operacional — Fases 6–14 (FORA DO CICLO ATUAL)

Somente direção de produto. Nenhuma destas fases tem design técnico, migration, tabela ou implementação aprovados; **cada uma exige PLAN READ_ONLY próprio antes de qualquer BUILD**, e o escopo pode mudar nesse PLAN.

- **Fase 6 — Tempo real e dispositivos.** Push notifications, badge, vibração, som, atualização em tempo real e suporte a smartphone/tablet.
- **Fase 7 — Escalonamento.** Alertas não assumidos, tempos-limite, encaminhamento progressivo ao próximo responsável/enfermagem/coordenação.
- **Fase 8 — Cobertura avançada do plantão.** Faltas, trocas, substituições temporárias e redistribuição de responsabilidades/cobertura. Não é RH, folha, ponto ou banco de horas. (A Fase 2B entrega apenas ausência, substituição simples e cobertura básica.)
- **Fase 9 — Painel operacional.** Visão em tempo real da instituição/posto: plantão atual, áreas, alertas, pendências, residentes em atenção e situação operacional; possibilidade futura de painel/TV respeitando privacidade.
- **Fase 10 — Indicadores operacionais e gerenciais.** Tempos de resposta/resolução, alertas não assumidos/escalonados, pendências transferidas, atividades atrasadas, intercorrências, ausências, substituições e análises por ala/turno/período.
- **Fase 11 — Regras configuráveis.** Prioridade, destinatários, antecedência, canais, regras operacionais e, quando aplicável, parâmetros clínicos definidos pela ILPI/Responsável Técnico. O FacILPI nunca inventa faixas clínicas.
- **Fase 12 — Checklists e comunicação contextual.** Checklists configuráveis de início/fim de plantão e mensagens/observações vinculadas a residente, área ou turno, sem criar prontuário paralelo ou "WhatsApp interno".
- **Fase 13 — Equipamentos, manutenção e contingência.** Equipamentos, inspeções/manutenções, indisponibilidades operacionais e procedimentos de contingência para falha de internet, servidor ou dispositivo.
- **Fase 14 — Automação e detecção de padrões.** Organização, sumarização, priorização e identificação de padrões sobre dados existentes. Sem diagnóstico automático, decisão clínica ou predição não validada.

**RH completo** — folha, ponto e banco de horas — permanece fora das 14 fases e fora do escopo do FacILPI neste ciclo.
