"""tenant admins on several tenants: user_tenants, invitations.tenant_ids

Revision ID: 0005
Revises: 0004
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_tenants",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tenant_id"),
    )
    op.create_index("ix_user_tenants_tenant_id", "user_tenants", ["tenant_id"])
    # Every existing tenant admin keeps its tenant.
    op.execute("INSERT INTO user_tenants (user_id, tenant_id) SELECT id, tenant_id FROM users WHERE tenant_id IS NOT NULL")
    with op.batch_alter_table("users") as b:
        b.drop_column("tenant_id")

    op.add_column("invitations", sa.Column("tenant_ids", sa.JSON(), nullable=False, server_default="[]"))
    conn = op.get_bind()
    for inv_id, tid in conn.execute(sa.text("SELECT id, tenant_id FROM invitations WHERE tenant_id IS NOT NULL")).all():
        conn.execute(sa.text("UPDATE invitations SET tenant_ids = :v WHERE id = :id"), {"v": json.dumps([str(tid)]), "id": inv_id})
    with op.batch_alter_table("invitations") as b:
        b.drop_column("tenant_id")


def downgrade() -> None:
    # A tenant admin with several tenants keeps only one of them.
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("tenant_id", sa.Uuid(), nullable=True))
        b.create_foreign_key("fk_users_tenant_id", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
    op.execute("UPDATE users SET tenant_id = (SELECT MIN(CAST(tenant_id AS TEXT)) FROM user_tenants WHERE user_tenants.user_id = users.id)"
               if op.get_bind().dialect.name == "sqlite" else
               "UPDATE users SET tenant_id = ut.tenant_id FROM (SELECT DISTINCT ON (user_id) user_id, tenant_id FROM user_tenants ORDER BY user_id) ut WHERE ut.user_id = users.id")
    op.drop_index("ix_user_tenants_tenant_id", table_name="user_tenants")
    op.drop_table("user_tenants")
    with op.batch_alter_table("invitations") as b:
        b.add_column(sa.Column("tenant_id", sa.Uuid(), nullable=True))
        b.create_foreign_key("fk_invitations_tenant_id", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
        b.drop_column("tenant_ids")
