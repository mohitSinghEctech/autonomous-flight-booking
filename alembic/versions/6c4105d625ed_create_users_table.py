"""create users table

Revision ID: 6c4105d625ed
Revises: 
Create Date: 2026-10-05 00:17:20.178836

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6c4105d625ed'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('given_name', sa.String(length=100), nullable=False),
    sa.Column('family_name', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('users')
