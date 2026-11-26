"""integrations: connector instances per customer, chats.integration_ids

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plugin", sa.String(64), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("secrets_enc", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_integrations_tenant_name"),
    )
    op.create_index("ix_integrations_tenant_id", "integrations", ["tenant_id"])
    op.add_column("chats", sa.Column("integration_ids", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("chats", "integration_ids")
    op.drop_index("ix_integrations_tenant_id", table_name="integrations")
    op.drop_table("integrations")
