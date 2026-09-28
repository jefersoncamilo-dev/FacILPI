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

Ocupação é derivada do residente atual; a edição do leito não a contorna. Leito com residente ocupante só aceita a situação `livre` na edição, e a inativação acontece somente pela ação própria de inativar, que exige a permissão dela e recusa leito ocupado.

## Intercorrências

Intercorrência é evento relevante com histórico, gravidade/situação e providências/desfecho conforme contrato. Não transforme automaticamente todo cuidado, sinal vital ou ocorrência em Intercorrência e não gere tarefas/avisos fora de regra aprovada.

A leitura devolve o registro como gravado, inclusive valores anteriores ao contrato atual (situação `"Aberta"`/nula, tipo vazio, gravidade ausente). Só `aberta` entra em plantão, alertas e contagem de abertas; situação fora de `aberta`/`encerrada` não é tratada como aberta nem apresentada como encerrada, e não é normalizada sem decisão registrada.

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

## Alertas e pendências

Decisão do responsável (26/09, #107): alertas são **projeção derivada**, calculada a cada consulta (`GET /api/central-alertas/`) a partir das fontes oficiais. Não há tabela, job agendado, "ciente" ou dispensa: o alerta some quando o problema é resolvido na tela de origem. A tabela legada `alertas` (001) e o CRUD `/api/alertas/` continuam `fail_closed`.

Destinatários: Administrador da ILPI (`alertas:ler`, migration 022) e, desde a Camada Operacional (#117, migration 023), os perfis institucionais `cuidador`, `enfermagem`, `medico`, `responsavel_tecnico` e `administrativo` (templates e clones). `platform_superuser` não recebe. `alertas` é módulo clínico, fora do catálogo local. **RBAC por origem:** cada regra só é calculada se a sessão também lê o módulo de origem; sem essa leitura a regra não existe para ela (nem contagem). `alertas:ler` sozinho não mostra todos os alertas da ILPI. Tenant sempre da sessão.

Origem de cada regra: admissão → `admissoes:ler`; documentos → `documentos:ler`; avaliação → `avaliacoes:ler`; grau → `grau_dependencia:ler`; PAIS → `planos_cuidados:ler`; cuidados sem registro → `plantao:ler`; **doses sem registro → `plantao:ler` e `administracoes:ler`** (fato de medicação; o cuidador, "sem medicação" na 015, não recebe); intercorrências → `intercorrencias:ler`; residente sem leito → `quartos_leitos:ler`; ausência → `ausencias:ler`; acesso não utilizado → `funcionarios:ler`. Regras por residente ativo exigem também `residentes:ler`.

Contrato do item (#117):
- **Natureza** (`alerta | pendencia | informativo | atividade`) é independente da gravidade. Hoje só `alerta` (pede ação/atenção no plantão: doses e cuidados sem registro, intercorrências, ausência prolongada) e `pendencia` (algo a regularizar: admissão, documentos, avaliação, grau, PAIS, residente sem leito, acesso não utilizado). A contagem traz totais por gravidade, por natureza e `total`.
- **Tempo:** `desde` é quando nasceu a situação de origem; `prazo` é quando vence/venceu e só existe quando o domínio fornece vencimento real (validade de documento, avaliação e grau; data final do PAIS; horário previsto de cuidado/dose). Validade por data D vale até o fim do dia D no fuso da ILPI (vence às 00:00 de D+1). Situação vencida tem `desde = prazo`. Sem origem confiável (`grau_ausente`, `pais_ausente`, `residente_sem_leito`, documento só "vencendo"), `desde` é nulo — não se inventa horário. `gerado_em` é metadado da resposta; "agora" é referência de apresentação do cliente e nunca é persistido nem enviado por item.
- **Ordem determinística:** gravidade (crítico, atenção, aviso) → alerta antes de pendência → mais atrasado/antigo (prazo vencido mais antigo; senão `desde` mais antigo) → itens só com prazo futuro, o que vence primeiro antes → sem tempo por último → desempate pelo id.
- **Id estável:** `regra:referência[:contexto]` (ROADMAP §16). Contexto quando a mesma entidade origina situações distintas: etapa na admissão parada, situação no PAIS parado; avaliação vencida é do grupo residente + tipo/instrumento (hash curto do texto), não da última avaliação. Recalcular não muda o id.
- **Localização operacional mínima:** `unidade`, `quarto`, `leito` e `local` ("Ala B · Quarto 12 · Leito A") do leito atualmente ocupado pelo residente do item, numa única consulta por requisição; nulos sem leito. A localização operacional mínima é atributo contextual do residente presente em um alerta já autorizado e não concede capacidade de consultar, listar ou gerenciar quartos e leitos. Não exige `quartos_leitos:ler`; por conservadorismo, segue o mesmo gate do nome do residente (`residentes:ler`).

Regras v1 e limiares (constantes em `backend/src/application/alertas.py`, exibidos na tela):
- Admissão e documentos: admissão sem transição há mais de 7 dias; documento obrigatório não validado (mesmo predicado da pendência de admissão); documento vencido ou que vence em até 30 dias.
- Avaliação, grau e PAIS: avaliação mais recente do par tipo/instrumento vencida sem outra válida; residente `Ativo` sem grau ativo ou com grau vencido; residente `Ativo` sem PAIS vigente (crítico); PAIS em ciclo sem mudança há mais de 7 dias; PAIS vigente com data final vencida.
- Plantão: cuidados e doses com horário já passado nas últimas 24 h e sem registro, agrupados por residente (doses são críticas); intercorrência grave aberta (crítica); intercorrência aberta há mais de 24 h.
- Ocupação e equipe: residente `Ativo` sem leito; ausência sem retorno há mais de 7 dias; senha temporária não trocada há mais de 7 dias.

A janela de 24 h do plantão é recorte de período, não tolerância de atraso (D.2). Regras clínicas de valor (ex.: sinais vitais fora de faixa) não entram sem decisão própria. Notificação externa (e-mail, WhatsApp) e limiares configuráveis ficam fora da v1.

## IA e voz

IA pode apoiar entrada, organização e consulta, mas não deve tomar decisão clínica automaticamente. Entrada por voz futura deve preencher texto/estruturas sob confirmação humana, não executar conduta clínica por conta própria.
