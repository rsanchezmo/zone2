"""The project's layering, read from the source: routers don't import each other, the agent and the
services never import a router, zone2 never imports the backend, and the app starts without
Pydantic AI or OpenAI (they cost ~60 MB on the Pi and load when the chat first opens)."""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from zone2.paths import PROJECT_ROOT


def modules(package: str) -> list[Path]:
    return sorted((PROJECT_ROOT / package).rglob("*.py"))


def imported(path: Path, root: Path = PROJECT_ROOT) -> set[str]:
    """Every module `path` imports, relative imports resolved, `from a import b` as both a and a.b."""
    package = ".".join(path.relative_to(root).with_suffix("").parts[:-1])
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.split(".")[:len(package.split(".")) - node.level + 1]
                base = ".".join([*parent, base] if base else parent)
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def offenders(package: str, forbidden: str) -> dict[str, list[str]]:
    found = {}
    for path in modules(package):
        own = ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
        bad = sorted(n for n in imported(path) if (n == forbidden or n.startswith(forbidden + ".")) and n != own)
        if bad:
            found[str(path.relative_to(PROJECT_ROOT))] = bad
    return found


def test_the_import_reader_resolves_relative_imports(tmp_path: Path):
    path = tmp_path / "backend" / "routers" / "mod.py"
    path.parent.mkdir(parents=True)
    path.write_text("import os.path\nfrom . import goals\nfrom ..services.sync import status\n")
    assert imported(path, tmp_path) == {"os.path", "backend.routers", "backend.routers.goals",
                                        "backend.services.sync", "backend.services.sync.status"}


def test_routers_do_not_import_each_other():
    for path in modules("backend/routers"):
        own = ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
        others = sorted(n for n in imported(path) if n.startswith("backend.routers.") and n != own)
        assert not others, f"{path.name} imports {others}: move what they share to backend/services"


@pytest.mark.parametrize("package", ["backend/agent", "backend/services"])
def test_the_agent_and_the_services_never_import_a_router(package: str):
    assert offenders(package, "backend.routers") == {}


def test_zone2_never_imports_the_backend():
    assert offenders("zone2", "backend") == {}


def test_the_app_starts_without_pydantic_ai_or_openai(tmp_path: Path):
    probe = (
        "import pathlib, sys\n"
        "import zone2.paths\n"
        f"zone2.paths.ENV_FILE = pathlib.Path({str(tmp_path / '.env')!r})\n"
        "import backend.app\n"
        "heavy = sorted({m.split('.')[0] for m in sys.modules} & {'pydantic_ai', 'openai'})\n"
        "print(','.join(heavy))\n"
    )
    env = {**os.environ, "STRAVA_WEB_DATA_DIR": str(tmp_path / "data"), "STRAVA_WEB_WORKDIR": str(tmp_path / "work")}
    done = subprocess.run([sys.executable, "-c", probe], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == ""
