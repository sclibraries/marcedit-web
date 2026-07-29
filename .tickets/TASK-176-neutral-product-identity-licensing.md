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
- Add a name-neutral independence disclaimer that uses MarcEdit only to
  identify the optional external task format.
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

Status: Completed

Design:
- `docs/superpowers/specs/2026-07-29-smith-metadata-studio-open-task-migration-design.md`

Plan:
- `docs/superpowers/plans/2026-07-29-task-174-phase-1-product-identity-licensing.md`

Evidence:
- Focused supported-runtime suite:
  `tests/test_product_identity.py`, `tests/test_app_pages.py`, and
  `tests/test_home_page_jobs.py` completed with 40 passed and 0 skipped.
- Image `marcedit-web:task-176` built successfully at review-fix commit
  `8c425b1`; `/app/LICENSE` and `/app/THIRD_PARTY_NOTICES.md` both passed the
  network-free image-content check.
- Complete supported-runtime Docker suite completed with 1,581 passed and 4
  skipped. Two skips at `tests/test_docker_compose_config.py:88` and two at
  `tests/test_docker_compose_config.py:130` each reported:
  `docker CLI is required to render Compose configuration`.
- Browser acceptance opened `http://127.0.0.1:18501/` and settled at
  `http://127.0.0.1:18501/?start=quick`. The page title, Home level-1 heading,
  and sidebar level-2 heading exactly matched
  `Smith College Libraries MARC21 workflow application`; the Home upload
  heading and Quick Load/file chooser controls rendered; and no user-facing
  `marcedit-web` string appeared. Screenshot:
  `./task176-product-identity.png`.
- Browser execution used controller-provided trusted Playwright evidence after
  the requested browser-use CLI was absent and the approved in-app Browser
  fallback did not expose its required control tool. The disposable
  `marcedit-web-task176-browser` container returned health `ok` and stopped
  successfully.
- Technical entry points are unchanged: no `deploy/`, `scripts/`,
  `.streamlit/`, or `docker-compose*.yml` file changed; the `marcedit-web`
  distribution name, `/marcedit-web/` production URL,
  `marcedit_web/App.py` commands, and `/app` image paths remain present.
- Reviewed range: `b1234eb..8c425b1`; `git diff --check` passed and every
  changed line was reviewed against TASK-176.
- Review findings: Critical: none. Important: one shared-sidebar literal was
  found, reproduced with two failing regression assertions, fixed in
  `8c425b1`, and verified with two passing targeted tests plus the focused and
  complete suites; no Important finding remains. Minor: placing the licensing
  copy layer before dependency installation invalidated the dependency layer
  during the first licensing build, although the unchanged requirements were
  reused on the post-fix rebuild.
- Full execution report:
  `.superpowers/sdd/task-176-task-4-report.md`.
