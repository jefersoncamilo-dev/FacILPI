# UX operacional do plantão — relatório consolidado

- Issue: [jefersoncamilo-dev/FacILPI#135](https://github.com/jefersoncamilo-dev/FacILPI/issues/135)
- Branch: `feat/ux-operacional-ilpi`, criada a partir de `fase-3b/funcionarios-usuarios-vinculos` @ `a02b438` (merge do PR #130)
- Data: 2026-09-30
- Protótipo: [`prototypes/ux-operacional/index.html`](../../prototypes/ux-operacional/index.html). É um arquivo estático, sem build, com dados sintéticos.

---

## 1. Resumo executivo

O backend do FacILPI já cobre boa parte do que um plantão ILPI precisa, e está bem protegido:
- execução append-only com três resultados;
- horário real separado do horário de registro;
- proteção contra execução duplicada por ocorrência (409);
- estorno com motivo;
- passagem de plantão em que o recebimento não se confunde com a entrega.

As maiores perdas de praticidade estão na **interface do registro**, não no contrato:

1. O modal do Meu Plantão abre com "Executada" já selecionado (`frontend/src/pages/MeuPlantao.tsx:73`) e sempre grava o horário como "agora" (`MeuPlantao.tsx:210`).
2. Não existe registro coletivo. Uma rodada de café da manhã para 12 residentes exige abrir e fechar o modal 12 vezes.
3. Não existe ajudante. O modelo não tem esse campo, conforme detalhado na seção 2.3.

**Recomendação:** reorganizar a sequência **Meu Plantão → Registro → Passagem** reaproveitando os endpoints existentes. Isso pode começar sem migration: pré-seleção, horário ajustável, coletivo por lote de chamadas e leitura do 409 como "já registrado". Ajudante e atividade não planejada ficam para uma decisão de modelagem posterior.

**Limites deste trabalho:**
- Nenhum teste foi executado.
- Nenhum ambiente publicado foi acessado.
- O concorrente não foi usado com login.
- As permissões e a idempotência simuladas no protótipo **não comprovam** o comportamento do backend.

---

## 2. Diagnóstico do FacILPI (somente os fluxos do plantão)

Legenda das classificações:
- **Implementado:** o código existe.
- **Integrado:** o frontend chama o backend.
- **Possui testes:** o arquivo de teste existe. Isso **não significa** que os testes foram executados com sucesso; nada foi executado nesta rodada.

### 2.1 Capacidades

| Capacidade | Evidência | Classificação |
|---|---|---|
| Lista do plantão (cuidado, medicação, intercorrência) | `GET /api/plantao/`, `GET /api/meu-plantao/`; `frontend/src/pages/MeuPlantao.tsx` | Implementado e integrado. Possui testes: `backend/tests/test_meu_plantao.py`, `frontend/src/__tests__/MeuPlantao.test.tsx` |
| Registro de cuidado | `POST /api/execucoes-cuidado`; `ExecucaoCreate` em `backend/src/application/schemas.py:1616` | Implementado e integrado (via modal do Meu Plantão). Possui testes: `test_d2_rotina.py` |
| Resultados | `executada \| recusada \| omitida`; justificativa obrigatória fora de `executada` (`models.py:613-617`, `schemas.py:1623`) | Implementado |
| Horário real ≠ horário de registro | `ocorrido_em` (retroativo permitido, futuro rejeitado) e `registrado_em` (servidor) em `models.py:634-635` | Backend implementado. O frontend fixa `ocorrido_em = now` (`MeuPlantao.tsx:210`) |
| Não duplicar | Índice único parcial `uq_exec_ocorrencia_vigente` (`models.py:624`); a segunda tentativa recebe 409 | Implementado **por ocorrência**. Não há chave de idempotência genérica |
| Correção | `POST /api/execucoes-cuidado/{id}/estornar` com motivo e substituto opcional (`schemas.py:1630`) | Backend implementado. **Não há interface** |
| Medicação | `POST /api/administracoes` (`administrada \| recusada \| omitida`, quantidade obrigatória), com fluxo próprio | Implementado e integrado pelo Meu Plantão. Possui testes: `test_c5_medicacao.py`. PR #134 (aberto) ajusta a permissão das doses |
| Passagem de plantão | `GET /api/passagens/previa`, `POST /api/passagens/`, `POST /api/passagens/{id}/receber`. Quem entregou não pode receber; um segundo recebimento simultâneo recebe 409 (`backend/src/application/passagem.py:486-508`) | Implementado e integrado. Possui testes: `test_passagem_plantao.py`, `PassagemPlantao.test.tsx`, `PassagemPersistida.test.tsx` |
| Alertas e estados | `/api/central-alertas` (assumir, atender, liberar; só a origem resolve) | Implementado e integrado. PR #133 (aberto) introduz "expirado sem registro" |
| Escala e presença | `/api/escala` (previsto: `prevista\|ausente\|cancelada`), `/api/plantoes` (real) | Implementado e integrado (`frontend/src/pages/Escala.tsx`) |

### 2.2 Lacunas e divergências

| # | Achado | Evidência | Impacto |
|---|---|---|---|
| L1 | O resultado "Executada" vem pré-selecionado | `MeuPlantao.tsx:73` (`resultadoCuidado: 'executada'`) | Um toque desatento registra como realizado um cuidado que não foi feito |
| L2 | Não é possível informar o horário real | `MeuPlantao.tsx:210` | Um registro feito depois do cuidado fica com a hora errada, embora o backend aceite retroativo |
| L3 | Não há registro coletivo | Nenhuma rota nem tela; cada execução é uma ocorrência | Rotinas de grupo (refeição, hidratação, mudança de decúbito) custam N aberturas de modal |
| L4 | Não há ajudante | `ExecucaoCuidado` não tem coluna para isso; `D2Input` usa `extra="forbid"` (`schemas.py:1567`) | O trabalho feito em dupla não fica rastreável por pessoa |
| L5 | Não há atividade não planejada | `ExecucaoCreate.ocorrencia_id` é obrigatório | O cuidado extra (um banho não previsto, por exemplo) não tem onde ser registrado como cuidado |
| L6 | Não há interface de estorno | O backend tem `estornar`; o frontend não | A correção depende de alguém com acesso técnico |
| L7 | O menu Passagem usa `plantao:ler` e o backend exige `passagem_plantao:*` | `frontend/src/components/shell/navegacao.ts:58` | O usuário vê o menu e recebe 403 na tela. A tela já trata esse caso, mas o menu engana |
| L8 | Estados do Meu Plantão feitos à mão | Marcação inline, sem usar `components/ui/states` | Inconsistência visual; o comportamento está correto (403 ≠ vazio) |
| L9 | A documentação diverge do código | `docs/PROJECT_STATUS.md` diz que o D.4 está "em recuperação", mas `ResidenteProntuario.tsx` e `test_d4_prontuario.py` existem | Status incerto; confirmar no GitHub |
| L10 | Não há tema escuro | Não há variáveis dark em `frontend/src/index.css` | É requisito do usuário; fica para entrega posterior |

### 2.3 "Não realizado": mapeamento para o contrato existente

A interface mostra três opções, e cada uma corresponde a um valor que já existe no backend:

| Interface (protótipo) | Contrato | Regra |
|---|---|---|
| Realizado | `executada` | Justificativa opcional |
| Recusado pelo residente | `recusada` + `justificativa` | Motivo obrigatório |
| Não realizado (outro motivo) | `omitida` + `justificativa` | Motivo obrigatório; a interface oferece motivos comuns (ausente do quarto, dormindo, contraindicação observada, falta de material, outro) e grava o texto no campo `justificativa` |
| *(nada registrado)* | Nenhuma execução | Continua como pendência ou atraso; **nunca** vira "não realizado" automaticamente |

Os motivos padronizados ficam no texto livre da `justificativa`. Para gerar estatísticas por motivo, será preciso um campo estruturado, o que depende de uma decisão de modelagem (seção 5).

**Ajudante:** a modelagem confirma que um ajudante estruturado, identificável e auditável exige mudança de esquema. Pode ser uma coluna ou uma tabela de participantes; em qualquer caso, uma migration incremental. Gravar o nome na `observacao` não precisa de migration, mas não é rastreável por pessoa e não deve ser tratado como solução.

---

## 3. Comparação focada (4 roteiros)

**Fontes:**
- D = manual *Registo Diário* (desktop/tablet); M = manual *RD Mobile*. Os números são páginas do PDF.
- Consultei visualmente D p.6, 8 e 34 e M p.10. As demais páginas citadas foram lidas pelo texto extraído.
- Páginas web consultadas em 2026-09-30.
- Nenhum recurso foi tratado como exclusivo. Quando uma fonte não menciona um recurso, isso não significa que ele não exista.

| Tarefa | Evidência concorrente | FacILPI hoje | Lacuna / capacidade | Proposta | Benefício esperado | Risco / dependência | Prior. | Critério de aceite |
|---|---|---|---|---|---|---|---|---|
| Registro de cuidado e recusa | MySenior: os botões de avaliação são específicos da atividade; por exemplo, Troca Fralda tem Urina / Fezes / Urina e fezes / Não trocou; depois "+ Ajudante" e "Tratada" (D p.8; M p.10). "Recusa de medicação" é um tipo de ocorrência (D p.18). PointClickCare: opção "Resident Refused" citada numa base de cliente (confiança baixa) | Três resultados com justificativa; "Executada" vem pré-selecionado; horário fixo | Capacidade existe; interface fraca (L1, L2) | Nenhum resultado pré-selecionado; três botões grandes; motivos comuns; horário real ajustável | Menos registros errados por toque; hora fiel | Nenhum no backend | P0 | Nada pré-marcado; recusa e não realizado exigem motivo; o horário futuro é bloqueado; ausência de registro continua pendente |
| Atividade não planejada | MySenior: "Nova Atividade" → grupo → atividade → avaliação → Tratada (D p.10-13; M p.11-12) | Não existe (L5) | Lacuna | Backlog: decidir se é uma programação avulsa ou um novo tipo de registro | Registro completo do cuidado real | Decisão de modelagem; RBAC | P1 | O cuidado extra aparece no prontuário com a origem "não planejado" |
| Coletivo com exceções e ajudantes | MySenior: lista da atividade com avaliação por utente e "Tratado" por linha. O "+ Ajudante" aplica-se a todos os utentes; para um ajudante específico, o registro tem de ser individual (D p.34-35; M p.35-36). Na captura D p.34, a primeira opção aparece destacada em todas as linhas; não confirmei se isso é uma pré-seleção. PointClickCare: vários residentes numa entrada (página oficial, confiança alta) | Não existe (L3) | Lacuna | Tela coletiva: uma linha por residente, com resultado, horário e ajudante próprios; nada marcado; salva só as linhas preenchidas; sem "marcar todos" | Menos aberturas de modal; exceções preservadas | Primeira versão sem migration (N chamadas `POST /execucoes-cuidado`); o ajudante depende de L4 | P0 (sem ajudante) / P1 (ajudante) | Cada residente mantém resultado e ajudante próprios; as linhas vazias continuam "sem registro" |
| Passagem de plantão | MySenior: "Passagem de Turno" é um tipo de comunicação em texto livre, com leitura obrigatória por "Tomar Conhecimento" (D p.25, 28). Log my Care: registros marcados para a passagem, ocorrências incluídas automaticamente, confirmação de leitura visível ao gestor (logmycare.co.uk/features/handovers, confiança alta) | Prévia automática feita pelo servidor, notas curtas, recebimento distinto e com 409 | Capacidade existe e é estruturada | Mostrar as pendências herdadas com responsável e prazo; "Confirmar recebimento" separado; as pendências continuam no Meu Plantão de quem recebe | Continuidade sem a falsa impressão de que tudo foi concluído | Corrigir L7 (permissão do menu) | P0 | Receber não conclui nenhuma pendência; quem entregou não pode receber; 403 com mensagem clara |

**Outros fatos registrados, sem uso direto nesta rodada:**
- O MySenior anunciou o assistente de IA em 06/05/2025 e uma ampliação em 28/05/2026. Trato isso como lançamento seguido de expansão, e não como informação conflitante.
- O MySenior anunciou faturamento integrado em 22/09/2026.
- A estatística de "previsão por tempo planejado" do MySenior serve de referência para o painel de carga de trabalho no backlog.
- Os preços do MySenior (em EUR, por utente) não foram comparados com o Brasil.

---

## 4. Decisões incorporadas

- **Acesso entre especialidades começa bloqueado,** e o administrador libera ações específicas. Ver não implica poder editar. Uma nota privada da especialidade é diferente de uma orientação compartilhada. Hoje não há áreas por especialidade no RBAC: o catálogo de `alembic/versions/015_s1_matriz_permissoes.py` e `backend/src/application/security.py` só conhece área operacional. Isso fica no backlog.
- **Tema escuro** é requisito já solicitado e fica para entrega posterior (L10).
- **O protótipo reaproveita o que já existe:** a paleta "Haze Esmeralda" (`frontend/src/index.css`), ícones Lucide, alvos de toque ≥ 44 px e navegação inferior no celular.
- **Medicação continua no fluxo próprio** (`/administracoes`, com quantidade obrigatória). No protótipo, ela aparece apenas como referência e não passa pelo formulário genérico de cuidados.

## 5. Decisões pendentes (curtas)

1. **Ajudante:** coluna única ou tabela de participantes? Quem pode ser ajudante: só quem está em plantão ativo, ou qualquer funcionário ativo? Qualquer opção exige migration.
2. **Motivo estruturado** para "não realizado": manter o texto livre ou criar um campo com códigos? Um campo com códigos exige migration.
3. **Janela de retroatividade** do horário real na interface. O backend aceita qualquer passado não futuro; a proposta de interface é limitar ao turno atual e ao anterior, com justificativa.
4. **Atividade não planejada:** qual modelo usar (L5)?
5. **PRs #133 e #134** (abertos) mudam a semântica de alertas e doses. Convém integrá-los antes de implementar a P0.

---

## 6. Backlog priorizado

Esforço: P = pequeno (≤ 1 dia), M = médio (2–4 dias), G = grande (> 1 semana).

### P0: praticidade do plantão, sem migration

| Item | Valor | Esforço | Risco / dependência | Aceite |
|---|---|---|---|---|
| **P0-1** Registro individual sem pré-seleção, com horário real ajustável e motivos | Evita falso "realizado"; hora fiel | P | Só o frontend; testes em `MeuPlantao.test.tsx` | Nada pré-marcado; horário futuro bloqueado; recusa e não realizado exigem motivo; o payload segue `ExecucaoCreate` |
| **P0-2** 409 lido como "já registrado" + preservação do preenchimento em falha | Repetir não duplica; a rede não apaga o que foi preenchido | P | Depende do índice `uq_exec_ocorrencia_vigente` (já existe) | Timeout seguido de nova tentativa não cria segunda execução; em 409, a tela recarrega e mostra o registro existente; em falha de rede, o formulário continua preenchido |
| **P0-3** Registro coletivo por atividade (sem ajudante) | Menos passos em rotinas de grupo | M | N chamadas independentes; tratar o resultado parcial por linha | Cada linha tem resultado e horário próprios; as linhas vazias ficam "sem registro"; uma falha numa linha não desfaz as outras e é mostrada nessa linha |
| **P0-4** Menu Passagem com a permissão correta (L7) | Evita um 403 inesperado | P | `navegacao.ts` | O menu só aparece com `passagem_plantao:ler` |
| **P0-5** Passagem mostrando pendências herdadas com responsável e prazo, e recebimento separado | Continuidade clara | P-M | Reaproveita `/passagens/previa` | Receber não altera nenhuma pendência; o texto da tela diz isso explicitamente |
| **P0-6** Filtros e rolagem preservados no Meu Plantão | Volta ao ponto em que o usuário estava | P | Só o frontend | Depois de registrar, a lista volta com o mesmo filtro e a mesma posição |

### P1: exige decisão ou migration

| Item | Valor | Esforço | Risco / dependência | Aceite |
|---|---|---|---|---|
| P1-1 Ajudante por residente (individual e coletivo) | Rastreia o trabalho feito em dupla | M | Migration incremental; RBAC; auditoria | Cada execução lista participantes identificados; a autoria continua do usuário autenticado |
| P1-2 Interface de estorno e substituição | Correção sem suporte técnico | M | `execucoes:corrigir`; motivo obrigatório | O registro original continua visível como estornado; o substituto fica ligado a ele |
| P1-3 Atividade não planejada | Registro fiel do cuidado real | M-G | Decisão L5 | Aparece no prontuário e no plantão com a origem correta |
| P1-4 Áreas multidisciplinares e matriz de acesso (bloqueado por padrão) | Privacidade por especialidade (REQ-04/07) | G | Catálogo RBAC, migrations, testes de API direta, busca, contadores e exportação | Uma área sem liberação recebe 404/403 na API, e isso não vaza nos contadores nem nos resumos |
| P1-5 Emergência (REQ-08) | Resumo rápido para encaminhamento | M-G | Reaproveitar intercorrência, prontuário e ficha; sem simular chamada externa | Mostra os dados ausentes e a data de cada dado; não duplica intercorrência |
| P1-6 Fisioterapia (REQ-05) | Plano, agenda e evolução | G | Confirmar as escalas de avaliação com o gestor | Presença, recusa, ausência e reagendamento distintos |
| P1-7 Tema escuro | Requisito do usuário | M | Tokens em `index.css` | Contraste AA nos dois temas |

### P2: evolução

- Lembretes configuráveis (REQ-06), distinguindo lembrete, alerta crítico, confirmação de leitura e responsabilidade assumida.
- Escala mensal configurável (REQ-09).
- Painel do gestor com carga de trabalho.
- Resumo assistido da passagem, com links para a origem e revisão humana.
- Leitura de QR/NFC que abre o contexto do residente, sem confirmar cuidado automaticamente.
- Registro por voz, sempre com revisão antes de salvar.

## 7. Plano incremental de PRs

Cada PR é uma Issue.

1. **PR-A (P0-1 + P0-2 + P0-6):** só em `frontend/src/pages/MeuPlantao.tsx` e nos testes dele.
2. **PR-B (P0-4 + P0-5):** `navegacao.ts` e `PassagemPlantao.tsx`.
3. **PR-C (P0-3):** nova tela coletiva que chama o mesmo `POST /execucoes-cuidado`, sem mudar o backend.
4. **Decisão de modelagem (P1-1, P1-3), depois PR-D:** migration e API.

## 8. Piloto e métricas (resumo)

- **Linha de base:** 3 a 5 plantões antes da mudança e 3 a 5 plantões comparáveis depois dela.
- **Medidas:**
  - tempo mediano de registro por tarefa;
  - quantidade de correções e estornos por 100 registros;
  - pendências sem registro sobre as atividades previstas;
  - tempo de passagem;
  - pendências sem responsável;
  - percepção de esforço da equipe.
- **Cuidados:**
  - tempo de preenchimento não é tempo de cuidado;
  - falta de registro não prova omissão;
  - nenhuma meta percentual antes de existir a linha de base;
  - nenhum conteúdo clínico nos logs de analytics;
  - uma amostra pequena é exploratória.

## 9. As três melhorias prioritárias

1. **Registro individual seguro** (P0-1 + P0-2): nenhum resultado pré-selecionado, horário real ajustável, motivo obrigatório para recusa e não realizado, e 409 lido como "já registrado" com o preenchimento preservado.
2. **Registro coletivo por atividade** (P0-3): uma linha por residente com resultado e horário próprios, sem "marcar todos", usando o endpoint atual. O ajudante entra em seguida (P1-1).
3. **Passagem que preserva responsabilidade** (P0-4 + P0-5): permissão correta no menu, pendências herdadas com responsável e prazo, e recebimento explicitamente separado de conclusão.
