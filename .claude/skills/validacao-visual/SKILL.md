---
name: validacao-visual
description: Valida uma correção ou funcionalidade na tela real do FacILPI, em ambiente descartável, com conta sintética e credencial efêmera. Use quando a evidência de teste automatizado não bastar e for preciso ver o comportamento no app rodando.
---

# Validação visual em ambiente descartável

Use quando o critério de aceite exigir ver o comportamento na tela, não apenas em teste. Teste que já renderiza o componente real com o helper real costuma ser evidência suficiente; nesse caso, diga isso e pergunte antes de montar o ambiente.

## Login e credenciais de teste

- Nunca solicite, leia, copie, armazene ou digite credenciais reais do usuário.
- Nunca use contas reais ou o banco oficial para testes.
- Para validação visual, crie somente uma conta sintética em banco descartável.
- Gere uma senha temporária aleatória e informe-a apenas ao usuário.
- Por padrão, o usuário faz o login manualmente no navegador integrado; depois que ele informar "login realizado", continue a navegação e os testes.
- Se o usuário autorizar explicitamente, o agente pode digitar a conta sintética e a senha gerada. A autorização vale apenas para credencial sintética em ambiente descartável e até o usuário dizer o contrário. Credencial real, conta real ou ambiente não descartável continuam proibidos: pare e peça que o usuário digite.
- Não registre a senha em commits, Issues, PRs, logs permanentes ou arquivos do repositório.
- Não passe a senha como argumento de linha de comando; use entrada do formulário ou variável gerada em runtime.
- Ao finalizar, encerre os serviços e remova o banco descartável.
- Para testes automatizados de API, use credenciais sintéticas isoladas e nunca credenciais de produção.
- Se o login falhar, diagnostique rede, CORS, porta, banco, vínculo e contexto antes de concluir que a senha está errada.

## Ambiente

Banco descartável fora do repositório, validado por `db_safety.validate_target()` antes de qualquer conexão. `storage/app.db` e `backend/storage/app.db` nunca são alvo. Aponte também `STORAGE_PATH` para o diretório descartável, para não criar artefato dentro do repositório.

Suba o schema com `alembic upgrade head` no alvo validado. Não copie, migre nem seede conteúdo do banco oficial.

Semeie o mínimo necessário: uma ILPI, um perfil com as permissões que a tela exige, o vínculo usuário/perfil/ILPI, o funcionário ativo e os registros sob teste. Prefira dados que venham da própria Issue, porque é o valor da Issue que precisa aparecer na tela.

## Portas e serviços

Confirme a porta antes de concluir que o app está no ar. Se a porta padrão estiver ocupada, o Vite sobe em outra e o `CORS_ORIGINS` do backend deixa de cobrir a origem: ajuste por variável de ambiente, nunca alterando código para acomodar o ambiente de teste. Não encerre processo que você não iniciou.

## Evidência

Antes de navegar, declare o que cada valor deve exibir e o que exibia com o defeito. Verifique o valor exato, não um padrão frouxo.

Cubra todos os consumidores da correção, não apenas o mais visível. Screenshot sozinho não prova nome acessível, foco nem estado; use leitura da página para texto e estrutura, e screenshot para layout.

## Encerramento

Encerre os serviços que você subiu, remova o banco descartável e confirme que a working tree continua limpa e que o banco oficial não foi tocado. Relate o caminho do banco descartável, o resultado da validação do alvo, os valores observados na tela e o que foi removido.
