"""Tests for the OSV report helper. They do not contact the network."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_installed_packages.py"
if not _PATH.is_file():
    pytest.skip(
        "scripts/audit_installed_packages.py is a repository tool and is not in this tree",
        allow_module_level=True,
    )
_SPEC = importlib.util.spec_from_file_location("audit_installed_packages", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


def test_advisory_ids_reject_incomplete_results() -> None:
    assert audit.advisory_ids({}) == []
    assert audit.advisory_ids({"vulns": [{"id": "GHSA-1"}]}) == ["GHSA-1"]
    with pytest.raises(ValueError, match="paginated"):
        audit.advisory_ids({"next_page_token": "more"})
    with pytest.raises(ValueError, match="not an object"):
        audit.advisory_ids([])
    with pytest.raises(ValueError, match="no id"):
        audit.advisory_ids({"vulns": [{}]})


def test_render_reports_findings_and_a_limited_clean_result() -> None:
    clean = io.StringIO()
    assert audit.render([("pip", "26.2")], [{}], clean) == 0
    assert "not a claim" in clean.getvalue()
    found = io.StringIO()
    assert audit.render([("setuptools", "65.5.0")], [{"vulns": [{"id": "PYSEC-1"}]}], found) == 1
    assert "PYSEC-1" in found.getvalue()


def test_selected_packages_skips_this_project(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Distribution:
        def __init__(self, name: str, version: str) -> None:
            self.metadata = {"Name": name}
            self.version = version

    monkeypatch.setattr(
        audit.metadata,
        "distributions",
        lambda: [
            _Distribution("pyforge-toolkit", "0.1.0"),
            _Distribution("pip", "26.2"),
            _Distribution("", "1"),
        ],
    )
    assert audit.selected_packages() == [("pip", "26.2")]
