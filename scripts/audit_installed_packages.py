"""Ask OSV which installed third-party packages have published advisories.

The script reads the environment that is running it. It skips
``pyforge-toolkit`` because that distribution is not on PyPI. A run that
prints no advisories means OSV returned none for those names and versions at
that moment. It does not mean the packages, or PyForge, have no
vulnerabilities.

Exit status is ``0`` when every query returns no advisory, ``1`` when at
least one advisory is returned, and ``2`` when the query cannot be completed.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import sys
import urllib.request
from typing import TextIO

OSV_QUERYBATCH = "https://api.osv.dev/v1/querybatch"
SKIPPED_DISTRIBUTIONS = frozenset({"pyforge-toolkit"})


def selected_packages() -> list[tuple[str, str]]:
    """Return installed name/version pairs that this audit can query."""
    packages: list[tuple[str, str]] = []
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        version = distribution.version
        if not isinstance(name, str) or not name or not version:
            continue
        if name.casefold() in SKIPPED_DISTRIBUTIONS:
            continue
        packages.append((name, version))
    return sorted(packages, key=lambda item: item[0].casefold())


def advisory_ids(result: object) -> list[str]:
    """Return advisory identifiers from one OSV batch result."""
    if not isinstance(result, dict):
        raise ValueError("OSV result was not an object")
    if "next_page_token" in result:
        raise ValueError("OSV result was paginated")
    vulns = result.get("vulns") or []
    if not isinstance(vulns, list):
        raise ValueError("OSV vulnerabilities were not a list")
    identifiers: list[str] = []
    for vuln in vulns:
        if not isinstance(vuln, dict):
            raise ValueError("OSV vulnerability was not an object")
        identifier = vuln.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("OSV vulnerability had no id")
        identifiers.append(identifier)
    return identifiers


def query_osv(packages: list[tuple[str, str]]) -> list[object]:
    """Return one OSV result object for each package, in the same order."""
    if not packages:
        return []
    body = {
        "queries": [
            {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
            for name, version in packages
        ]
    }
    request = urllib.request.Request(
        OSV_QUERYBATCH,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "pyforge-audit"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"OSV query failed: {exc}") from exc
    if not isinstance(payload, dict) or "next_page_token" in payload:
        raise RuntimeError("OSV response was incomplete")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != len(packages):
        raise RuntimeError("OSV response did not contain one result per package")
    return results


def render(packages: list[tuple[str, str]], results: list[object], output: TextIO) -> int:
    """Write the audit report and return the process status."""
    findings = 0
    for (name, version), result in zip(packages, results, strict=True):
        identifiers = advisory_ids(result)
        if identifiers:
            findings += len(identifiers)
            print(f"{name} {version}: {', '.join(identifiers)}", file=output)
        else:
            print(f"{name} {version}: no advisory returned", file=output)
    if findings:
        print(
            f"{findings} OSV advisory id(s) matched installed versions.",
            file=output,
        )
        return 1
    print(
        "No OSV advisory was returned for the queried versions. "
        "This is not a claim that those packages have no vulnerabilities.",
        file=output,
    )
    return 0


def main() -> int:
    """Query OSV and return the process status."""
    packages = selected_packages()
    print("Skipped distributions not on PyPI: pyforge-toolkit", file=sys.stdout)
    try:
        results = query_osv(packages)
        return render(packages, results, sys.stdout)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
