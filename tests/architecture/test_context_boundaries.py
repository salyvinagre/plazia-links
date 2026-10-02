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
                            "smtplib",
                        }
                        or name.startswith(("app.platform", "app.interfaces"))
                        for name in names
                    ), path


def test_legacy_runtime_paths_and_dependencies_are_removed():
    for path in ("app/models", "app/services", "app/core", "migrations", "alembic.ini"):
        assert not Path(path).exists(), path
    dependencies = Path("pyproject.toml").read_text()
    assert "sqlalchemy" not in dependencies.lower() and "alembic" not in dependencies.lower()
    assert 'env_prefix="PLZLINKS_' not in Path("app/platform/settings.py").read_text()
