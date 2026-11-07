"""polish pass 1 model additions

Revision ID: c2de6083697e
Revises: a7b6e4a5874b
Create Date: 2026-11-06 22:57:28.482216

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2de6083697e'
down_revision = 'a7b6e4a5874b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('expense_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_column('expense_id')
