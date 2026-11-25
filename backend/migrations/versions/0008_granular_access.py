"""granular access: users.all_tenants, invitations.all_tenants; General ticked for everyone

Revision ID: 0008
Revises: 0007

- Analysts used to see every customer: they get all_tenants (every customer, also future ones).
- Tenant admins and analysts get General ticked (it is a tenant like the others, on by default).
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("all_tenants", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("invitations", sa.Column("all_tenants", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE users SET all_tenants = true WHERE role = 'analyst'")
    op.execute("UPDATE invitations SET all_tenants = true WHERE role = 'analyst'")
    conn = op.get_bind()
    general = conn.execute(sa.text("SELECT id FROM tenants WHERE is_global = true")).scalar()
    if general is not None:
        conn.execute(sa.text(
            "INSERT INTO user_tenants (user_id, tenant_id) SELECT u.id, :g FROM users u "
            "WHERE u.role = 'tenant_admin' AND NOT EXISTS "
            "(SELECT 1 FROM user_tenants x WHERE x.user_id = u.id AND x.tenant_id = :g)"), {"g": general})
        for inv_id, ids in conn.execute(sa.text("SELECT id, tenant_ids FROM invitations WHERE role = 'tenant_admin'")).all():
            ids = json.loads(ids) if isinstance(ids, str) else (ids or [])
            if str(general) not in ids:
                conn.execute(sa.text("UPDATE invitations SET tenant_ids = :v WHERE id = :id"),
                             {"v": json.dumps(ids + [str(general)]), "id": inv_id})


def downgrade() -> None:
    with op.batch_alter_table("invitations") as b:
        b.drop_column("all_tenants")
    with op.batch_alter_table("users") as b:
        b.drop_column("all_tenants")
