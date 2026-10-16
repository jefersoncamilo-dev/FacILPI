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
Documentação impactada: SIM/NÃO/NÃO CONFIRMADO
Documentos atualizados:
Arquitetura impactada: SIM/NÃO/NÃO CONFIRMADO
Segurança/tenant/RBAC impactados: SIM/NÃO/NÃO CONFIRMADO
Contrato funcional impactado: SIM/NÃO/NÃO CONFIRMADO
Roadmap impactado: SIM/NÃO/NÃO CONFIRMADO
Resultado:
Riscos/pendências:
Próxima ação:
Writer lock atual:

Regras:
- Não declare `INTEGRATED`, `MERGED` ou `COMPLETED` sem confirmação correspondente no GitHub.
- Diferencie código implementado de código commitado, PR aberta de PR mergeada e teste local de CI.
- Se documentação foi impactada e não atualizada, não esconda: registre como pendência/bloqueio conforme criticidade.
- Se documentação não foi impactada, justifique brevemente em `Documentos atualizados`.
- Liste pendências fora do escopo sem corrigi-las silenciosamente.
- Informe exatamente uma próxima ação operacional quando o trabalho ainda depender de um próximo gate.

## Critério de parada

Preencha o template uma única vez com os fatos já confirmados na sessão e pare — esta skill não itera. Não regenere o handoff nem repita verificação de um fato sem evidência nova. Se uma informação permanecer indisponível após uma tentativa razoável de confirmação, registre `NÃO CONFIRMADO` naquele campo e finalize normalmente, sem bloquear a entrega por isso.
