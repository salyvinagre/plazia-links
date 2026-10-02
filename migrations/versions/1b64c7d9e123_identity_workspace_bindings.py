"""Bind local workspaces explicitly to Identity organizations."""

import sqlalchemy as sa
from alembic import op

revision = "1b64c7d9e123"
down_revision = "0a53b6c8d012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.alter_column("owner_id", existing_type=sa.String(36), nullable=True)
    op.create_table(
        "workspace_identity_bindings",
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("organization_id", sa.String(40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
        sa.UniqueConstraint("issuer", "organization_id", name="uq_identity_tenant"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT 1 FROM workspaces WHERE owner_id IS NULL LIMIT 1")
    ).first():
        raise RuntimeError("Assign local owners before downgrading Identity workspaces")
    op.drop_table("workspace_identity_bindings")
    with op.batch_alter_table("workspaces") as batch:
        batch.alter_column("owner_id", existing_type=sa.String(36), nullable=False)
