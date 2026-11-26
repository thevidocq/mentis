"""answer check: provider role (answers | checker), chat_messages.answer_check

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_providers", sa.Column("role", sa.String(12), nullable=False, server_default="answers"))
    op.add_column("chat_messages", sa.Column("answer_check", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "answer_check")
    op.drop_column("llm_providers", "role")
