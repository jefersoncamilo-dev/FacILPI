# Domain Rules — FacILPI

## Princípio do produto

FacILPI é um sistema para ILPIs, não um sistema hospitalar por padrão. Separe gestão institucional, cuidados cotidianos e atos/informações relacionados à saúde.

## Regra de repercussão

Sempre pergunte: "Se este dado for criado ou alterado aqui, onde ele deve repercutir no restante do sistema?"

Avalie residente, familiares, prontuário, PAIS, tarefas/rotina, agenda, medicamentos, alertas, dashboard, Meu Plantão, passagem de plantão, quarto/leito, estoque, financeiro, equipe e auditoria.

Mapear repercussão não significa implementar automação. Automatize somente quando houver justificativa operacional e escopo aprovado.

## Estados críticos

Procure uma única fonte de verdade para estados críticos, especialmente:
- residente ativo/inativo;
- presença/ausência/hospitalização/saída;
- medicação prevista/administrada/recusada/omitida;
- PAIS e sua versão vigente;
- programação/ocorrência/execução assistencial;
- autoria/executor;
- tenant;
- perfil/permissão.

## Residente

O Residente é o centro da arquitetura funcional. Processos como Admissão não substituem a entidade Residente nem devem criar uma segunda pessoa para representar o mesmo indivíduo.

## Avaliações e grau de dependência

Avaliação é um fato/instrumento registrado. Grau de dependência oficial exige confirmação humana e histórico próprio. Não automatize decisão clínica nem use o campo legado de Residente como nova fonte oficial.

## Documentos

Obrigatoriedade documental é uma regra institucional/processual. Validade temporal não deve alterar automaticamente o status do documento sem regra explicitamente aprovada. Em Admissão, documento obrigatório só é considerado atendido conforme o contrato atual do módulo; não invente uma lista universal de documentos obrigatórios.

## Quarto/leito e ausência

Leito representa ocupação estrutural. Ausência/hospitalização representa presença física temporariamente alterada. Não libere leito automaticamente apenas porque existe ausência.

## Intercorrências

Intercorrência é evento relevante com histórico, gravidade/situação e providências/desfecho conforme contrato. Não transforme automaticamente todo cuidado, sinal vital ou ocorrência em Intercorrência e não gere tarefas/avisos fora de regra aprovada.

## Medicação

O sistema registra a prescrição informada; não emite decisão clínica automaticamente. Prescritor clínico e autoria técnica são conceitos distintos.

Estados e correções devem preservar histórico. Não trate Dose Prevista como Tarefa. Não introduza PRN/SOS, tolerância, classificação automática de cedo/tarde, estoque/lote ou decremento automático fora de uma Issue própria.

## PAIS

O PAIS é versionado e possui responsabilidades humanas explícitas de revisão/aprovação. Avaliações, grau de dependência, sinais vitais, intercorrências e medicação podem repercutir no contexto, mas não alteram automaticamente o PAIS sem decisão humana/contrato aprovado.

Fluxo principal: necessidade → meta → intervenção. Programação e execução pertencem à rotina assistencial.

## Rotina assistencial

Programação não é execução. Ocorrência esperada não é execução. Profissional designado não é necessariamente executor. Executor deve ser derivado da sessão autenticada quando o contrato do módulo assim define.

Pendências/atrasos derivados não devem ser materializados ou classificados automaticamente sem regra aprovada. Não adicionar tolerâncias escondidas.

## Admissão

Admissão é processo próprio e acompanha etapas sem duplicar as fontes oficiais de documentos, avaliações, quarto/leito ou PAIS. Avanços são explícitos/humanos. Cancelamento/desistência preservam histórico. Conclusão não deve disparar automaticamente medicação, tarefas, alertas, financeiro ou comunicações familiares sem regra própria.

## Prontuário longitudinal

Prontuário deve consultar/agregar fatos oficiais já persistidos. Não criar uma tabela genérica duplicando eventos apenas para montar timeline. Eventos devem manter origem e timestamps honestos. Estornos/correções devem permanecer visíveis conforme contrato.

## Passagem de Plantão

Deve sintetizar informações relevantes do turno sem virar nova fonte de fatos clínicos. Deve apontar para origens oficiais e permitir complemento humano quando necessário.

## Alertas do gestor

Decisão do responsável (26/09, #107): alertas são **projeção derivada**, calculada a cada consulta (`GET /api/central-alertas/`) a partir das fontes oficiais. Não há tabela, job agendado, "ciente" ou dispensa: o alerta some quando o problema é resolvido na tela de origem. A tabela legada `alertas` (001) e o CRUD `/api/alertas/` continuam `fail_closed`.

Destinatário: Administrador da ILPI (`alertas:ler`, migration 022, template `ilpi_admin` e clones). `alertas` é módulo clínico, fora do catálogo local. Cada regra só é calculada se a sessão também lê o módulo de origem; sem essa leitura a regra não existe para ela (nem contagem). Tenant sempre da sessão.

Regras v1 e limiares (constantes em `backend/src/application/alertas.py`, exibidos na tela):
- Admissão e documentos: admissão sem transição há mais de 7 dias; documento obrigatório não validado (mesmo predicado da pendência de admissão); documento vencido ou que vence em até 30 dias.
- Avaliação, grau e PAIS: avaliação mais recente do par tipo/instrumento vencida sem outra válida; residente `Ativo` sem grau ativo ou com grau vencido; residente `Ativo` sem PAIS vigente (crítico); PAIS em ciclo sem mudança há mais de 7 dias; PAIS vigente com data final vencida.
- Plantão: cuidados e doses com horário já passado nas últimas 24 h e sem registro, agrupados por residente (doses são críticas); intercorrência grave aberta (crítica); intercorrência aberta há mais de 24 h.
- Ocupação e equipe: residente `Ativo` sem leito; ausência sem retorno há mais de 7 dias; senha temporária não trocada há mais de 7 dias.

A janela de 24 h do plantão é recorte de período, não tolerância de atraso (D.2). Regras clínicas de valor (ex.: sinais vitais fora de faixa) não entram sem decisão própria. Notificação externa (e-mail, WhatsApp) e limiares configuráveis ficam fora da v1.

## IA e voz

IA pode apoiar entrada, organização e consulta, mas não deve tomar decisão clínica automaticamente. Entrada por voz futura deve preencher texto/estruturas sob confirmação humana, não executar conduta clínica por conta própria.
