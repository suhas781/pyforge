"""Check the wheel and sdist produced by ``python -m build``.

Run this from the repository root after a build. It checks the artifacts in
``dist/`` and does not install them.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
EXPECTED_NAME = "pyforge-toolkit"
EXPECTED_VERSION = "0.1.0"
EXPECTED_WHEEL = "pyforge_toolkit-0.1.0-py3-none-any.whl"
EXPECTED_SDIST = "pyforge_toolkit-0.1.0.tar.gz"
EXPECTED_URLS = {
    "Changelog": "https://github.com/suhas781/pyforge/blob/main/CHANGELOG.md",
    "Documentation": "https://github.com/suhas781/pyforge/blob/main/docs/api-reference.md",
    "Homepage": "https://github.com/suhas781/pyforge",
    "Repository": "https://github.com/suhas781/pyforge",
}
EXPECTED_CLASSIFIERS = (
    "Development Status :: 3 - Alpha",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
)
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
_DIST_INFO = f"{EXPECTED_NAME.replace('-', '_')}-{EXPECTED_VERSION}.dist-info"
EXPECTED_DIST_INFO_FILES = (
    f"{_DIST_INFO}/METADATA",
    f"{_DIST_INFO}/WHEEL",
    f"{_DIST_INFO}/RECORD",
    f"{_DIST_INFO}/top_level.txt",
    f"{_DIST_INFO}/licenses/LICENSE",
)
# This is the member set produced by the current setuptools build. The license
# is permitted only at its dist-info path. Any other archive member is rejected.
EXPECTED_WHEEL_MEMBERS = frozenset([*WHEEL_FILES, *EXPECTED_DIST_INFO_FILES])


def main() -> None:
    """Validate the single wheel and source distribution in ``dist/``."""
    wheels = sorted(DIST.glob("*.whl"))
    sdists = sorted(DIST.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(f"Expected one wheel and one sdist in {DIST}, found {wheels=} {sdists=}")
    if wheels[0].name != EXPECTED_WHEEL:
        raise SystemExit(f"Unexpected wheel name: {wheels[0].name}")
    if sdists[0].name != EXPECTED_SDIST:
        raise SystemExit(f"Unexpected sdist name: {sdists[0].name}")
    _check_wheel(wheels[0])
    _check_sdist(sdists[0])
    print(f"Validated {wheels[0].name} and {sdists[0].name}")


def _check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        _reject_unexpected_wheel_members(path.name, names)
        missing = [item for item in WHEEL_FILES if item not in names]
        if missing:
            raise SystemExit(f"{path.name} is missing {missing}")
        _reject_unexpected_python_modules(path.name, names)
        _reject_sensitive_paths(path.name, names)
        if any(name.startswith("tests/") or "/tests/" in name for name in names):
            raise SystemExit(f"{path.name} contains tests")
        if not any(name.endswith("/LICENSE") or name.endswith("LICENSE") for name in names):
            raise SystemExit(f"{path.name} is missing the license")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        _check_metadata(archive.read(metadata_name).decode("utf-8"))
        wheel_name = next(name for name in names if name.endswith(".dist-info/WHEEL"))
        _check_wheel_tags(archive.read(wheel_name).decode("utf-8"))


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
    fields: dict[str, list[str]] = {}
    for line in metadata.splitlines():
        if not line or line.startswith((" ", "\t")) or ": " not in line:
            continue
        key, value = line.split(": ", 1)
        fields.setdefault(key, []).append(value)
    name = _one(fields, "Name")
    version = _one(fields, "Version")
    requires_python = _one(fields, "Requires-Python")
    if name != EXPECTED_NAME:
        raise SystemExit(f"Unexpected distribution name: {name}")
    if version != EXPECTED_VERSION:
        raise SystemExit(f"Unexpected version: {version}")
    if requires_python != ">=3.11":
        raise SystemExit(f"Unexpected Requires-Python: {requires_python}")
    license_values = fields.get("License-Expression", [])
    if license_values != ["MIT"]:
        raise SystemExit(f"Unexpected license expression: {license_values}")
    runtime_requirements = [
        value for value in fields.get("Requires-Dist", []) if "extra ==" not in value
    ]
    if runtime_requirements:
        raise SystemExit(f"Runtime dependencies are not allowed: {runtime_requirements}")
    urls: dict[str, str] = {}
    for value in fields.get("Project-URL", []):
        label, _, url = value.partition(", ")
        urls[label] = url
    if urls != EXPECTED_URLS:
        raise SystemExit(f"Unexpected project URLs: {urls}")
    classifiers = set(fields.get("Classifier", []))
    missing = [item for item in EXPECTED_CLASSIFIERS if item not in classifiers]
    if missing:
        raise SystemExit(f"Metadata is missing classifiers: {missing}")


def package_python_modules(names: list[str]) -> set[str]:
    """Return ``pyforge`` Python modules, ignoring wheel metadata.

    A module path starts with ``pyforge/`` and ends with ``.py``. A leading
    ``./`` is removed; a ``../`` prefix is left in place so it cannot satisfy
    an allow-list entry. Files under ``*.dist-info/`` are metadata even when
    their names end in ``.py``. ``py.typed`` and other non-Python package
    files are not modules.
    """
    modules: set[str] = set()
    for name in names:
        normalized = name.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if ".dist-info/" in normalized or normalized.endswith(".dist-info"):
            continue
        if normalized.startswith("pyforge/") and normalized.endswith(".py"):
            modules.add(normalized)
    return modules


def _normalize_wheel_member(name: str) -> str:
    """Return a wheel member path without collapsing parent segments.

    Backslashes become slashes, and a leading ``./`` is removed. ``../`` stays
    in the path so it cannot be rewritten into an allow-list entry.
    """
    normalized = name.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _wheel_member_problem(name: str) -> str | None:
    """Return why a raw archive member is unsafe, or ``None`` when it is well formed."""
    if name == "" or "\0" in name:
        return "malformed"
    slashed = name.replace("\\", "/")
    normalized = _normalize_wheel_member(name)
    if (
        slashed.startswith("/")
        or normalized.startswith("/")
        or (len(slashed) >= 2 and slashed[1] == ":")
        or (len(normalized) >= 2 and normalized[1] == ":")
    ):
        return "absolute"
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        return "traversal"
    if not normalized or any(part in {"", "."} for part in parts):
        return "malformed"
    return None


def _duplicates(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(item for item, count in counts.items() if count > 1)


def _reject_unexpected_wheel_members(label: str, names: list[str]) -> None:
    """Reject every wheel member outside the exact build allow-list.

    The allow-list is ``EXPECTED_WHEEL_MEMBERS``. Paths are normalized only by
    slash direction and a leading ``./``. Absolute paths, parent traversal,
    malformed paths, and duplicate members are rejected even when the remaining
    names match.
    """
    problems: list[str] = []
    normalized: list[str] = []
    for name in names:
        problem = _wheel_member_problem(name)
        if problem is not None:
            problems.append(f"{name} ({problem})")
            continue
        normalized.append(_normalize_wheel_member(name))
    duplicate_names = sorted(set(_duplicates(names)) | set(_duplicates(normalized)))
    found = set(normalized)
    missing = sorted(EXPECTED_WHEEL_MEMBERS - found)
    extra = sorted(found - EXPECTED_WHEEL_MEMBERS)
    if problems or duplicate_names or missing or extra:
        raise SystemExit(
            f"{label} members do not match the allow-list: "
            f"unsafe={problems} duplicate={duplicate_names} "
            f"missing={missing} extra={extra}"
        )


def _reject_unexpected_python_modules(label: str, names: list[str]) -> None:
    expected = {item for item in WHEEL_FILES if item.endswith(".py")}
    found = package_python_modules(names)
    missing = sorted(expected - found)
    extra = sorted(found - expected)
    if missing or extra:
        raise SystemExit(
            f"{label} Python modules do not match the allow-list: missing={missing} extra={extra}"
        )


def _check_wheel_tags(wheel_text: str) -> None:
    tags = [line.split(": ", 1)[1] for line in wheel_text.splitlines() if line.startswith("Tag: ")]
    pure = [
        line.split(": ", 1)[1]
        for line in wheel_text.splitlines()
        if line.startswith("Root-Is-Purelib: ")
    ]
    if tags != ["py3-none-any"] or pure != ["true"]:
        raise SystemExit(f"Unexpected wheel tags: {tags=} {pure=}")


def _one(fields: dict[str, list[str]], key: str) -> str:
    values = fields.get(key, [])
    if len(values) != 1:
        raise SystemExit(f"Expected one {key} field, found {values}")
    return values[0]


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
