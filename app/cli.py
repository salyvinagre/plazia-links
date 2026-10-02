import argparse
import asyncio
import sys

from sqlalchemy import select

from app.db import get_session_factory
from app.models.user import User


async def _make_superuser(email: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"User with email '{email}' not found")
            return False
        if user.is_superuser:
            print(f"User '{email}' is already a superuser")
            return True
        user.is_superuser = True
        await session.commit()
        print(f"User '{email}' ({user.display_name or user.email}) is now a superuser")
        return True


async def _list_superusers() -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(User).where(User.is_superuser.is_(True)).order_by(User.created_at)
        )
        users = result.scalars().all()
        if not users:
            print("No superusers found")
            return
        print(f"{'Email':<40} {'Name':<25} {'Created':<25}")
        print("-" * 90)
        for u in users:
            print(f"{u.email:<40} {(u.display_name or ''):<25} {str(u.created_at):<25}")


async def _organization_command(args: argparse.Namespace) -> None:
    from app.config import IdentitySettings, settings
    from app.contexts.access.adapters.provisioning import WorkspaceProvisioning

    config = IdentitySettings()
    config.validate_deployment(production=settings.environment.lower() in {"production", "prod"})
    async with get_session_factory()() as db:
        provisioning = WorkspaceProvisioning(db, config.issuer)
        if args.command == "bind-organization":
            workspace_id = await provisioning.bind(args.organization, args.name, args.workspace_id)
            await db.commit()
            print(f"{args.organization} -> workspace {workspace_id}")
        else:
            await provisioning.disable(args.organization)
            await db.commit()
            print(f"Disabled local access for {args.organization}")


def main() -> None:
    from app.config import settings

    parser = argparse.ArgumentParser(prog="plazia-links")
    commands = parser.add_subparsers(dest="command", required=True)
    bind = commands.add_parser("bind-organization", help="Bind a verified Identity tenant locally")
    bind.add_argument("organization")
    bind.add_argument("--name", required=True)
    bind.add_argument("--workspace-id", help="Explicitly bind an existing local workspace")
    disable = commands.add_parser("disable-organization", help="Revoke a local tenant binding")
    disable.add_argument("organization")
    superuser = commands.add_parser("makesuperuser", help="Local legacy profile only")
    superuser.add_argument("email")
    commands.add_parser("list-superusers", help="Local legacy profile only")
    args = parser.parse_args()
    if args.command in {"bind-organization", "disable-organization"}:
        try:
            asyncio.run(_organization_command(args))
        except ValueError as exc:
            parser.error(str(exc))
    elif settings.auth_mode != "legacy" or settings.environment.lower() in {"production", "prod"}:
        parser.error("Legacy users are unavailable in the Identity profile or production")
    elif args.command == "makesuperuser":
        sys.exit(0 if asyncio.run(_make_superuser(args.email)) else 1)
    else:
        asyncio.run(_list_superusers())


if __name__ == "__main__":
    main()
