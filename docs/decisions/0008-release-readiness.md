# ADR 0008: No automatic publication

- Status: Accepted
- Date: 2026-11-03

## Context

The library is an alpha at version `0.1.0`. Retry, logging, configuration,
HTTP decisions, retry events, a process-local cache, and test helpers are on
`main`. None of that has been tagged or uploaded to PyPI.

A release workflow that runs on push could publish an unreviewed commit. When
this decision was accepted, the changelog listed most of the library under
`Unreleased`, so a tag of the then-current `0.1.0` section would have
described an older subset of the code.

## Decision

Keep version `0.1.0`. Do not create a tag, a GitHub release, or a PyPI upload
as part of the readiness work.

Record project URLs and the Python version classifiers in the package
metadata. The license remains the `MIT` license expression. Setuptools
rejects the older MIT license classifier when that expression is set.
`scripts/check_distribution.py` rejects a wheel that is not
`py3-none-any`, a license expression other than `MIT`, a runtime dependency,
or a missing project URL.

CI stays a quality workflow with `contents: read`. It does not publish.
Publication, when the owner requests it, has to be a separate explicit
action. The steps live in `docs/releasing.md`.

The public Python API is unchanged.

## Alternatives

- Tag `0.1.0` now: rejected. The owner has not approved a release. Describing
  the source tree in the changelog is not publication.
- Publish from the existing CI job: rejected. A push to `main` would become
  an upload, and the job would need credentials it does not have.
- Add a `workflow_dispatch` uploader in this change: rejected. An uploader
  with a token or trusted-publisher permission is a release action. The
  checklist comes first, while the owner still has to approve the version.

## Later

A documentation edit after this decision described the implemented
capabilities in the changelog's `0.1.0` section. That section still states
that no tag and no PyPI upload exist. Owner approval is still required before
either one.

## Consequences

The package can be installed from a checkout. It cannot be installed from
PyPI until a later, approved release.

The distribution check will fail if a future release changes the version,
license, or URLs and forgets to update the expected constants. That failure
is intentional.

Callers of the Python API see the same names and behavior as before this
decision.
