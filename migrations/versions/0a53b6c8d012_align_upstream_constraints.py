"""Align link deletion and contact uniqueness with the existing ORM model.

Revision ID: 0a53b6c8d012
Revises: f42e5a7b9c01

Duplicate contacts in an existing database must be reconciled explicitly;
this migration never discards customer data to make the constraint succeed.
"""

from alembic import op

revision = "0a53b6c8d012"
down_revision = "f42e5a7b9c01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("clicks_link_id_fkey", "clicks", type_="foreignkey")
    op.create_foreign_key(
        "clicks_link_id_fkey", "clicks", "links", ["link_id"], ["id"], ondelete="CASCADE"
    )
    op.create_unique_constraint("uq_workspace_email", "email_contacts", ["workspace_id", "email"])


def downgrade() -> None:
    op.drop_constraint("uq_workspace_email", "email_contacts", type_="unique")
    op.drop_constraint("clicks_link_id_fkey", "clicks", type_="foreignkey")
    op.create_foreign_key("clicks_link_id_fkey", "clicks", "links", ["link_id"], ["id"])
