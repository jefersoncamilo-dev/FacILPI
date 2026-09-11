---
name: verify-backend
description: Executa validação backend segura e econômica no FacILPI. Use quando houver mudança backend, migration, RBAC, tenant, autoria ou necessidade de regressão controlada.
---

# Verificação backend

## Segurança do alvo

Antes de qualquer teste destrutivo ou migration de teste, confirme que o alvo é `DISPOSABLE_TEST`. Nunca use `storage/app.db`, `backend/storage/app.db`, homologação ou produção.

Reutilize os guards/fixtures de banco descartável existentes. Não contorne validações de alvo.

## Ordem eficiente

1. Teste específico do comportamento alterado.
2. Testes diretamente relacionados ao módulo/contrato histórico.
3. PostgreSQL descartável quando schema, constraints, FKs, tenant ou RBAC puderem divergir do SQLite.
4. Uma única regressão completa final se o gate da Issue exigir.

Não rode a suíte completa entre microcorreções.

## Diagnóstico

Quando falhar:
- capture apenas a falha útil e traceback relevante;
- formule uma hipótese;
- confira o trecho de código/migration/teste relacionado;
- aplique no máximo uma correção por hipótese;
- rerode o menor teste capaz de confirmá-la.

Se o mesmo sintoma persistir após duas tentativas justificadas sem nova evidência, pare e entregue diagnóstico. Não entre em loop.

## Integridade dos testes

Não remova testes, não adicione skip, não afrouxe asserts/tolerâncias e não altere fixtures para esconder defeito. Se o teste contradizer o contrato aprovado, reporte o conflito.

## Relatório

Informe comandos executados, banco/ambiente usado, contagens PASS/FAIL/SKIP, duração quando relevante, warnings bloqueantes ou não bloqueantes e se o banco oficial permaneceu intocado quando esse gate foi verificado externamente.
