"""Add MVP model

Revision ID: 13ml13mvp
Revises: d51b8285cf56
Create Date: 2026-01-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '13ml13mvp'
down_revision = 'd51b8285cf56'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'mvp',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False, default=0),
        sa.Column('reason_summary', sa.Text(), nullable=True),
        sa.Column('awarded_by_session_id', sa.String(length=36), nullable=False),
        sa.Column('awarded_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mvp_id'), 'mvp', ['id'], unique=False)
    op.create_index(op.f('ix_mvp_match_id'), 'mvp', ['match_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_mvp_match_id'), table_name='mvp')
    op.drop_index(op.f('ix_mvp_id'), table_name='mvp')
    op.drop_table('mvp')
