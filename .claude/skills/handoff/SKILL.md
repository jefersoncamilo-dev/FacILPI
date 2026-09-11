---
name: handoff
description: Gera o handoff obrigatório do FacILPI ao concluir ou transferir uma etapa, sem inventar estado e distinguindo BUILD, validação, commit e integração.
---

# Handoff FacILPI

Use somente fatos confirmados na sessão, git ou GitHub. Se algo não foi verificado, escreva `NÃO CONFIRMADO`.

Preencha exatamente:

Issue:
Branch:
Base:
Objetivo:
Escopo permitido:
O que foi confirmado:
Arquivos alterados:
Testes executados:
Resultado:
Riscos/pendências:
Próxima ação:
Writer lock atual:

Regras:
- Não declare `INTEGRATED`, `MERGED` ou `COMPLETED` sem confirmação correspondente no GitHub.
- Diferencie código implementado de código commitado, PR aberta de PR mergeada e teste local de CI.
- Liste pendências fora do escopo sem corrigi-las silenciosamente.
- Informe exatamente uma próxima ação operacional quando o trabalho ainda depender de um próximo gate.
