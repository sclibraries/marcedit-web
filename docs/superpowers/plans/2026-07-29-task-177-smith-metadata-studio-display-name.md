# TASK-177 Smith Metadata Studio Display Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finalize `Smith Metadata Studio` as the public display name, verify it in Docker, and preserve every `marcedit-web` deployment identifier.

**Architecture:** The existing dependency-free `PRODUCT_NAME` constant remains the sole application identity source. The implementation changes only its value and exact current-state documentation/tests; all consumers—including browser metadata, headings, sidebars, and Gemini prompts—continue using the same interface.

**Tech Stack:** Python 3.9, Streamlit, pytest, Docker, trusted Playwright browser connector

**Ticket:** [TASK-177](../../../.tickets/TASK-177-smith-metadata-studio-display-name.md)

**Design:** [Smith Metadata Studio Display-Name Design](../specs/2026-07-29-smith-metadata-studio-display-name-design.md)

## Global Constraints

- The exact public product name is `Smith Metadata Studio`.
- The production folder and working directory remain `marcedit-web`.
- The production URL remains `/marcedit-web/`.
- The Python distribution remains `marcedit-web`; the package remains `marcedit_web`.
- `MARCEDIT_WEB_*` environment variables remain unchanged.
- Docker, Compose, service, systemd, startup-command, and deployment-script identifiers remain unchanged.
- The technical `MarcEditor` route and `views/5_MarcEditor.py` filename remain unchanged.
- `Record Editor` remains the user-facing editor label.
- MarcEdit is named only as a referential identifier for supported external task and mnemonic text formats.
- No production deployment or ITS configuration change is authorized.
- Every test skip and browser-evidence deviation is reported explicitly.

## File Structure

- `marcedit_web/lib/product_identity.py`: owns the canonical public product-name constant.
- `README.md`: presents the current public identity while retaining technical deployment instructions.
- `tests/test_product_identity.py`: enforces the exact public name and preserved compatibility boundary.
- `.tickets/TASK-177-smith-metadata-studio-display-name.md`: records state and durable acceptance evidence.
- `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`: records the parent-program checkpoint.
- `docs/superpowers/evidence/task-177-smith-metadata-studio-browser-smoke.md`: stores durable accessibility evidence from the rebuilt image.

---

### Task 1: Finalize and verify the display-only product name

**Files:**
- Modify: `tests/test_product_identity.py`
- Modify: `marcedit_web/lib/product_identity.py`
- Modify: `README.md`
- Modify: `.tickets/TASK-177-smith-metadata-studio-display-name.md`
- Modify: `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`
- Create: `docs/superpowers/evidence/task-177-smith-metadata-studio-browser-smoke.md`

**Interfaces:**
- Consumes: `marcedit_web.lib.product_identity.PRODUCT_NAME: str`.
- Produces: the same interface with exact value `Smith Metadata Studio`.
- Preserves: `PageSpec.url_path == "MarcEditor"` and `PageSpec.script == "views/5_MarcEditor.py"`.

- [ ] **Step 1: Change the identity contract test first**

In `tests/test_product_identity.py`, change the test-local expected value and
rename the exact-value test:

```python
PRODUCT_NAME = "Smith Metadata Studio"


def test_approved_product_name_is_centralized():
    from marcedit_web.lib import product_identity

    assert product_identity.PRODUCT_NAME == PRODUCT_NAME
    assert "MarcEdit" not in product_identity.PRODUCT_NAME
```

Extend the current-state documentation assertion so the superseded public
placeholder cannot remain in the README:

```python
assert readme.startswith(f"# {PRODUCT_NAME}\n")
assert "Smith College Libraries MARC21 workflow application" not in readme
```

Do not prohibit the historical placeholder in TASK-176 evidence or the
approved design history; those records document why it existed.

- [ ] **Step 2: Run the narrow test to verify RED**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:task-176 \
  python -m pytest \
    tests/test_product_identity.py::test_approved_product_name_is_centralized \
    tests/test_product_identity.py::test_readme_and_package_description_are_independent_and_neutral \
    -q
```

Expected: both tests fail because the constant and README still contain
`Smith College Libraries MARC21 workflow application`.

- [ ] **Step 3: Make the minimum display-only implementation**

In `marcedit_web/lib/product_identity.py`, change only the value:

```python
PRODUCT_NAME = "Smith Metadata Studio"
```

In `README.md`, change only the level-one heading:

```markdown
# Smith Metadata Studio
```

Do not rename imports, routes, files, URLs, packages, environment variables,
containers, services, deployment paths, or startup commands.

- [ ] **Step 4: Run the narrow and focused suites to verify GREEN**

Run the same narrow command from Step 2.

Expected: `2 passed`, zero skipped.

Then run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:task-176 \
  python -m pytest \
    tests/test_product_identity.py \
    tests/test_app_pages.py \
    tests/test_home_page_jobs.py \
    tests/test_gemini_task_draft.py \
    tests/test_marceditor_mode.py \
    -q
```

Expected: all focused tests pass, zero skipped. The private navigation test
must continue to report title `Record Editor`, URL path `MarcEditor`, and
script `views/5_MarcEditor.py`.

- [ ] **Step 5: Commit the TDD implementation**

Run:

```bash
git add tests/test_product_identity.py \
  marcedit_web/lib/product_identity.py \
  README.md
git commit -m "feat: finalize Smith Metadata Studio display name"
```

- [ ] **Step 6: Build the exact candidate image**

Run:

```bash
docker build -t marcedit-web:task-177 .
```

Expected: exit `0`; the unchanged `RUN pip install -r requirements.txt` layer
is reusable when available.

Verify packaged notices without network access:

```bash
docker run --rm --network none marcedit-web:task-177 \
  sh -c 'test -f /app/LICENSE &&
         test -f /app/THIRD_PARTY_NOTICES.md &&
         grep -Fq "pytest-dev/pytest" /app/THIRD_PARTY_NOTICES.md'
```

Expected: exit `0` with no output.

- [ ] **Step 7: Run the complete supported suite in the rebuilt image**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest -q
```

Expected: every test passes except environment-dependent Compose-rendering
tests that explicitly skip when the Docker CLI is unavailable inside the
container. Record the exact pass/skip counts, locations, and reasons.

- [ ] **Step 8: Run browser acceptance against the rebuilt image**

Start a disposable container:

```bash
docker run --rm -d \
  --name marcedit-web-task177-browser \
  -p 127.0.0.1:18501:8501 \
  marcedit-web:task-177
```

Wait for:

```bash
curl --fail --silent http://127.0.0.1:18501/_stcore/health
```

Expected: exact output `ok`.

Using the trusted Playwright browser connector, open
`http://127.0.0.1:18501/` and wait for the settled Home page. Verify:

- page title is exactly `Smith Metadata Studio`;
- main level-one and sidebar level-two headings are exactly
  `Smith Metadata Studio`;
- `Upload a MARC file`, `Quick Load`, `Choose File`, and `Browse files` are
  visible;
- neither `Smith College Libraries MARC21 workflow application` nor
  `MarcEdit Web` nor the user-facing label `MarcEditor` is visible.

Save the accessibility snapshot to:

```text
docs/superpowers/evidence/task-177-smith-metadata-studio-browser-smoke.md
```

Attempt one screenshot through the trusted connector. If it fails, report the
exact error and retain the accessibility snapshot; do not fabricate evidence.

Stop the exact container:

```bash
docker stop marcedit-web-task177-browser
```

- [ ] **Step 9: Audit preserved technical identifiers**

Run:

```bash
git diff --name-only 5b7824e..HEAD
```

Expected: no `deploy/`, `scripts/`, `.streamlit/`, Compose, systemd, or
environment configuration file.

Run:

```bash
rg -n \
  'name = "marcedit-web"|/marcedit-web/|url_path="MarcEditor"|views/5_MarcEditor.py|MARCEDIT_WEB_' \
  pyproject.toml README.md marcedit_web deploy scripts
```

Expected: the technical identifiers remain present and unchanged. Review the
exact diff to distinguish referential MarcEdit format text from prohibited
application branding.

- [ ] **Step 10: Record durable evidence and complete the ticket**

Update `.tickets/TASK-177-smith-metadata-studio-display-name.md` with:

- focused and complete-suite pass/skip counts;
- Docker build and artifact-check results;
- browser URL and exact identity assertions;
- accessibility snapshot path and screenshot result;
- preserved technical-identifier audit;
- implementation commit range awaiting independent review.

Add a TASK-177 checkpoint to
`.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`. Keep TASK-174
`In-Progress`; keep TASK-177 `In-Progress` through the independent review.

- [ ] **Step 11: Run final static verification and commit evidence**

Run:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -w /workspace \
  -e PYTHONPATH=/workspace \
  marcedit-web:task-177 \
  python -m pytest \
    tests/test_product_identity.py \
    tests/test_app_pages.py \
    tests/test_home_page_jobs.py \
    tests/test_gemini_task_draft.py \
    tests/test_marceditor_mode.py \
    -q
git diff --check 5b7824e..HEAD
git status --short
```

Expected: focused tests pass with zero skips; diff check produces no output;
only intentional ticket/evidence changes remain before commit.

Commit:

```bash
git add .tickets/TASK-177-smith-metadata-studio-display-name.md \
  .tickets/TASK-174-smith-metadata-studio-open-task-migration.md \
  docs/superpowers/evidence/task-177-smith-metadata-studio-browser-smoke.md
git commit -m "docs: complete TASK-177 display-name evidence"
```

- [ ] **Step 12: Independent review gate**

Review the exact range `5b7824e..HEAD` against TASK-177 and the approved design.
Approval requires:

- zero unresolved Critical findings;
- zero unresolved Important findings;
- every skip and screenshot deviation disclosed;
- a clean worktree and `git diff --check`;
- no deployment or ITS-owned identifier change.

If review finds an issue, return TASK-177 to `In-Progress`, add a failing
regression where applicable, fix the complete finding set, rerun proportionate
verification, and re-review before merge.

- [ ] **Step 13: Record review approval and complete TASK-177**

After approval, add the exact reviewed range and finding summary to TASK-177
and the parent checkpoint. Set TASK-177 to `Completed`; leave TASK-174
`In-Progress`.

Run:

```bash
git add .tickets/TASK-177-smith-metadata-studio-display-name.md \
  .tickets/TASK-174-smith-metadata-studio-open-task-migration.md
git commit -m "docs: approve TASK-177 display-name release"
git diff --check 5b7824e..HEAD
git status --short
```

Expected: commit succeeds; diff check and status produce no output.
