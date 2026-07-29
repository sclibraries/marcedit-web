# TASK-174 Phase 1 Product Identity and Licensing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Parent ticket:** [TASK-174](../../../.tickets/TASK-174-smith-metadata-studio-open-task-migration.md)

**Child ticket:** [TASK-176](../../../.tickets/TASK-176-neutral-product-identity-licensing.md)

**Design:** [Smith Metadata Studio and Open Task Migration](../specs/2026-07-29-smith-metadata-studio-open-task-migration-design.md)

**Goal:** Establish the approved name-neutral product and licensing baseline
without changing any production route, service, package, path, or environment
identifier.

**Architecture:** Add one dependency-free product-name constant and consume it
at the four current Streamlit brand surfaces. Repository and image licensing
material is explicit and test-covered. Existing technical identifiers remain
compatibility contracts and are guarded by regression assertions.

**Tech Stack:** Python 3.9, Streamlit 1.50, pytest 8, Docker, Markdown,
`pyproject.toml`.

## Global Constraints

- The interim user-facing value is exactly
  `Smith College Libraries MARC21 workflow application`.
- Do not select `Smith Metadata Studio` as the public identity until Smith's
  institutional approval is recorded.
- Keep `marcedit-web`, `marcedit_web`, `/marcedit-web/`,
  `MARCEDIT_WEB_*`, all Docker service names, filesystem paths, and systemd
  units unchanged.
- Use MarcEdit only to identify the external format accepted by the optional
  migration adapter; do not claim compatibility beyond tested signatures.
- Do not change `.streamlit/config.toml`; activity-header work belongs to
  TASK-175.
- Do not change deployment units, proxy routes, install scripts, or ITS
  instructions; that work belongs to TASK-173.
- This child adds no native-task schema, storage, compiler, or migration code.
- Use TDD for every behavior change, report every skip, and do not mark
  TASK-176 Completed before final verification and review.

## File Map

- Create `marcedit_web/lib/product_identity.py`: dependency-free source of the
  interim user-facing product name.
- Create `tests/test_product_identity.py`: constant, UI-routing, legal-copy,
  notice, Docker-packaging, and compatibility-identifier regressions.
- Modify `marcedit_web/App.py`: use the constant for Streamlit's browser page
  title.
- Modify `marcedit_web/views/00_Home.py`: use the constant for the Home title
  and sidebar brand.
- Modify `marcedit_web/views/6_Diff.py`: use the constant for the Diff sidebar
  brand.
- Create `LICENSE`: MIT license for Smith College.
- Create `THIRD_PARTY_NOTICES.md`: direct runtime dependency names, licenses,
  and upstream sources.
- Modify `README.md`: neutral heading, independent-product description, and
  disclaimer while retaining technical setup/deployment identifiers.
- Modify `pyproject.toml`: neutral project description while retaining the
  distribution name.
- Modify `Dockerfile`: copy `LICENSE` and `THIRD_PARTY_NOTICES.md` into
  `/app`.
- Modify `.tickets/TASK-176-neutral-product-identity-licensing.md`: execution
  status and final evidence.
- Modify `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`: link
  the completed Phase 1 checkpoint without completing the parent program.

---

### Task 1: Activate TASK-176 and add the product identity contract

**Files:**
- Modify: `.tickets/TASK-176-neutral-product-identity-licensing.md`
- Create: `tests/test_product_identity.py`
- Create: `marcedit_web/lib/product_identity.py`

**Interfaces:**
- Consumes: no application interface; the exact interim value comes from the
  approved TASK-174 design.
- Produces: `marcedit_web.lib.product_identity.PRODUCT_NAME: str`.

- [ ] **Step 1: Mark the child ticket In-Progress**

Change only:

```text
Status: Todo
```

to:

```text
Status: In-Progress
```

- [ ] **Step 2: Write the failing constant test**

Create `tests/test_product_identity.py` with:

```python
"""Product identity and licensing boundaries for TASK-176."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_NAME = "Smith College Libraries MARC21 workflow application"


def test_interim_product_name_is_neutral_and_centralized():
    from marcedit_web.lib import product_identity

    assert product_identity.PRODUCT_NAME == PRODUCT_NAME
    assert "MarcEdit" not in product_identity.PRODUCT_NAME
```

- [ ] **Step 3: Run the test to prove the contract does not exist**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:dev \
  python -m pytest \
    tests/test_product_identity.py::test_interim_product_name_is_neutral_and_centralized \
    -q
```

Expected: FAIL because `marcedit_web.lib.product_identity` cannot be imported.

- [ ] **Step 4: Add the minimal product identity module**

Create `marcedit_web/lib/product_identity.py` with:

```python
"""User-facing product identity.

Technical compatibility names such as ``marcedit_web`` and
``MARCEDIT_WEB_*`` do not derive from this value.
"""

from __future__ import annotations


PRODUCT_NAME = "Smith College Libraries MARC21 workflow application"
```

- [ ] **Step 5: Run the focused test**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:dev \
  python -m pytest tests/test_product_identity.py -q
```

Expected: `1 passed`.

- [ ] **Step 6: Commit the identity contract**

```bash
git add \
  .tickets/TASK-176-neutral-product-identity-licensing.md \
  marcedit_web/lib/product_identity.py \
  tests/test_product_identity.py
git commit -m "feat: add neutral product identity contract"
```

---

### Task 2: Route every current Streamlit product-name surface through the constant

**Files:**
- Modify: `tests/test_product_identity.py`
- Modify: `marcedit_web/App.py`
- Modify: `marcedit_web/views/00_Home.py`
- Modify: `marcedit_web/views/6_Diff.py`

**Interfaces:**
- Consumes: `product_identity.PRODUCT_NAME: str` from Task 1.
- Produces: browser page title, Home page title, Home sidebar brand, and Diff
  sidebar brand driven by that constant.

- [ ] **Step 1: Add failing UI-routing assertions**

Append to `tests/test_product_identity.py`:

```python
def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_current_streamlit_brand_surfaces_use_product_name_constant():
    app = _source("marcedit_web/App.py")
    home = _source("marcedit_web/views/00_Home.py")
    diff = _source("marcedit_web/views/6_Diff.py")

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in app
    assert "page_title=PRODUCT_NAME" in app

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in home
    assert "st.title(PRODUCT_NAME)" in home
    assert "st.header(PRODUCT_NAME)" in home

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in diff
    assert "st.header(PRODUCT_NAME)" in diff


def test_current_streamlit_brand_calls_do_not_embed_legacy_name():
    app = _source("marcedit_web/App.py")
    home = _source("marcedit_web/views/00_Home.py")
    diff = _source("marcedit_web/views/6_Diff.py")

    assert 'page_title="marcedit-web"' not in app
    assert 'st.title("marcedit-web")' not in home
    assert 'st.header("marcedit-web")' not in home
    assert 'st.header("marcedit-web")' not in diff
```

- [ ] **Step 2: Run the routing tests and verify they fail**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:dev \
  python -m pytest tests/test_product_identity.py -q
```

Expected: 2 failures identifying the embedded UI strings; the Task 1 constant
test remains passing.

- [ ] **Step 3: Route the App browser title through the constant**

In `marcedit_web/App.py`, add:

```python
from marcedit_web.lib.product_identity import PRODUCT_NAME
```

Then replace:

```python
page_title="marcedit-web",
```

with:

```python
page_title=PRODUCT_NAME,
```

- [ ] **Step 4: Route the Home title and sidebar through the constant**

In `marcedit_web/views/00_Home.py`, add:

```python
from marcedit_web.lib.product_identity import PRODUCT_NAME
```

Replace the product heading calls with:

```python
st.title(PRODUCT_NAME)
```

and:

```python
st.header(PRODUCT_NAME)
```

Do not change `st.header("Upload a MARC file")`,
`st.header("Loaded batch")`, the module docstring, imports, or deployment
paths.

- [ ] **Step 5: Route the Diff sidebar through the constant**

In `marcedit_web/views/6_Diff.py`, add:

```python
from marcedit_web.lib.product_identity import PRODUCT_NAME
```

Replace only the sidebar brand call with:

```python
st.header(PRODUCT_NAME)
```

Do not change the page's `st.title("Diff")`.

- [ ] **Step 6: Run focused identity and existing UI tests**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:dev \
  python -m pytest \
    tests/test_product_identity.py \
    tests/test_app_pages.py \
    tests/test_home_page_jobs.py \
    -q
```

Expected: all tests pass with zero skips.

- [ ] **Step 7: Confirm remaining legacy-name strings are technical**

Run:

```bash
rg -n 'marcedit-web|marcedit_web|MARCEDIT_WEB_' \
  marcedit_web/App.py \
  marcedit_web/views/00_Home.py \
  marcedit_web/views/6_Diff.py
```

Expected: remaining matches are module/package names, logger names, technical
docstrings, or other compatibility identifiers—not arguments to the product
brand calls tested above.

- [ ] **Step 8: Commit the UI routing**

```bash
git add \
  marcedit_web/App.py \
  marcedit_web/views/00_Home.py \
  marcedit_web/views/6_Diff.py \
  tests/test_product_identity.py
git commit -m "feat: centralize user-facing product identity"
```

---

### Task 3: Add licensing, dependency notices, and independent-product copy

**Files:**
- Modify: `tests/test_product_identity.py`
- Create: `LICENSE`
- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: the exact interim `PRODUCT_NAME` value from Task 1.
- Produces: repository and Docker-distributed MIT license, verified direct
  dependency notices, neutral README/package descriptions, and explicit
  technical-identifier compatibility assertions.

- [ ] **Step 1: Add failing repository-boundary tests**

Append to `tests/test_product_identity.py`:

```python
def test_repository_has_smith_mit_license():
    license_text = _source("LICENSE")

    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 Smith College" in license_text
    assert "Permission is hereby granted, free of charge" in license_text


def test_direct_runtime_dependency_notices_are_present():
    notices = _source("THIRD_PARTY_NOTICES.md")
    pyproject = _source("pyproject.toml")
    expected = {
        "Streamlit": "Apache-2.0",
        "pymarc": "BSD-2-Clause",
        "streamlit-ace": "MIT",
        "Authlib": "BSD-3-Clause",
    }

    for project, license_id in expected.items():
        assert project in notices
        assert license_id in notices

    match = re.search(
        r"(?ms)^dependencies\s*=\s*\[(.*?)^\]",
        pyproject,
    )
    assert match is not None
    declared = set(
        re.findall(r'(?m)^\s*"([A-Za-z0-9_.-]+)', match.group(1))
    )
    assert {name.lower() for name in declared} == {
        name.lower() for name in expected
    }


def test_readme_and_package_description_are_independent_and_neutral():
    readme = _source("README.md")
    pyproject = _source("pyproject.toml")

    assert readme.startswith(f"# {PRODUCT_NAME}\n")
    assert "Recreates MarcEdit" not in readme
    assert "not affiliated with or endorsed by MarcEdit or its author" in readme
    assert "recreating MarcEdit" not in pyproject
    assert 'description = "Independent web application for MARC21 metadata workflows."' in pyproject


def test_existing_technical_identifiers_remain_compatible():
    readme = _source("README.md")
    pyproject = _source("pyproject.toml")

    assert 'name = "marcedit-web"' in pyproject
    assert "https://libtools2.smith.edu/marcedit-web/" in readme
    assert "streamlit run marcedit_web/App.py" in readme


def test_docker_image_includes_project_license_and_notices():
    dockerfile = _source("Dockerfile")

    assert "COPY LICENSE THIRD_PARTY_NOTICES.md ./" in dockerfile
```

- [ ] **Step 2: Run the repository-boundary tests and verify they fail**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:dev \
  python -m pytest tests/test_product_identity.py -q
```

Expected: the Task 1 and Task 2 tests pass; the five new tests fail because
the license/notices do not exist and the old descriptions remain.

- [ ] **Step 3: Add the MIT license**

Create `LICENSE` with:

```text
MIT License

Copyright (c) 2026 Smith College

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: Add direct runtime dependency notices**

Create `THIRD_PARTY_NOTICES.md` with:

```markdown
# Third-party notices

The application distribution includes these direct runtime dependencies.
Their license texts and notices are available from the linked upstream
projects. Installed distributions retain the license metadata supplied by
upstream.

| Project | License | Upstream source |
| --- | --- | --- |
| [Streamlit](https://github.com/streamlit/streamlit) | Apache-2.0 | https://github.com/streamlit/streamlit |
| [pymarc](https://github.com/pymarc/pymarc) | BSD-2-Clause | https://github.com/pymarc/pymarc |
| [streamlit-ace](https://github.com/okld/streamlit-ace) | MIT | https://github.com/okld/streamlit-ace |
| [Authlib](https://github.com/authlib/authlib) | BSD-3-Clause | https://github.com/authlib/authlib |

These notices cover direct dependencies declared in `pyproject.toml`.
Transitive dependencies retain the license metadata supplied in their
installed distributions.
```

The license identifiers are verified against the existing
`marcedit-web:dev` image: Streamlit 1.50.0 reports Apache License 2.0, pymarc
5.3.1 carries the two-clause BSD text, streamlit-ace 0.1.1 reports MIT, and
Authlib 1.3.2 reports BSD-3-Clause.

- [ ] **Step 5: Replace README identity and add the disclaimer**

Replace the README heading and opening paragraph with:

```markdown
# Smith College Libraries MARC21 workflow application

An independently developed web application for viewing, validating, editing,
and comparing MARC21 metadata. It is deployed at
https://libtools2.smith.edu/marcedit-web/ behind Apache + mod_shib on
RHEL 8.10.

MarcEdit is referenced only to identify the external task-file format accepted
by the optional migration tools. This project is not affiliated with or
endorsed by MarcEdit or its author.
```

Keep all existing local-development commands, `marcedit_web/` layout names,
deployment URL, and deployment-document links unchanged.

- [ ] **Step 6: Replace only the package description**

In `pyproject.toml`, replace:

```toml
description = "Web-based MARC21 editor recreating MarcEdit's core features."
```

with:

```toml
description = "Independent web application for MARC21 metadata workflows."
```

Keep:

```toml
name = "marcedit-web"
```

- [ ] **Step 7: Include the license and notices in the image**

In `Dockerfile`, immediately after `COPY requirements.txt ./`, add:

```dockerfile
COPY LICENSE THIRD_PARTY_NOTICES.md ./
```

Do not change the base image, runtime user, command, healthcheck, exposed port,
or any application path.

- [ ] **Step 8: Run focused tests**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:dev \
  python -m pytest tests/test_product_identity.py -q
```

Expected: all tests pass with zero skips.

- [ ] **Step 9: Commit the licensing baseline**

```bash
git add \
  Dockerfile \
  LICENSE \
  README.md \
  THIRD_PARTY_NOTICES.md \
  pyproject.toml \
  tests/test_product_identity.py
git commit -m "docs: establish independent licensing baseline"
```

---

### Task 4: Verify Docker packaging, browser identity, and complete regression

**Files:**
- Modify: `.tickets/TASK-176-neutral-product-identity-licensing.md`
- Modify: `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`

**Interfaces:**
- Consumes: the product constant, UI routing, legal copy, and Docker packaging
  from Tasks 1–3.
- Produces: recorded supported-runtime, image-content, browser, full-suite, and
  review evidence for the Phase 1 gate.

- [ ] **Step 1: Run the focused host suite**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:dev \
  python -m pytest \
    tests/test_product_identity.py \
    tests/test_app_pages.py \
    tests/test_home_page_jobs.py \
    -q
```

Expected: all tests pass with zero skips.

- [ ] **Step 2: Build the Phase 1 image**

Run:

```bash
docker build -t marcedit-web:task-176 .
```

Expected: build exits 0. Because `requirements.txt` is unchanged, the existing
dependency-install layer is reusable and no dependency update is authorized.

- [ ] **Step 3: Verify the image contains licensing artifacts**

Run:

```bash
docker run --rm --network none marcedit-web:task-176 \
  sh -c 'test -f /app/LICENSE && test -f /app/THIRD_PARTY_NOTICES.md'
```

Expected: exit 0 with no output.

- [ ] **Step 4: Run the complete suite in the supported Docker runtime**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:task-176 \
  python -m pytest -q
```

Expected: all tests pass. Report the exact pass and skip counts; do not hide
the four Compose-rendering skips if the image still lacks the Docker CLI.

- [ ] **Step 5: Start a disposable browser-test container without Compose**

Run:

```bash
docker run --rm -d \
  --name marcedit-web-task176-browser \
  -p 127.0.0.1:18501:8501 \
  -e MARCEDIT_WEB_MODE=public \
  marcedit-web:task-176
```

Expected: the command prints one container ID. This uses Docker's existing
default bridge and does not allocate a new Compose network.

- [ ] **Step 6: Verify Streamlit health before opening the browser**

Run:

```bash
curl --retry 20 --retry-delay 1 --retry-connrefused -fsS \
  http://127.0.0.1:18501/_stcore/health
```

Expected: `ok`.

- [ ] **Step 7: Perform the browser identity check**

Open `http://127.0.0.1:18501/` and verify:

1. the browser tab title is
   `Smith College Libraries MARC21 workflow application`;
2. the Home page H1 uses that exact value;
3. the sidebar uses that exact value;
4. Home upload controls still render; and
5. no user-facing `marcedit-web` brand appears.

Capture a screenshot in the execution evidence. This is a visual acceptance
check, not a replacement for the automated source-routing tests.

- [ ] **Step 8: Stop the disposable container**

Run:

```bash
docker stop marcedit-web-task176-browser
```

Expected: `marcedit-web-task176-browser`.

- [ ] **Step 9: Verify technical entry points were not changed**

Run:

```bash
git diff --name-only b1234eb..HEAD
```

Expected: no files under `deploy/`, `scripts/`, `.streamlit/`, or
`docker-compose*.yml`.

Run:

```bash
git diff b1234eb..HEAD -- \
  pyproject.toml README.md Dockerfile
```

Expected: the `marcedit-web` distribution name, `/marcedit-web/` production
URL, `marcedit_web/App.py` command, and `/app` image paths remain present.

- [ ] **Step 10: Review the complete Phase 1 diff**

Run:

```bash
git diff --check b1234eb..HEAD
git diff --stat b1234eb..HEAD
git diff b1234eb..HEAD
```

Review every changed line against TASK-176. Record all Critical, Important,
and Minor findings. Correct findings through a new red/green test cycle and a
separate fix commit. Do not mark the ticket Completed while a Critical or
Important finding remains.

- [ ] **Step 11: Record evidence and complete only the child ticket**

Append an `Evidence` section to
`.tickets/TASK-176-neutral-product-identity-licensing.md` containing:

- focused host-suite count and skip count;
- full Docker-suite count and every skip reason;
- image build tag and licensing-artifact check;
- browser URL, five visual assertions, and screenshot path;
- unchanged technical-entry-point result;
- reviewed commit range; and
- final review findings by severity.

Change TASK-176 to `Status: Completed` only when every success criterion is
satisfied. Add a Phase 1 checkpoint to TASK-174 linking TASK-176, its commit
range, and its evidence, but leave TASK-174 `Status: In-Progress`.

- [ ] **Step 12: Commit Phase 1 evidence**

```bash
git add \
  .tickets/TASK-174-smith-metadata-studio-open-task-migration.md \
  .tickets/TASK-176-neutral-product-identity-licensing.md
git commit -m "docs: complete TASK-176 identity phase"
```

- [ ] **Step 13: Run the final clean-tree gate**

Run:

```bash
git status --short
git log --oneline b1234eb..HEAD
```

Expected: `git status --short` emits no output. The log contains the Task 1,
Task 2, Task 3, any review-fix commits, and the final evidence commit.

Do not begin the native task schema/storage child until this Phase 1 evidence
commit is reviewed.
