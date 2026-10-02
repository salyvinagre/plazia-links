"""Executable dependency boundaries for the contexts introduced in PR #2.

The inherited Zly tree is not claimed to be hexagonal. These checks protect the
new contexts and their public HTTP/CLI entry points without blanket exceptions.
"""

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXTS = ROOT / "app/contexts"


def imports(path: Path) -> list[str]:
    package = ".".join(path.relative_to(ROOT).with_suffix("").parts[:-1])
    result = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                name = importlib.util.resolve_name("." * node.level + name, package)
            result.append(name)
    return result


def test_domain_and_application_depend_only_inward() -> None:
    failures = []
    for path in CONTEXTS.rglob("*.py"):
        parts = path.relative_to(CONTEXTS).parts
        if len(parts) < 3 or parts[1] not in {"domain", "application"}:
            continue
        context, layer = parts[:2]
        own = f"app.contexts.{context}."
        for module in imports(path):
            if module.split(".")[0] in sys.stdlib_module_names:
                continue
            if module.startswith(own):
                target_layer = module[len(own) :].split(".")[0]
                allowed = {"domain"} if layer == "domain" else {"domain", "application"}
                if target_layer in allowed:
                    continue
            if (
                layer == "application"
                and module.startswith("app.contexts.")
                and module.endswith(".contracts")
            ):
                continue
            failures.append(f"{path.relative_to(ROOT)} -> {module}")
    assert failures == []


def test_cross_context_imports_use_published_contracts() -> None:
    failures = []
    for path in CONTEXTS.rglob("*.py"):
        context = path.relative_to(CONTEXTS).parts[0]
        for module in imports(path):
            if module.startswith("app.contexts."):
                target = module.split(".")[2]
                if target != context and not module.endswith(".contracts"):
                    failures.append(f"{path.relative_to(ROOT)} -> {module}")
    assert failures == []


def test_delivery_adapters_do_not_import_context_internals() -> None:
    paths = [
        ROOT / "app/api/managed_links.py",
        ROOT / "app/routes/identity.py",
        ROOT / "app/core/identity.py",
        ROOT / "app/schemas/managed_link.py",
        ROOT / "app/cli.py",
    ]
    failures = [
        f"{path.relative_to(ROOT)} -> {module}"
        for path in paths
        for module in imports(path)
        if module.startswith("app.contexts.") and not module.endswith(".contracts")
    ]
    assert failures == []


def test_repository_has_no_transport_schema_or_legacy_service_dependency() -> None:
    names = imports(CONTEXTS / "links/adapters/repository.py")
    assert not any(name.startswith(("app.schemas", "app.services", "fastapi")) for name in names)


def test_context_core_imports_without_site_packages_or_configuration() -> None:
    modules = [
        ".".join(path.relative_to(ROOT).with_suffix("").parts)
        for path in CONTEXTS.rglob("*.py")
        if path.name != "__init__.py"
        and any(part in {"domain", "application"} for part in path.parts)
    ]
    script = "import importlib\n" + "\n".join(
        f"importlib.import_module({module!r})" for module in modules
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT)},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
