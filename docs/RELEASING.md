# Publishing bondbyisin

This repository is an independent Python client. Upload only the contents of
`bondbyisin-python/` to a new repository named `bondbyisin-python`, under the
GitHub account or organisation chosen for the Bond by ISIN brand.
No application servers, financial datasets or unrelated project files belong
in that repository.

## One-time owner setup

1. Create the GitHub repository and upload this source tree, including the
   hidden `.github/workflows/` directory. `pyproject.toml` must be at the
   repository root. Source distribution archives also contain the workflows.
   Use the `main` branch. Run the **Tests and package** workflow and verify
   its Python/OS matrix succeeds.
2. Sign into PyPI and TestPyPI. They are separate services and require separate
   accounts. Complete any email verification and two-factor authentication
   requested by the services. An existing PyPI login can own the new package;
   the package's name, metadata and runtime remain independent.
3. In the GitHub repository, create environments named `testpypi` and `pypi`
   under **Settings → Environments**. Add an active Bond by ISIN API key as an
   environment secret named `BOND_API_KEY` in `pypi`. It is used only by the
   live release checks and is never included in the distributions. The same
   secret in `testpypi` enables an earlier authenticated rehearsal.
4. Configure a pending Trusted Publisher on each index using this table.
   Substitute the actual GitHub owner. No PyPI token needs to be stored in
   the repository.

| Field | TestPyPI | PyPI |
| --- | --- | --- |
| Setup page | https://test.pypi.org/manage/account/publishing/ | https://pypi.org/manage/account/publishing/ |
| PyPI project name | `bondbyisin` | `bondbyisin` |
| GitHub owner | Your chosen account/organisation | Same owner |
| Repository name | `bondbyisin-python` | `bondbyisin-python` |
| Workflow filename | `release.yml` | `release.yml` |
| Environment name | `testpypi` | `pypi` |

A pending publisher does not reserve the package name. Successful first
publication creates the project. The workflow filename and environment must
match exactly. See the [official pending publisher guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Rehearse on TestPyPI

In **Actions → Publish Python package → Run workflow**, choose branch `main`
and target `testpypi`. The workflow tests, builds, validates and installs the
wheel, checks the public API examples, then uploads with Trusted Publishing.
If `BOND_API_KEY` is configured, it checks paid requests and pagination too.

Use a new virtual environment to verify the uploaded release. Install runtime
dependencies from ordinary PyPI, then fetch only this package from TestPyPI:

```bash
python -m pip install 'requests>=2.32.4,<3'
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps bondbyisin==0.1.0
python -c "from bondbyisin import Client; print(Client(api_key='').search('oracle')['returned'])"
```

Run `python scripts/smoke.py --require-key` with `BOND_API_KEY` set to verify
authenticated access. The release workflow requires this check before PyPI
publication; anonymous examples alone do not establish that paid access works.

## Publish to PyPI

Once the matrix, TestPyPI installation and authenticated checks pass:

1. Ensure `src/bondbyisin/_version.py` is the intended version.
2. Create a GitHub release with tag `v0.1.0` at the verified commit. Publishing
   the release triggers `release.yml` for the `pypi` environment. Alternatively,
   run the workflow manually from that tag with target `pypi`.
3. The workflow rejects a tag/version mismatch, checks the built wheel against
   the live API with the environment key, then publishes it to PyPI.
4. In another new environment, run `python -m pip install bondbyisin==0.1.0`,
   then run the public and authenticated smoke checks again.
5. Verify https://pypi.org/project/bondbyisin/ shows the correct version,
   description and Bond by ISIN website links. Update the site's API page
   with the installation example in `docs/WEBSITE_SNIPPET.html`.

## Later releases

Bump `_version.py`, update `CHANGELOG.md`, run the checks, rehearse on TestPyPI
and create the matching `vX.Y.Z` release. A published filename/version cannot
be overwritten. Correct a faulty release with a new version; PyPI also supports
yanking releases to discourage new installations while preserving history.

## Local build without GitHub

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
python -m build
python scripts/check_dist.py
```

This produces `dist/bondbyisin-0.1.0-py3-none-any.whl` and
`dist/bondbyisin-0.1.0.tar.gz`. The automated route above is preferred, but the
same files can be uploaded with Twine using credentials entered locally:

```bash
python -m twine upload --repository testpypi dist/*
# After the TestPyPI and authenticated checks:
python -m twine upload dist/*
```

Do not put credentials in source files, shell command arguments or chat.
See [Python's packaging tutorial](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
for the manual token workflow.
