# Release checklist

Version `0.1.0` is the current alpha. It has not been tagged, and it has not
been uploaded to PyPI. This checklist is the procedure for a later release.
Following it in this milestone does not create that release.

## What CI does

`.github/workflows/ci.yml` runs on pull requests to `main` and on pushes to
`main`. Its permission is `contents: read`. It lints, checks formatting,
type-checks, tests with coverage, builds the package, validates the wheel and
sdist, and installs both artifacts in clean environments.

That workflow does not create a Git tag, a GitHub release, or a PyPI upload.
There is no `workflow_dispatch` publish job, no PyPI environment, and no
`id-token: write` permission. Do not add publication to a workflow that runs
on ordinary branch pushes.

A future publish workflow, if the owner asks for one, must be a separate
file triggered only by `workflow_dispatch`, must name the version as an
explicit input, and must use the minimum permissions that upload needs. It
must not run from `push` or `pull_request`.

## Before changing the version

1. Choose the version. `0.1.0` remains the alpha until the owner selects the
   first public version. The features listed under `Unreleased` in
   `CHANGELOG.md` are not yet folded into a released section.
2. Confirm `main` is the commit that will be released, and that the working
   tree is clean.
3. Read `CHANGELOG.md` and move the `Unreleased` notes into the section for
   the chosen version. Do not leave shipped behavior only under `Unreleased`.
4. Set the same version in `pyproject.toml`, in `pyforge.__version__`, and in
   `EXPECTED_VERSION`, `EXPECTED_WHEEL`, and `EXPECTED_SDIST` inside
   `scripts/check_distribution.py`. The tests and the distribution check both
   require that string.
5. Keep `Development Status :: 3 - Alpha` unless the owner explicitly changes
   the support promise. Do not mark the package Production/Stable in the same
   edit that only tags the current alpha.
6. Review the [security notes](security.md). Redaction is not a universal
   secret scanner. `MemoryCache` is process memory. `temporary_env` is
   process-global for the names it changes.

## Final verification

Run these on the release commit:

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=pyforge --cov-report=term-missing
python -m build
python scripts/check_distribution.py
```

Install `dist/pyforge_toolkit-<version>-py3-none-any.whl` and the sdist in two
new virtual environments. Confirm `pyforge.__version__` matches the chosen
version and that the wheel metadata has no unconditional `Requires-Dist`.

Wait until GitHub Actions reports success for Python 3.11, 3.12, and 3.13 on
that commit. Python 3.12 and 3.13 are not assumed from a local 3.11 run.

## Tag, GitHub release, and PyPI

Do these only after the owner approves the release:

1. Create an annotated tag on the verified commit: `git tag -a v<version> -m "PyForge <version>"`.
2. Push that tag: `git push origin v<version>`.
3. Create a GitHub release from that tag. Use the changelog section as the
   body. Do not attach a different commit.
4. Upload the wheel and sdist built from that tag. Prefer a trusted publisher
   or an API token stored outside the repository. Do not commit a token.
5. Confirm PyPI shows the same version, `Requires-Python: >=3.11`, no runtime
   dependencies, and the MIT license.

## After publication

1. Install the published artifact in a clean environment with
   `python -m pip install pyforge-toolkit==<version>`.
2. Import `pyforge`, check `__version__`, and run one public call from retry,
   logging, configuration, HTTP decisions, observability, cache, and
   `pyforge.testing`.
3. Record the tag, the GitHub release URL, and the PyPI URL in the changelog.
4. If publication fails, do not reuse the version. Fix the problem and choose
   a new version.
