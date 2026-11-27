"""documents from a link: source URL, check schedule and last check

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

COLUMNS = (
    ("source_url", sa.String(2000)),
    ("source_check", sa.String(8)),
    ("source_checked_at", sa.DateTime(timezone=True)),
    ("source_status", sa.String(12)),
    ("source_error", sa.String(300)),
    ("source_etag", sa.String(200)),
    ("source_modified", sa.String(100)),
)


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.add_column("documents", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("documents", name)
