"""Allow-list checks for Python modules inside the wheel."""

from __future__ import annotations

import pytest

from scripts.check_distribution import WHEEL_FILES, package_python_modules
from scripts.check_distribution import (
    _reject_unexpected_python_modules as reject_modules,
)

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
