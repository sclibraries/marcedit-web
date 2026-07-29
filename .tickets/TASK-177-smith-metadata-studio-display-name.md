Title: Finalize the Smith Metadata Studio display name

Parent: TASK-174

Scope:
- Set the centralized public product name to `Smith Metadata Studio`.
- Update user-facing documentation and identity tests to the approved name.
- Preserve the `marcedit-web` production folder, URL, distribution name,
  Python package, environment variables, Docker/service names, systemd entry
  points, startup commands, and technical routes.
- Rebuild and test the exact display-only rename in Docker before merge.

Success Criteria:
- Browser title, application heading/sidebar, and model-facing product identity
  use `Smith Metadata Studio`.
- `Record Editor` remains the user-facing editor name.
- No production/deployment identifier changes.
- Focused tests, the complete supported Docker suite, and Docker browser
  acceptance pass with every skip or evidence deviation reported.
- Code review has no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-29-smith-metadata-studio-display-name-design.md`

Implementation Evidence:
- TDD RED in `marcedit-web:task-176` produced the intended two failures:
  the centralized constant and README still used the superseded
  `Smith College Libraries MARC21 workflow application` placeholder.
- TDD GREEN in `marcedit-web:task-176` produced 2 narrow passes and 58
  focused passes with zero skips. The focused navigation contract retained
  title `Record Editor`, URL path `MarcEditor`, and script
  `views/5_MarcEditor.py`.
- Implementation commit: `2481c39` (`feat: finalize Smith Metadata Studio
  display name`).
- `docker build -t marcedit-web:task-177 .` exited 0. The unchanged
  `RUN pip install -r requirements.txt` layer was cached.
- The network-isolated packaged-artifact check found `/app/LICENSE`,
  `/app/THIRD_PARTY_NOTICES.md`, and the `pytest-dev/pytest` notice; it exited
  0 with no output.
- The complete supported suite in the rebuilt image produced 1,586 passes and
  four disclosed skips. `tests/test_docker_compose_config.py:88` skipped two
  parameterizations and `tests/test_docker_compose_config.py:130` skipped two
  parameterizations because the Docker CLI is required to render Compose
  configuration and is unavailable inside the test container.
- Browser acceptance used `http://127.0.0.1:18501/` and the exact rebuilt
  `marcedit-web:task-177` image. The initial default-mode disposable container
  reached the private `Sign-in required` gate, so it was replaced with the
  same image, name, and port plus test-only `MARCEDIT_WEB_MODE=public`; no
  source or production default changed. Both health checks returned exact
  output `ok`.
- The settled browser URL was
  `http://127.0.0.1:18501/?start=quick`. The page title was exactly
  `Smith Metadata Studio`; the sidebar level-two and main level-one headings
  were exactly `Smith Metadata Studio`; `Upload a MARC file`, `Quick Load`,
  `Choose File`, and `Browse files` were visible; and
  `Smith College Libraries MARC21 workflow application`, `MarcEdit Web`, and
  the user-facing label `MarcEditor` were absent.
- Durable accessibility evidence:
  `docs/superpowers/evidence/task-177-smith-metadata-studio-browser-smoke.md`.
  The single trusted-connector screenshot attempt succeeded and is retained at
  `docs/superpowers/evidence/task-177-smith-metadata-studio-browser-smoke.png`.
- The `5b7824e..HEAD` name-only audit contains no `deploy/`, `scripts/`,
  `.streamlit/`, Compose, systemd, or environment configuration file.
  `pyproject.toml` still declares `marcedit-web`; README and deployment sources
  retain `/marcedit-web/`; `MARCEDIT_WEB_*` settings remain present; and
  `marcedit_web/App.py` retains `url_path="MarcEditor"` and
  `views/5_MarcEditor.py`. Remaining MarcEdit references are technical route
  identifiers, compatibility assertions, implementation-plan constraints, or
  referential descriptions of supported external formats.
- Review range awaiting independent review: `5b7824e..HEAD`.
