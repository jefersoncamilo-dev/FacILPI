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

**Passagem persistida (#125, migration 027).** A passagem é o *registro do que foi comunicado* na troca de turno:
- **Parte automática montada pelo servidor** — nunca aceita do cliente —, só com dados reais e o RBAC de quem entrega, recortada pelos residentes da área (a única área pela qual a pessoa responde, ou a informada): alertas/pendências abertos da projeção (cuidados e doses entram como atividade, item a item), intercorrências abertas que ainda não são alerta, atividades não concluídas na janela do plantão (início do plantão até a entrega; sem plantão, últimas 12 h) e ausências ativas.
- **Parte manual**: observações curtas (até 280 caracteres) com categoria (`assistencial | comportamento | familia_visitas | estrutura_materiais | outro`) e residente opcional — não é prontuário paralelo.
- **Recebimento**: o próximo turno vê as passagens entregues com a **situação atual de cada fonte** ("ainda aberto" / "resolvido desde então"), filtrada pela leitura de origem de quem consulta (itens sem acesso aparecem só como contagem), e confirma. Quem entregou não confirma o próprio recebimento. Entregar pode encerrar o plantão no mesmo passo.
- Auditoria de quem passou/quando e quem recebeu/quando. Permissões `passagem_plantao:ler` (ilpi_admin, cuidador, enfermagem, médico, RT) e `passagem_plantao:registrar` (ilpi_admin, cuidador, enfermagem, RT). A visão ao vivo da UX-09 continua na mesma tela.

## Alertas e pendências

Decisão do responsável (26/09, #107): alertas são **projeção derivada**, calculada a cada consulta (`GET /api/central-alertas/`) a partir das fontes oficiais; não há job agendado, "ciente" nem dispensa, e o alerta some quando o problema é resolvido na tela de origem. A tabela legada `alertas` (001) e o CRUD `/api/alertas/` continuam `fail_closed`.

**Estado persistente (#123, migration 026) — substitui o antigo "sem tabela".** Três camadas, nunca duas verdades: a **fonte** determina se a situação existe; a **projeção** gera o alerta com id estável; o **estado** (`alerta_estados`) registra só o que a equipe fez. O estado nunca cria nem mantém alerta.
- Ciclo por episódio: novo (sem estado aberto) → `assumido` → `em_atendimento` → `resolvido`; ou `liberado` (devolve à equipe). Um estado aberto por alerta (índice único parcial: duas pessoas ao mesmo tempo → a segunda recebe 409 dizendo quem assumiu). Estados fechados ficam como histórico (`GET /central-alertas/historico`).
- **Resolução só pela fonte.** Não existe "resolver" manual. Na consulta da central, estado aberto cujo alerta a projeção não gera mais vira `resolvido` (encerramento `fonte`), auditado como `alerta_estados.resolvido_pela_fonte` (sem usuário: quem encerrou foi a fonte). Só entram regras avaliadas por inteiro nesta consulta — sem leitura da origem ou com teto atingido, a ausência do id não prova nada. O UPDATE é condicional (idempotente com consultas simultâneas). `resolvido_em` significa "detectado pela projeção". Se a situação voltar a existir (mesmo id), começa como novo episódio. Estado assumido depois do instante da projeção não é encerrado por ela (evita corrida com quem acabou de assumir).
- **"Resolvido" = a projeção deixou de gerar o alerta**, não "alguém registrou". Na maior parte das regras isso coincide com o registro na origem; em doses e cuidados sem registro, o alerta também deixa de existir quando o previsto sai da janela de 24 h da projeção — e o estado aberto é encerrado como `resolvido`/`fonte` mesmo sem registro. **Decisão pendente do PO (#123):** manter assim (a janela é a da rotina) ou distinguir "saiu da janela" de "resolvido". Nada é apagado: o histórico mostra quem assumiu e quando.
- Assumir, iniciar atendimento e liberar exigem `alertas:assumir` (clínica, ILPI-only; `ilpi_admin` e os 5 institucionais) e o alerta presente na projeção do próprio usuário (RBAC por origem + situação existente; senão 404). Liberar: o titular ou quem tem `escala:gerenciar`. Responsabilidade operacional não bloqueia nem concede assumir (RBAC ≠ responsabilidade). A equipe vê "Assumido por …/Em atendimento por …" na central, no sino e no Início.

Destinatários: Administrador da ILPI (`alertas:ler`, migration 022) e, desde a Camada Operacional (#117, migration 023), os perfis institucionais `cuidador`, `enfermagem`, `medico`, `responsavel_tecnico` e `administrativo` (templates e clones). `platform_superuser` não recebe. `alertas` é módulo clínico, fora do catálogo local. **RBAC por origem:** cada regra só é calculada se a sessão também lê o módulo de origem; sem essa leitura a regra não existe para ela (nem contagem). `alertas:ler` sozinho não mostra todos os alertas da ILPI. Tenant sempre da sessão.

Origem de cada regra: admissão → `admissoes:ler`; documentos → `documentos:ler`; avaliação → `avaliacoes:ler`; grau → `grau_dependencia:ler`; PAIS → `planos_cuidados:ler`; cuidados e doses sem registro → `plantao:ler` (mesma origem do Meu Plantão, que já projeta doses pendentes a quem lê o plantão; restringir doses a quem lê medicação exigiria conceder permissão clínica de medicação ao `ilpi_admin` — decisão pendente, não tomada no #117); intercorrências → `intercorrencias:ler`; residente sem leito → `quartos_leitos:ler`; ausência → `ausencias:ler`; acesso não utilizado → `funcionarios:ler`. Regras por residente ativo exigem também `residentes:ler`.

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

## Escala, plantão e responsabilidade operacional

Camada Operacional, Fase 2A (#120). O FacILPI sabe **quem responde por qual área agora** e quem respondia em qualquer instante do passado. Não é RH: sem folha, ponto, banco de horas ou cálculo salarial.

- **Área operacional** (`ala | setor | unidade | grupo`) é cadastrada por ILPI. `QuartoLeito.unidade` continua texto livre do leito e **não** é tratada como área. Leitos entram na área com vigência (`inicio_em`/`fim_em`); remover encerra a vigência, não apaga; um leito pertence a no máximo uma área ativa por vez. Os residentes de uma área derivam da ocupação atual dos seus leitos — fonte única, sem cópia.
- **Turno** é rótulo operacional com horas locais (pode cruzar a meia-noite).
- **Plantão real** é o que a pessoa efetivamente trabalha: ela inicia e encerra o próprio plantão (`plantao:registrar`); um em andamento por funcionário. O gestor (`escala:gerenciar`) pode encerrar um plantão esquecido aberto.
- **Responsabilidade** liga plantão, funcionário e área com vigência semiaberta `[inicio_em, fim_em)`. É append-only: a única alteração é gravar `fim_em` uma vez, com motivo (`fim_plantao | transferencia | ajuste`). Transferir encerra uma vigência e abre outra no mesmo instante — sem buraco nem sobreposição do mesmo par. Mais de um profissional pode responder pela mesma área (reforço). "Quem respondia no instante T" é sempre consultado pela vigência; eventos não copiam o nome do responsável.
- **Responsabilidade não é permissão.** Responder pela Ala B não abre nenhuma tela nem dado novo; RBAC continua sendo a única autorização. Contagem de residentes por área só aparece para quem lê residentes.
- **Escala planejada × plantão real** (#122, migration 025). A escala registra quem *deveria* trabalhar (funcionário, período — turno + data no fuso da ILPI ou horário explícito —, área opcional); o plantão real continua sendo quem *efetivamente* trabalhou. Quando o plantão nasce da própria escala, ela guarda o vínculo (`plantao_id`) e a responsabilidade nasce na área da escala. Tipos `regular | substituicao | cobertura`; situações `prevista | ausente | cancelada` — ausência e cancelamento exigem motivo e **nada é apagado**. Substituição simples: a original fica ausente e nasce uma escala `substituicao` no mesmo período e área (uma substituta válida por escala). Cobertura: escala extra ou plantão iniciado sem escala (aparece como "cobertura sem escala"). A mesma pessoa não tem duas escalas previstas sobrepostas; escala já cumprida não é alterada. O estado exibido (prevista, presente, realizada, não iniciada, ausente, substituída, cancelada) é derivado na hora, sem tolerância de atraso inventada. Faltas, trocas e redistribuição avançadas ficam para a Fase 8.
- Permissões (migration 024): `escala:ler` e `escala:gerenciar` (módulo operacional, não clínico, ILPI-only — o gestor pode repassá-las a perfis locais) e `plantao:registrar` (módulo `plantao`). Grants: `ilpi_admin` as três; cuidador, enfermagem e responsável técnico `escala:ler` + `plantao:registrar`; médico `escala:ler`. Tenant sempre da sessão; recurso de outra ILPI responde 404. Toda mutação é auditada.

## IA e voz

IA pode apoiar entrada, organização e consulta, mas não deve tomar decisão clínica automaticamente. Entrada por voz futura deve preencher texto/estruturas sob confirmação humana, não executar conduta clínica por conta própria.
