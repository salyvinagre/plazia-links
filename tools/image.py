"""Build from a small materialized source context; exclude local environments and credentials."""

import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    with tempfile.TemporaryDirectory(prefix="plzl-image-") as directory:
        context = Path(directory)
        project = context / "plazia-links"
        project.mkdir()
        for filename in ("pyproject.toml", "uv.lock"):
            shutil.copy2(ROOT / filename, project / filename)
        for dirname in ("app", "worker"):
            shutil.copytree(
                ROOT / dirname,
                project / dirname,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            )
        manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
        for source in manifest["tool"]["uv"]["sources"].values():
            original = (ROOT / source["path"]).resolve()
            target = context / "plazia" / "packages" / original.name
            target.mkdir(parents=True)
            shutil.copy2(original / "pyproject.toml", target / "pyproject.toml")
            shutil.copytree(
                original / "src",
                target / "src",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            )
        engine = os.getenv("CONTAINER", "podman")
        format_args = ["--format", "docker"] if Path(engine).name == "podman" else []
        subprocess.run(
            [
                engine,
                "build",
                *format_args,
                "--rm",
                "-f",
                str(ROOT / "infrastructure/Dockerfile"),
                "-t",
                "plazia-links:local",
                str(context),
            ],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    build()
