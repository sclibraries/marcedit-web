Title: Establish a neutral product identity and licensing baseline

Parent: TASK-174

Scope:
- Add one application constant for every user-facing product-name string, with
  the interim value `Smith College Libraries MARC21 workflow application`.
- Route the browser page title, Home title/sidebar, and Diff sidebar through
  that constant.
- Add the repository's MIT license and direct-dependency notices.
- Replace README and package-description language that says the application
  recreates MarcEdit.
- Add a name-neutral independence disclaimer that uses MarcEdit only as a
  referential identifier for supported external MarcEdit task and mnemonic
  text formats, never as the application's product identity.
- Include the license and notices in the Docker image.
- Preserve the `marcedit-web` package name, `marcedit_web` Python package,
  `/marcedit-web/` URL, environment variables, Docker service names, filesystem
  paths, and systemd entry points.

Success Criteria:
- All current user-facing product-name sites consume the single constant.
- The interim UI name and README heading are
  `Smith College Libraries MARC21 workflow application`.
- `README.md` and `pyproject.toml` contain no claim that the application
  recreates MarcEdit.
- `LICENSE` contains the MIT license for Smith College.
- `THIRD_PARTY_NOTICES.md` identifies Streamlit, pymarc, streamlit-ace, and
  Authlib with their verified licenses and upstream sources.
- The Docker image contains `/app/LICENSE` and
  `/app/THIRD_PARTY_NOTICES.md`.
- Focused tests, the complete supported Docker test suite, and a Docker browser
  smoke test pass with every skip reported.
- Code review has no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-29-smith-metadata-studio-open-task-migration-design.md`

Plan:
- `docs/superpowers/plans/2026-07-29-task-174-phase-1-product-identity-licensing.md`

Evidence:
- Focused supported-runtime suite:
  `tests/test_product_identity.py`, `tests/test_app_pages.py`,
  `tests/test_home_page_jobs.py`, `tests/test_gemini_task_draft.py`, and
  `tests/test_marceditor_mode.py` completed with 57 passed and 0 skipped.
- Image `marcedit-web:task-176` built successfully at review-fix commit
  `29a4b71`; the build showed `RUN pip install -r requirements.txt` as
  `CACHED`, and `/app/LICENSE` and `/app/THIRD_PARTY_NOTICES.md` both passed
  the network-free image-content check. The packaged notices also contained
  the pytest source entry.
- Complete supported-runtime Docker suite completed with 1,585 passed and 4
  skipped. Two skips at `tests/test_docker_compose_config.py:88` and two at
  `tests/test_docker_compose_config.py:130` each reported:
  `docker CLI is required to render Compose configuration`.
- Browser acceptance opened `http://127.0.0.1:18501/` and settled at
  `http://127.0.0.1:18501/?start=quick`. The page title, Home level-1 heading,
  and sidebar level-2 heading exactly matched
  `Smith College Libraries MARC21 workflow application`; the Home upload
  heading and Quick Load/file chooser controls rendered; and no user-facing
  `marcedit-web`, `MarcEdit Web`, or `MarcEditor` product string appeared.
  Durable accessibility snapshot:
  `docs/superpowers/evidence/task-176-record-editor-browser-smoke.md`.
  Full-page, viewport, and element screenshot attempts each timed out at the
  connector's fixed five-second limit, so no screenshot exists; this remains
  an explicit Minor plan deviation.
- Browser execution used controller-provided trusted Playwright evidence after
  the requested browser-use CLI was absent and the approved in-app Browser
  fallback did not expose its required control tool. The disposable
  `marcedit-web-task176-browser` container returned health `ok` and stopped
  successfully.
- Technical entry points are unchanged: no `deploy/`, `scripts/`,
  `.streamlit/`, or `docker-compose*.yml` file changed; the `marcedit-web`
  distribution name, `/marcedit-web/` production URL,
  `marcedit_web/App.py` commands, and `/app` image paths remain present.
- Reviewed range: `b1234eb..29a4b71`; `git diff --check` passed and every
  changed line was reviewed against TASK-176.
- Review findings: Critical: none. Important: one shared-sidebar literal was
  found, reproduced with two failing regression assertions, fixed in
  `8c425b1`, and verified with two passing targeted tests plus the focused and
  complete suites. A second Important finding showed the changeable licensing
  copy invalidated dependency installation and could re-resolve ranged
  requirements; its ordering regression failed first, then passed after
  `0610315` moved the copy after dependency installation. Minor: the original
  screenshot reference implied a local file that did not exist; it now
  accurately identifies durable accessibility evidence and an unavailable
  screenshot. Final whole-branch review then found two Important findings:
  inconsistent independent-identity boundaries and incomplete Docker direct
  dependency notices. Commit `29a4b71` broadened referential-format policy,
  neutralized user-facing Record Editor and model-prompt identity, added the
  verified pytest MIT/source notice, and reconciled notices against direct
  non-comment `requirements.txt` entries. Both Important findings are
  resolved. The unavailable screenshot remains the only unresolved Minor/plan
  deviation; no Critical or Important finding remains.
- Execution report is local-only, ignored by Git, and absent from clean checkouts:
  `.superpowers/sdd/task-176-task-4-report.md`. Essential evidence remains in
  this tracked ticket and
  `docs/superpowers/evidence/task-176-record-editor-browser-smoke.md`.
