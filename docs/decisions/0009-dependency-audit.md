# ADR 0009: Audit installed packages with OSV

- Status: Accepted
- Date: 2026-11-03

## Context

The library has no runtime dependencies. The development extra and the
build-system requirements do. CI previously did not compare those installed
versions with a vulnerability database, and the Actions were pinned only to
moving major tags.

Adding a scanner package would put another third-party tree into the
development environment. The package under audit, `pyforge-toolkit`, is not
on PyPI, so a scanner cannot look it up there.

## Decision

Query the public OSV database from `scripts/audit_installed_packages.py`,
using only the standard library. CI runs the script after installing
`setuptools>=77`, `wheel`, and the development extra. The workflow permission
stays `contents: read`. The script skips `pyforge-toolkit`.

A response with no advisories is recorded as "none returned." It is not
treated as proof that the packages or this repository have no
vulnerabilities. A failed query exits with status 2 so a network problem is
not reported as a clean audit.

`actions/checkout` and `actions/setup-python` are pinned to the verified
commits named in `docs/security.md`.

## Alternatives

- `pip-audit` as a development dependency: it is a known client, and it also
  queries OSV. It was not added because it brings its own third-party
  packages into every development install.
- Ignore vulnerabilities in the base interpreter's `setuptools`: rejected.
  An old copy is a real finding. The remediation is to install the
  build-system floor before auditing.

## Consequences

CI needs network access for the audit step. The result changes when OSV
publishes a new advisory for an installed version, even if this repository
did not change.

The audit does not inspect the isolated environment created later by
`python -m build` unless that environment is the one executing the script.
