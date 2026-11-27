"""answers remember the tenants whose passages they read

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("searched", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "searched")
