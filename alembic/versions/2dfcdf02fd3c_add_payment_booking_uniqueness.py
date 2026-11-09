"""add payment booking uniqueness

Revision ID: 2dfcdf02fd3c
Revises: a7c31f9d2b84
Create Date: 2026-10-06 02:07:57.844626

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2dfcdf02fd3c'
down_revision: Union[str, Sequence[str], None] = 'a7c31f9d2b84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint('uq_payment_booking_id', 'payments', ['booking_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_payment_booking_id', 'payments', type_='unique')
