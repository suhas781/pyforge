"""Allow-list checks for wheel members and Python modules."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.check_distribution import (
    EXPECTED_WHEEL_MEMBERS,
    SDIST_SUFFIXES,
    WHEEL_FILES,
    package_python_modules,
)
from scripts.check_distribution import _check_sdist as check_sdist
from scripts.check_distribution import _check_wheel as check_wheel
from scripts.check_distribution import (
    _reject_unexpected_python_modules as reject_modules,
)
from scripts.check_distribution import (
    _reject_unexpected_wheel_members as reject_members,
)

WHEEL_METADATA = """\
Metadata-Version: 2.4
Name: pyforge-toolkit
Version: 0.1.0
License-Expression: MIT
Requires-Python: >=3.11
Classifier: Development Status :: 3 - Alpha
Classifier: Programming Language :: Python :: 3.11
Classifier: Programming Language :: Python :: 3.12
Classifier: Programming Language :: Python :: 3.13
Project-URL: Changelog, https://github.com/suhas781/pyforge/blob/main/CHANGELOG.md
Project-URL: Documentation, https://github.com/suhas781/pyforge/blob/main/docs/api-reference.md
Project-URL: Homepage, https://github.com/suhas781/pyforge
Project-URL: Repository, https://github.com/suhas781/pyforge
"""
WHEEL_TAGS = "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"

EXPECTED_MODULES = {
    "pyforge/__init__.py",
    "pyforge/cache.py",
    "pyforge/config.py",
    "pyforge/http.py",
    "pyforge/logging.py",
    "pyforge/observe.py",
    "pyforge/retry.py",
    "pyforge/testing.py",
}
METADATA = [
    "pyforge/py.typed",
    "pyforge_toolkit-0.1.0.dist-info/METADATA",
    "pyforge_toolkit-0.1.0.dist-info/WHEEL",
    "pyforge_toolkit-0.1.0.dist-info/RECORD",
    "pyforge_toolkit-0.1.0.dist-info/top_level.txt",
    "pyforge_toolkit-0.1.0.dist-info/licenses/LICENSE",
    "pyforge_toolkit-0.1.0.dist-info/vendor.py",
]


def test_expected_module_set_matches_the_wheel_allow_list() -> None:
    assert {item for item in WHEEL_FILES if item.endswith(".py")} == EXPECTED_MODULES
    names = sorted(EXPECTED_MODULES) + METADATA
    assert package_python_modules(names) == EXPECTED_MODULES
    reject_modules("wheel", names)


def test_missing_python_module_is_rejected() -> None:
    names = sorted(EXPECTED_MODULES - {"pyforge/cache.py"}) + METADATA
    with pytest.raises(SystemExit, match="pyforge/cache.py"):
        reject_modules("wheel", names)


def test_extra_python_module_is_rejected() -> None:
    names = (
        sorted(EXPECTED_MODULES)
        + METADATA
        + [
            "pyforge/extra.py",
            "pyforge/nested/hidden.py",
        ]
    )
    with pytest.raises(SystemExit, match="pyforge/extra.py") as raised:
        reject_modules("wheel", names)
    message = str(raised.value)
    assert "pyforge/nested/hidden.py" in message
    assert "vendor.py" not in message


def test_parent_directory_prefix_does_not_satisfy_the_allow_list() -> None:
    names = sorted(EXPECTED_MODULES - {"pyforge/cache.py"}) + ["../pyforge/cache.py"]
    assert "pyforge/cache.py" not in package_python_modules(names)
    with pytest.raises(SystemExit, match="pyforge/cache.py") as raised:
        reject_modules("wheel", names)
    assert "pyforge/cache.py" in str(raised.value)


def test_dot_slash_prefix_matches_the_allow_list() -> None:
    names = sorted(EXPECTED_MODULES - {"pyforge/cache.py"}) + [
        "./pyforge/cache.py",
        ".\\pyforge\\extra.py",
    ]
    found = package_python_modules(names)
    assert found == EXPECTED_MODULES | {"pyforge/extra.py"}
    with pytest.raises(SystemExit, match="pyforge/extra.py"):
        reject_modules("wheel", names)


def test_wheel_allow_list_is_the_current_build_contract() -> None:
    assert EXPECTED_WHEEL_MEMBERS == {
        "pyforge/__init__.py",
        "pyforge/cache.py",
        "pyforge/config.py",
        "pyforge/http.py",
        "pyforge/logging.py",
        "pyforge/observe.py",
        "pyforge/retry.py",
        "pyforge/testing.py",
        "pyforge/py.typed",
        "pyforge_toolkit-0.1.0.dist-info/METADATA",
        "pyforge_toolkit-0.1.0.dist-info/WHEEL",
        "pyforge_toolkit-0.1.0.dist-info/RECORD",
        "pyforge_toolkit-0.1.0.dist-info/top_level.txt",
        "pyforge_toolkit-0.1.0.dist-info/licenses/LICENSE",
    }
    assert "pyforge/py.typed" in EXPECTED_WHEEL_MEMBERS
    reject_members("wheel", sorted(EXPECTED_WHEEL_MEMBERS))


@pytest.mark.parametrize(
    "member",
    [
        "pyforge/extra.pth",
        "pyforge/extra.so",
        "pyforge/extra.dll",
        "pyforge/extra.dat",
        "pyforge/nested/hidden.dat",
        "pyforge/nested/__init__.py",
        "pyforge/nested/",
        "pyforge_toolkit-0.1.0.dist-info/vendor.py",
    ],
)
def test_unexpected_wheel_member_is_rejected(member: str) -> None:
    names = sorted(EXPECTED_WHEEL_MEMBERS) + [member]
    with pytest.raises(SystemExit) as raised:
        reject_members("wheel", names)
    assert member in str(raised.value)


def test_duplicate_wheel_members_are_rejected() -> None:
    names = sorted(EXPECTED_WHEEL_MEMBERS) + ["pyforge/__init__.py", "./pyforge/cache.py"]
    with pytest.raises(SystemExit) as raised:
        reject_members("wheel", names)
    message = str(raised.value)
    assert "pyforge/__init__.py" in message
    assert "pyforge/cache.py" in message


@pytest.mark.parametrize(
    "member",
    [
        "/pyforge/extra.pth",
        "C:/pyforge/extra.pth",
        "C:\\pyforge\\extra.dll",
        "./C:/pyforge/extra.dat",
    ],
)
def test_absolute_wheel_paths_are_rejected(member: str) -> None:
    names = sorted(EXPECTED_WHEEL_MEMBERS) + [member]
    with pytest.raises(SystemExit) as raised:
        reject_members("wheel", names)
    message = str(raised.value)
    assert "absolute" in message
    assert "extra." in message


@pytest.mark.parametrize(
    "member", ["../pyforge/cache.py", "pyforge/../extra.pth", "./../pyforge/extra.so"]
)
def test_parent_traversal_is_rejected(member: str) -> None:
    names = sorted(EXPECTED_WHEEL_MEMBERS) + [member]
    with pytest.raises(SystemExit) as raised:
        reject_members("wheel", names)
    assert member in str(raised.value)
    assert "traversal" in str(raised.value)


def test_parent_prefix_does_not_satisfy_a_missing_member() -> None:
    names = sorted(EXPECTED_WHEEL_MEMBERS - {"pyforge/cache.py"}) + ["../pyforge/cache.py"]
    with pytest.raises(SystemExit) as raised:
        reject_members("wheel", names)
    message = str(raised.value)
    assert "pyforge/cache.py" in message
    assert "../pyforge/cache.py" in message


@pytest.mark.parametrize("member", ["pyforge//extra.dat", "pyforge/./extra.pth", ""])
def test_malformed_wheel_paths_are_rejected(member: str) -> None:
    names = sorted(EXPECTED_WHEEL_MEMBERS) + [member]
    with pytest.raises(SystemExit) as raised:
        reject_members("wheel", names)
    assert "malformed" in str(raised.value)


def test_slash_and_dot_slash_forms_match_allowed_members() -> None:
    names = sorted(EXPECTED_WHEEL_MEMBERS - {"pyforge/cache.py", "pyforge/http.py"})
    names.extend(["./pyforge/cache.py", "pyforge\\http.py"])
    reject_members("wheel", names)


def _write_wheel(path: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            if name.endswith("/METADATA"):
                payload = WHEEL_METADATA
            elif name.endswith("/WHEEL"):
                payload = WHEEL_TAGS
            else:
                payload = "ok"
            archive.writestr(name, payload)


def _write_sdist(path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        payloads = [f"pyforge_toolkit-0.1.0/{suffix}" for suffix in SDIST_SUFFIXES]
        payloads.append("pyforge_toolkit-0.1.0/playground/server.py")
        for name in payloads:
            data = b"ok"
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_fixture_wheel_and_sdist_match_the_contract(tmp_path: Path) -> None:
    wheel_path = tmp_path / "demo.whl"
    _write_wheel(wheel_path, sorted(EXPECTED_WHEEL_MEMBERS))
    check_wheel(wheel_path)

    extra_wheel = tmp_path / "extra.whl"
    _write_wheel(extra_wheel, sorted(EXPECTED_WHEEL_MEMBERS) + ["pyforge/extra.pth"])
    with pytest.raises(SystemExit, match="pyforge/extra.pth"):
        check_wheel(extra_wheel)

    sdist_path = tmp_path / "demo.tar.gz"
    _write_sdist(sdist_path)
    check_sdist(sdist_path)
