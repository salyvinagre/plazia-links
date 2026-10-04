import ast
from pathlib import Path


def test_context_core_contains_no_framework_or_storage_imports():
    for root in Path("app/contexts").iterdir():
        for drawer in ("domain", "application"):
            for path in (root / drawer).rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    names = (
                        [node.module or ""]
                        if isinstance(node, ast.ImportFrom)
                        else [name.name for name in node.names]
                        if isinstance(node, ast.Import)
                        else []
                    )
                    assert not any(
                        name.split(".")[0]
                        in {
                            "fastapi",
                            "pydantic",
                            "psycopg",
                            "sqlalchemy",
                            "redis",
                            "httpx",
                            "httpx2",
                            "smtplib",
                            "dependency_injector",
                            "openfga_sdk",
                            "jwt",
                            "oauthlib",
                            "shared_persistence",
                        }
                        or name.startswith(("app.platform", "app.interfaces"))
                        for name in names
                    ), path
                    for name in names:
                        parts = name.split(".")
                        if "ports" in path.parts:
                            assert not name.startswith(
                                (
                                    f"app.contexts.{root.name}.application.commands.",
                                    f"app.contexts.{root.name}.application.queries.",
                                )
                            ), path
                        if parts[:2] == ["app", "contexts"] and parts[2] != root.name:
                            assert parts[3:] == ["contracts"], path


def test_application_drawers_and_interface_dispatch_keep_ownership():
    # Access authorization is the explicit golden-principles authority boundary.
    for root in Path("app/contexts").iterdir():
        allowed = {"__init__.py", "authorization.py"} if root.name == "access" else {"__init__.py"}
        assert {path.name for path in (root / "application").glob("*.py")} <= allowed
    for path in Path("app/interfaces").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.contexts.") or (
                    node.module or ""
                ).endswith(".contracts"), path
                assert not (
                    node.module == "shared_messaging"
                    and any(name.name.startswith("InProcess") for name in node.names)
                ), path


def test_legacy_runtime_paths_and_dependencies_are_removed():
    for path in ("app/models", "app/services", "app/core", "migrations", "alembic.ini"):
        assert not Path(path).exists(), path
    dependencies = Path("pyproject.toml").read_text()
    assert "sqlalchemy" not in dependencies.lower() and "alembic" not in dependencies.lower()
    assert 'env_prefix="PLZLINKS_' not in Path("app/platform/settings.py").read_text()
