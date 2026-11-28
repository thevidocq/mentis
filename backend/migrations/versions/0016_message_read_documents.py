"""answers remember the documents whose passages they read

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("read_documents", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "read_documents")
