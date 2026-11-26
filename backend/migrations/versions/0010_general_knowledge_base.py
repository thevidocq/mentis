"""General Knowledge Base: rename General; analysts no longer tick it (everyone reads it); chats.use_general

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("use_general", sa.Boolean(), nullable=False, server_default=sa.true()))
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE tenants SET name = 'General Knowledge Base' WHERE is_global AND name = 'General'"))
    gkb = conn.execute(sa.text("SELECT id FROM tenants WHERE is_global")).scalar()
    if gkb is None:
        return
    # For analysts the tick meant "can read"; everyone reads it now. For tenant admins it now means
    # "manages the General Knowledge Base" and is kept as it is (review it in Users).
    conn.execute(sa.text(
        "DELETE FROM user_tenants WHERE tenant_id = :g AND user_id IN (SELECT id FROM users WHERE role <> 'tenant_admin')"
    ), {"g": gkb})


def downgrade() -> None:
    op.drop_column("chats", "use_general")
    op.get_bind().execute(sa.text("UPDATE tenants SET name = 'General' WHERE is_global AND name = 'General Knowledge Base'"))
