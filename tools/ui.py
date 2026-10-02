"""Build Tailwind/daisyUI as in the daisyUI Django guide, using standalone releases."""

import hashlib
import json
import platform
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/ui"
ASSETS = json.loads((ROOT / "tools/ui-assets.json").read_text())


def fetch(name: str) -> Path:
    asset = ASSETS[name]
    target = CACHE / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == asset["sha256"]:
        return target
    response = httpx.get(asset["url"], follow_redirects=True, timeout=60)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != asset["sha256"]:
        raise ValueError(f"Checksum mismatch for {name}")
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(response.content)
    temporary.replace(target)
    return target


def build() -> None:
    system = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}[platform.system()]
    machine = platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}[machine]
    executable = f"tailwindcss-{system}-{arch}" + (".exe" if system == "windows" else "")
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        compiler, _, _, htmx = executor.map(
            fetch, (executable, "daisyui.mjs", "daisyui-theme.mjs", "htmx.min.js")
        )
    compiler.chmod(0o755)
    subprocess.run(
        [
            str(compiler),
            "-i",
            "app/static/css/identity.source.css",
            "-o",
            "app/static/css/identity.css",
            "--minify",
        ],
        cwd=ROOT,
        check=True,
    )
    shutil.copyfile(htmx, ROOT / "app/static/js/htmx.min.js")


if __name__ == "__main__":
    build()
