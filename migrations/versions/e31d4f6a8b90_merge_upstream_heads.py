"""Join email-delivery and power-feature migration branches.

Revision ID: e31d4f6a8b90
Revises: 39664acc0069, c3d4e5f6a7b8

Both branches must remain ancestors so installations already on either head
can upgrade without stamping or discarding their migration history.
"""

revision = "e31d4f6a8b90"
down_revision = ("39664acc0069", "c3d4e5f6a7b8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both parent branches own their DDL; this revision only joins them."""


def downgrade() -> None:
    """Reopen the two existing heads without deleting application data."""
