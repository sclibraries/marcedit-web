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

Status: Todo

Design:
- `docs/superpowers/specs/2026-07-29-smith-metadata-studio-open-task-migration-design.md`

Plan:
- `docs/superpowers/plans/2026-07-29-task-174-phase-1-product-identity-licensing.md`
