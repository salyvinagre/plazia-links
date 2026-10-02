"""Product-local tenancy binding; no credentials or Identity user replicas."""

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class WorkspaceIdentityBinding(Base):
    __tablename__ = "workspace_identity_bindings"
    __table_args__ = (UniqueConstraint("issuer", "organization_id", name="uq_identity_tenant"),)

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
