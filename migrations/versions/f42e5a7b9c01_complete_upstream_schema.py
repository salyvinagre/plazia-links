"""Create fields and indexes present in models but missing from upstream migrations.

Revision ID: f42e5a7b9c01
Revises: e31d4f6a8b90
"""

import sqlalchemy as sa
from alembic import op

revision = "f42e5a7b9c01"
down_revision = "e31d4f6a8b90"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_links_user_id", "links", ["user_id"]),
    ("ix_clicks_link_timestamp", "clicks", ["link_id", "timestamp"]),
    ("ix_workspaces_owner_id", "workspaces", ["owner_id"]),
    ("ix_workspace_members_user_id", "workspace_members", ["user_id"]),
    ("ix_invites_status", "invites", ["status"]),
    ("ix_invites_invited_by_user_id", "invites", ["invited_by_user_id"]),
    ("ix_api_keys_user_id", "api_keys", ["user_id"]),
    ("ix_bio_links_link_id", "bio_links", ["link_id"]),
    ("ix_link_tags_tag_id", "link_tags", ["tag_id"]),
    ("ix_email_contacts_status", "email_contacts", ["status"]),
    ("ix_email_campaigns_created_at", "email_campaigns", ["workspace_id", "created_at"]),
    ("ix_email_campaign_contacts_contact_id", "email_campaign_contacts", ["contact_id"]),
    ("ix_email_campaign_clicks_link_id", "email_campaign_clicks", ["link_id"]),
)


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("workspaces", sa.Column("not_found_redirect", sa.String(500), nullable=True))
    op.add_column("workspaces", sa.Column("brand_color", sa.String(7), nullable=True))
    op.add_column("api_keys", sa.Column("permissions", sa.Text(), nullable=True))
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("workspace_id", "user_id", "action", "created_at"):
        op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns)
    op.execute(
        sa.text(
            "UPDATE webhook_deliveries SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        )
    )
    op.alter_column(
        "webhook_deliveries", "created_at", nullable=False, existing_type=sa.DateTime(timezone=True)
    )


def downgrade() -> None:
    op.alter_column(
        "webhook_deliveries", "created_at", nullable=True, existing_type=sa.DateTime(timezone=True)
    )
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_table("audit_logs")
    op.drop_column("api_keys", "permissions")
    op.drop_column("workspaces", "brand_color")
    op.drop_column("workspaces", "not_found_redirect")
    op.drop_column("users", "is_superuser")
