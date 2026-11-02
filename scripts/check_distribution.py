"""Check the wheel and sdist produced by ``python -m build``.

Run this from the repository root after a build. It checks the artifacts in
``dist/`` and does not install them.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
EXPECTED_NAME = "pyforge-toolkit"
EXPECTED_VERSION = "0.1.0"
WHEEL_FILES = (
    "pyforge/__init__.py",
    "pyforge/cache.py",
    "pyforge/config.py",
    "pyforge/http.py",
    "pyforge/logging.py",
    "pyforge/observe.py",
    "pyforge/retry.py",
    "pyforge/testing.py",
    "pyforge/py.typed",
)
SDIST_SUFFIXES = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "src/pyforge/__init__.py",
    "src/pyforge/cache.py",
    "src/pyforge/config.py",
    "src/pyforge/http.py",
    "src/pyforge/logging.py",
    "src/pyforge/observe.py",
    "src/pyforge/retry.py",
    "src/pyforge/testing.py",
    "src/pyforge/py.typed",
)


def main() -> None:
    """Validate the single wheel and source distribution in ``dist/``."""
    wheels = sorted(DIST.glob("*.whl"))
    sdists = sorted(DIST.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(f"Expected one wheel and one sdist in {DIST}, found {wheels=} {sdists=}")
    _check_wheel(wheels[0])
    _check_sdist(sdists[0])
    print(f"Validated {wheels[0].name} and {sdists[0].name}")


def _check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        missing = [item for item in WHEEL_FILES if item not in names]
        if missing:
            raise SystemExit(f"{path.name} is missing {missing}")
        _reject_sensitive_paths(path.name, names)
        if any(name.startswith("tests/") or "/tests/" in name for name in names):
            raise SystemExit(f"{path.name} contains tests")
        if not any(name.endswith("/LICENSE") or name.endswith("LICENSE") for name in names):
            raise SystemExit(f"{path.name} is missing the license")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        _check_metadata(archive.read(metadata_name).decode("utf-8"))


def _check_sdist(path: Path) -> None:
    with tarfile.open(path) as archive:
        names = archive.getnames()
    missing = [
        suffix for suffix in SDIST_SUFFIXES if not any(name.endswith(suffix) for name in names)
    ]
    if missing:
        raise SystemExit(f"{path.name} is missing {missing}")
    _reject_sensitive_paths(path.name, names)


def _check_metadata(metadata: str) -> None:
    fields: dict[str, str] = {}
    runtime_requirements: list[str] = []
    for line in metadata.splitlines():
        if not line or line.startswith((" ", "\t")) or ": " not in line:
            continue
        key, value = line.split(": ", 1)
        fields.setdefault(key, value)
        if key == "Requires-Dist" and "extra ==" not in value:
            runtime_requirements.append(value)
    if fields.get("Name") != EXPECTED_NAME:
        raise SystemExit(f"Unexpected distribution name: {fields.get('Name')}")
    if fields.get("Version") != EXPECTED_VERSION:
        raise SystemExit(f"Unexpected version: {fields.get('Version')}")
    if fields.get("Requires-Python") != ">=3.11":
        raise SystemExit(f"Unexpected Requires-Python: {fields.get('Requires-Python')}")
    if runtime_requirements:
        raise SystemExit(f"Runtime dependencies are not allowed: {runtime_requirements}")


def _reject_sensitive_paths(label: str, names: list[str]) -> None:
    blocked = [name for name in names if _is_sensitive(name)]
    if blocked:
        raise SystemExit(f"{label} contains sensitive paths: {blocked}")


def _is_sensitive(name: str) -> bool:
    filename = Path(name).name
    if filename == ".env.example":
        return False
    if filename == ".env" or filename.startswith(".env."):
        return True
    return filename.endswith((".pem", ".key")) or filename == "id_rsa"


if __name__ == "__main__":
    try:
        main()
    except StopIteration as exc:
        sys.exit(f"Distribution metadata was incomplete: {exc}")
