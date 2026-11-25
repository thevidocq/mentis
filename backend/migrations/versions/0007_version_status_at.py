"""document_versions.status_at: when the status became queued or processing

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_versions", sa.Column("status_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE document_versions SET status_at = uploaded_at")


def downgrade() -> None:
    with op.batch_alter_table("document_versions") as b:
        b.drop_column("status_at")
