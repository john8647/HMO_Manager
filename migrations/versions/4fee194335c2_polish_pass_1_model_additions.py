"""polish pass 1 model additions

Revision ID: 4fee194335c2
Revises: c2de6083697e
Create Date: 2026-11-07 09:45:08.423036

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4fee194335c2'
down_revision = 'c2de6083697e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('expense_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_transactions_expense_id', 'transactions', 'expenses', ['expense_id'], ['id']
    )


def downgrade():
    op.drop_constraint('fk_transactions_expense_id', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'expense_id')
