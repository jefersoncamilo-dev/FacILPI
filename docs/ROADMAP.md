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

Estoque, financeiro, alertas avançados, portal da família, agenda ampliada, relatórios e outras frentes entram conforme prioridade operacional. Não inseri-los silenciosamente dentro de Issues do núcleo.
