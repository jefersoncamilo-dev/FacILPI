"""Revisão do Alembic exigida pelos modelos ORM atuais.

Os testes fixam o banco numa revisão conhecida (não em `head`) para que uma
migration nova não mude contagens de catálogo de testes alheios. Mas a API usa
os modelos atuais: quem exercita a API precisa do schema que eles mapeiam.
Atualize esta constante quando uma migration nova acrescentar ou mudar coluna
mapeada (como a 029 fez com `autor_id` e a 032 com `percentual_consumido`).
"""

ESQUEMA_DOS_MODELOS = "032_percentual_refeicao"
