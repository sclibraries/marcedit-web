# TASK-186 Compact Modal Task Authoring Browser Smoke Evidence

## Candidate and safety boundary

- Initial candidate implementation commit: `d0c5a8e`; current reviewed code
  candidate after the split-Workspace amendment and corrective review:
  `4703736`.
- Initial rebuilt image: `marcedit-web:dev`,
  `sha256:87bae70bb6349dd033cde397ac88bba32de0483d5b3bb73349f23599047a97ec`.
- Browser target: the repository's loopback-only local service at
  `http://127.0.0.1:8501`, using the documented local private-unit development
  configuration without production authentication.
- Intended identities: disposable synthetic admin and cataloger identities in
  an isolated local database only. No production authentication, real identity,
  institutional database, vendor record, or institutional task corpus was
  accessed.
- Intended MARC fixture: a synthetic record containing control fields 001 and
  003 and `035 $aTFeba9780020306634`.
- Screenshot: not captured. No browser session reached synthetic application
  state, so there was no useful private-safe UI evidence to preserve.

## Browser-runtime disposition

Browser acceptance could not begin. The required `browser-use` executable was
not installed (`browser-use doctor`, `browser-use --help`, and
`browser-use python --help` each returned `command not found`). The separately
approved in-app browser workflow was also unavailable because its required
browser-control execution tool was not exposed in this session.

The Docker health endpoint and automated Streamlit render tests are not
substitutes for browser acceptance. No checklist item below is promoted to a
pass based on non-browser evidence.

## Fourteen-step acceptance matrix

| Step | Result | Observation or skip reason |
| --- | --- | --- |
| 1. Open Tasks, Build & import, and New task in form mode | **SKIP** | No supported browser controller was available, so the private UI could not be navigated. |
| 2. Main editor omits selector and expanded operation controls | **SKIP** | Requires visible browser state after step 1. |
| 3. Add six named operations plus an incomplete operation | **SKIP** | Requires interactive browser controls. No synthetic task was persisted. |
| 4. Alphabetical selector and compact ordered cards | **SKIP** | Requires rendered selector/card inspection. |
| 5. Split Workspace keeps setup beside preview; secondary tabs remain contextual | **SKIP** | Requires dialog interaction and visible split-layout inspection. |
| 6. Preview synthetic 035 replacement and observe Current without full MARC | **SKIP** | Requires interactive upload/preview state. No MARC data was loaded. |
| 7. Reorder Guided card and retain Current | **SKIP** | Requires the preview state from step 6. |
| 8. Edit, preview draft, cancel/discard, and restore original Current | **SKIP** | Requires a live dialog and preview cache interaction. |
| 9. Dirty/clean Cancel and confirmed Remove behavior | **SKIP** | Requires interactive confirmation dialogs. |
| 10. Keep incomplete operation; ordinal Needs attention blocks save | **SKIP** | Requires authoring and save interaction. |
| 11. Correct, save, reopen, and preserve order/meaning | **SKIP** | Requires persistent browser session state. |
| 12. Standalone reference searches label and summary alphabetically | **SKIP** | Requires reference-dialog interaction. |
| 13. In-operation Reference tab does not nest a dialog | **SKIP** | Requires open-dialog inspection. |
| 14. Cataloger custom-code restrictions and unchanged admin code mode | **SKIP** | Requires two synthetic role-specific browser sessions. |

Browser total: **0 PASS, 0 FAIL, 14 SKIP**. The release browser gate is
incomplete, so this evidence supports `DONE_WITH_CONCERNS`, not ticket
completion.

## Rebuilt dependency preflight

`docker compose build marcedit-web` completed successfully. A fresh container
reported Streamlit `1.50.0`; `inspect.signature(st.dialog)` contained the
required `dismissible` parameter and returned:

```text
(title: 'F | str', *, width: 'DialogWidth' = 'small', dismissible: 'bool' = True,
 on_dismiss: "Literal['ignore', 'rerun'] | WidgetCallback" = 'ignore')
 -> 'F | Callable[[F], F]'
```

## Automated verification

### Rebuilt image-only baseline

`docker compose run --rm marcedit-web pytest -ra` collected 1,978 tests and
finished in 86.89 seconds with **1,931 passed, 8 failed, 39 skipped**.

All eight failures were repository-file availability checks in
`tests/test_product_identity.py`; the implementation assertions did not fail.
The image intentionally omits `README.md`, `Dockerfile`,
`.tickets/TASK-176-neutral-product-identity-licensing.md`, and
`docs/superpowers/plans/2026-07-29-task-174-phase-1-product-identity-licensing.md`
from `/app`. The failing tests were:

1. `test_readme_and_package_description_are_independent_and_neutral`
2. `test_ticket_marks_ignored_execution_report_as_local_only`
3. `test_user_facing_editor_copy_uses_neutral_record_editor_label`
4. `test_existing_technical_identifiers_remain_compatible`
5. `test_docker_image_includes_project_license_and_notices`
6. `test_docker_dependency_install_precedes_changeable_license_copy`
7. `test_phase_one_plan_derives_notices_from_direct_requirements_entries`
8. `test_phase_one_plan_installs_dependencies_before_license_copy`

The 39 image-only skips were reported as follows:

- 24 deployment-unit checks: 2 missing private-service file checks, 4 missing
  deployment-document checks, 1 missing public-service check, 1 missing worker
  service check, 1 missing deploy script check, 1 missing install script check,
  10 missing preflight script checks, 1 missing `.env.example` check, 1 missing
  ITS setup document check, and 2 missing watchdog unit/timer checks.
- 13 Compose checks: 3 missing pull-file checks, 4 Docker-CLI-required render
  checks, 3 missing `.dockerignore` checks, and 3 missing Dockerfile checks.
- 1 task-authoring reference check because the syntax document is unavailable
  in the image build context.
- 1 institutional MarcEdit Tasks corpus check because that corpus is
  unavailable; synthetic fixtures remain authoritative.

### Read-only mounted-source baseline

The authoritative repository-aware command was:

```text
docker run --rm --network none \
  -v <TASK-186-worktree>:/workspace:ro -w /workspace \
  -e PYTHONPATH=/workspace marcedit-web:dev python -m pytest -ra
```

It collected 1,978 tests and finished in 81.47 seconds with **1,973 passed,
0 failed, 5 skipped**. The five skips were:

- 2 at `tests/test_docker_compose_config.py:88`: Docker CLI is required to
  render Compose configuration.
- 2 at `tests/test_docker_compose_config.py:130`: Docker CLI is required to
  render Compose configuration.
- 1 at `tests/test_task_authoring_corpus.py:105`: the institutional MarcEdit
  Tasks corpus is unavailable; synthetic fixtures remain authoritative.

The native compiler freshness guard passed **1 test** in 0.09 seconds, and
`git diff --exit-code main --
marcedit_web/schemas/native-task-compiler-contract-v1.json` was empty.
`git diff --check main...` also reported no whitespace errors.

### Post-review corrective verification

Whole-branch review found three Important issues in editor lifecycle,
malformed-parameter validation, and failed-preview staleness. Commit
`f842453` corrected those issues and added nested deep-copy coverage. Re-review
then found that the no-loaded-file failure context was being labeled Stale;
commit `dd9f364` restored Failed for that current `None`/`None`/`None` context
while preserving Stale after store identity or revision changes.

After `dd9f364`, the focused Docker suite passed **121 tests with no skips**.
The complete read-only mounted-source Docker suite passed **1,979 tests with
zero failures and 5 reported skips**: four Docker-CLI checks unavailable
inside the container and the unavailable institutional corpus check.
Independent re-review reported no remaining Critical or Important findings
and assessed the code as ready for real browser acceptance.

### Split-Workspace amendment verification

Commit `c75118d` combined setup and preview in one Workspace. Whole-branch
review then found two Important correctness issues in unsupported select-value
preservation and stale failed-preview evidence. Commit `4703736` corrected
both with RED-first tests. Scoped re-review reported no remaining Critical or
Important findings.

Final root-controlled verification after `4703736` produced:

- focused Docker suite: **214 passed, zero skipped**;
- complete read-only mounted-source Docker suite: **1,987 passed, zero
  failed, 5 reported skips**;
- native compiler freshness guard: **1 passed**; and
- compiler-manifest, whitespace, and worktree checks: clean.

The five complete-suite skips remain four Docker-CLI checks unavailable inside
the container and one unavailable institutional corpus check. None is treated
as a pass. Browser acceptance remains 0 PASS, 0 FAIL, 14 SKIP.

## Independent review

The read-only review covered the TASK-186 implementation range
`0ac6ff5..235f4ca` and then the focused correction committed as `d0c5a8e`.
It verified the single-dialog branch, runtime dynamic non-dismissible wrapper,
all eight injected renderer reruns, fragment-to-app fallback, transactional
draft and preview isolation, role-filtered palette coverage, invalid-operation
save/submission gates, and unchanged compiler, AI, import, sharing, and worker
behavior.

The reviewer found one Important title issue: selecting an Add operation used
a fragment rerun, which could retain the wrapper's initial `Add operation`
title. A focused regression test failed before the fix; `d0c5a8e` now requests
a full-app rerun and verifies the next wrapper title is
`Add — Delete tag`. The focused modal integration suite passed **106 tests**.
That checkpoint re-review reported **zero Critical, zero Important, and zero
Minor findings**. The later whole-branch review and corrections are recorded
in the post-review verification section above. Browser acceptance remains a
separate incomplete release gate.

## Release disposition

The rebuilt dependency contract, repository-aware automated suite, compiler
freshness guard, and whitespace gate pass. The image-only repository-file
failures and all skip reasons remain disclosed. Browser acceptance remains
unperformed because neither approved browser controller was available at that
checkpoint; the TASK-186 ticket remained `In-Progress` pending later manual
confirmation.

## Cataloger local-Docker confirmation (2026-08-01)

The cataloger subsequently tested the compact modal authoring workflow in the
local Docker deployment and confirmed that it worked as expected, including
the combined setup/preview Workspace. This is the approved manual-browser
disposition for the unavailable controller; no production service, database,
vendor record, or institutional corpus was used.

The repository-mounted Docker suite was rerun on the current worktree and
passed 1,988 tests with five disclosed skips (four Docker-CLI-dependent
Compose checks and the unavailable institutional corpus). The native contract
freshness test passed and the compiler manifest remained unchanged. The
image-only repository-file failures remain documented as a build-context
limitation and are not counted as application passes.
