"""initial — FáciLPI core tables

Revision ID: 001_initial
Revises:
Create Date: 2026-08-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('ativo', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table('instituicoes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('razao_social', sa.String(length=255), nullable=False),
        sa.Column('nome_fantasia', sa.String(length=255), nullable=True),
        sa.Column('cnpj', sa.String(length=18), nullable=True),
        sa.Column('endereco', sa.Text(), nullable=True),
        sa.Column('municipio', sa.String(length=255), nullable=True),
        sa.Column('telefone', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('responsavel_legal', sa.String(length=255), nullable=True),
        sa.Column('responsavel_tecnico', sa.String(length=255), nullable=True),
        sa.Column('capacidade', sa.Integer(), nullable=True),
        sa.Column('licenca_sanitaria', sa.String(length=100), nullable=True),
        sa.Column('validade_licenca', sa.Date(), nullable=True),
        sa.Column('fuso_horario', sa.String(length=64), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cnpj')
    )

    op.create_table('residentes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('instituicao_id', sa.String(length=36), nullable=True),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.Column('nome_social', sa.String(length=255), nullable=True),
        sa.Column('cpf', sa.String(length=14), nullable=True),
        sa.Column('rg', sa.String(length=20), nullable=True),
        sa.Column('cns', sa.String(length=15), nullable=True),
        sa.Column('data_nascimento', sa.Date(), nullable=False),
        sa.Column('sexo', sa.String(length=10), nullable=True),
        sa.Column('foto', sa.Text(), nullable=True),
        sa.Column('data_admissao', sa.Date(), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('grau_dependencia', sa.String(length=50), nullable=True),
        sa.Column('restricoes', sa.Text(), nullable=True),
        sa.Column('alergias', sa.Text(), nullable=True),
        sa.Column('necessidades_especiais', sa.Text(), nullable=True),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['instituicao_id'], ['instituicoes.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cpf', 'instituicao_id', name='uq_residente_cpf_inst')
    )
    op.create_index(op.f('ix_residentes_instituicao_id'), 'residentes', ['instituicao_id'], unique=False)

    op.create_table('familiares',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('residente_id', sa.String(length=36), nullable=False),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.Column('cpf', sa.String(length=14), nullable=True),
        sa.Column('parentesco', sa.String(length=50), nullable=True),
        sa.Column('telefone', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('endereco', sa.Text(), nullable=True),
        sa.Column('tipo_responsabilidade', sa.String(length=50), nullable=True),
        sa.Column('autorizacao_acesso', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_familiares_residente_id'), 'familiares', ['residente_id'], unique=False)

    op.create_table('documentos',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('residente_id', sa.String(length=36), nullable=True),
        sa.Column('instituicao_id', sa.String(length=36), nullable=True),
        sa.Column('tipo', sa.String(length=100), nullable=False),
        sa.Column('numero', sa.String(length=100), nullable=True),
        sa.Column('arquivo', sa.Text(), nullable=True),
        sa.Column('validade', sa.Date(), nullable=True),
        sa.Column('obrigatorio', sa.Boolean(), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('responsavel_envio', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['instituicao_id'], ['instituicoes.id'], ),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('quartos_leitos',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('instituicao_id', sa.String(length=36), nullable=False),
        sa.Column('unidade', sa.String(length=100), nullable=True),
        sa.Column('quarto', sa.String(length=50), nullable=False),
        sa.Column('leito', sa.String(length=50), nullable=False),
        sa.Column('capacidade', sa.Integer(), nullable=True),
        sa.Column('acessibilidade', sa.String(length=100), nullable=True),
        sa.Column('residente_atual_id', sa.String(length=36), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('data_ocupacao', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['instituicao_id'], ['instituicoes.id'], ),
        sa.ForeignKeyConstraint(['residente_atual_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('avaliacoes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('residente_id', sa.String(length=36), nullable=False),
        sa.Column('tipo', sa.String(length=50), nullable=False),
        sa.Column('instrumento', sa.String(length=100), nullable=True),
        sa.Column('profissional', sa.String(length=255), nullable=True),
        sa.Column('respostas', sa.Text(), nullable=True),
        sa.Column('pontuacao', sa.Float(), nullable=True),
        sa.Column('classificacao', sa.String(length=100), nullable=True),
        sa.Column('data', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('validade', sa.Date(), nullable=True),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_avaliacoes_residente_id'), 'avaliacoes', ['residente_id'], unique=False)

    op.create_table('planos_cuidados',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('residente_id', sa.String(length=36), nullable=False),
        sa.Column('versao', sa.Integer(), nullable=True),
        sa.Column('objetivos', sa.Text(), nullable=True),
        sa.Column('data_inicial', sa.Date(), nullable=False),
        sa.Column('data_final', sa.Date(), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('responsaveis', sa.Text(), nullable=True),
        sa.Column('revisor', sa.String(length=255), nullable=True),
        sa.Column('aprovador', sa.String(length=255), nullable=True),
        sa.Column('data_aprovacao', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_planos_cuidados_residente_id'), 'planos_cuidados', ['residente_id'], unique=False)

    op.create_table('tarefas',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('residente_id', sa.String(length=36), nullable=False),
        sa.Column('plano_id', sa.String(length=36), nullable=True),
        sa.Column('descricao', sa.String(length=500), nullable=False),
        sa.Column('horario_previsto', sa.DateTime(timezone=True), nullable=True),
        sa.Column('horario_realizado', sa.DateTime(timezone=True), nullable=True),
        sa.Column('prioridade', sa.String(length=20), nullable=True),
        sa.Column('responsavel', sa.String(length=255), nullable=True),
        sa.Column('executor', sa.String(length=255), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('justificativa', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['plano_id'], ['planos_cuidados.id'], ),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tarefas_residente_id'), 'tarefas', ['residente_id'], unique=False)

    op.create_table('medicamentos',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.Column('principio_ativo', sa.String(length=255), nullable=True),
        sa.Column('apresentacao', sa.String(length=100), nullable=True),
        sa.Column('concentracao', sa.String(length=100), nullable=True),
        sa.Column('unidade', sa.String(length=50), nullable=True),
        sa.Column('lote', sa.String(length=50), nullable=True),
        sa.Column('validade', sa.Date(), nullable=True),
        sa.Column('fabricante', sa.String(length=255), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('prescricoes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('residente_id', sa.String(length=36), nullable=False),
        sa.Column('medicamento_id', sa.String(length=36), nullable=False),
        sa.Column('prescritor', sa.String(length=255), nullable=False),
        sa.Column('dose', sa.String(length=50), nullable=False),
        sa.Column('via', sa.String(length=50), nullable=True),
        sa.Column('frequencia', sa.String(length=50), nullable=True),
        sa.Column('horarios', sa.String(length=255), nullable=True),
        sa.Column('inicio', sa.Date(), nullable=False),
        sa.Column('termino', sa.Date(), nullable=True),
        sa.Column('orientacoes', sa.Text(), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['medicamento_id'], ['medicamentos.id'], ),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prescricoes_residente_id'), 'prescricoes', ['residente_id'], unique=False)

    op.create_table('sinais_vitais',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('residente_id', sa.String(length=36), nullable=False),
        sa.Column('temperatura', sa.Float(), nullable=True),
        sa.Column('pressao_sistolica', sa.Integer(), nullable=True),
        sa.Column('pressao_diastolica', sa.Integer(), nullable=True),
        sa.Column('frequencia_cardiaca', sa.Integer(), nullable=True),
        sa.Column('frequencia_respiratoria', sa.Integer(), nullable=True),
        sa.Column('saturacao', sa.Integer(), nullable=True),
        sa.Column('glicemia', sa.Float(), nullable=True),
        sa.Column('peso', sa.Float(), nullable=True),
        sa.Column('profissional', sa.String(length=255), nullable=True),
        sa.Column('data', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sinais_vitais_residente_id'), 'sinais_vitais', ['residente_id'], unique=False)

    op.create_table('intercorrencias',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('residente_id', sa.String(length=36), nullable=False),
        sa.Column('tipo', sa.String(length=100), nullable=False),
        sa.Column('gravidade', sa.String(length=50), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('sbar_situacao', sa.Text(), nullable=True),
        sa.Column('sbar_contexto', sa.Text(), nullable=True),
        sa.Column('sbar_avaliacao', sa.Text(), nullable=True),
        sa.Column('sbar_recomendacao', sa.Text(), nullable=True),
        sa.Column('providencia', sa.Text(), nullable=True),
        sa.Column('desfecho', sa.Text(), nullable=True),
        sa.Column('responsavel', sa.String(length=255), nullable=True),
        sa.Column('data', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_intercorrencias_residente_id'), 'intercorrencias', ['residente_id'], unique=False)

    op.create_table('alertas',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('instituicao_id', sa.String(length=36), nullable=True),
        sa.Column('residente_id', sa.String(length=36), nullable=True),
        sa.Column('origem', sa.String(length=100), nullable=True),
        sa.Column('tipo', sa.String(length=50), nullable=False),
        sa.Column('gravidade', sa.String(length=20), nullable=True),
        sa.Column('mensagem', sa.Text(), nullable=False),
        sa.Column('responsavel', sa.String(length=255), nullable=True),
        sa.Column('prazo', sa.DateTime(timezone=True), nullable=True),
        sa.Column('situacao', sa.String(length=50), nullable=True),
        sa.Column('resolucao', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['instituicao_id'], ['instituicoes.id'], ),
        sa.ForeignKeyConstraint(['residente_id'], ['residentes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('alertas')
    op.drop_table('intercorrencias')
    op.drop_table('sinais_vitais')
    op.drop_table('prescricoes')
    op.drop_table('medicamentos')
    op.drop_table('tarefas')
    op.drop_table('planos_cuidados')
    op.drop_table('avaliacoes')
    op.drop_table('quartos_leitos')
    op.drop_table('documentos')
    op.drop_index(op.f('ix_familiares_residente_id'), table_name='familiares')
    op.drop_table('familiares')
    op.drop_index(op.f('ix_residentes_instituicao_id'), table_name='residentes')
    op.drop_table('residentes')
    op.drop_table('instituicoes')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
