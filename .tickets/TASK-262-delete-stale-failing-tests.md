Title: Delete the 13 stale failing tests so the suite runs green

Status: Ready
Size: S
Tier: small — deletes tests only; no application behavior changes
Milestone: M3 — Code health
Base: the local `main` commit that adds this ticket
Branch: codex/TASK-262

Why:
- 13 tests fail on main before any change, so a new failure is hard to see.
  None of them guards live cataloger behavior. Owner approved deleting them
  on 2026-11-13 (coordination repo decision 2026-11-13-delete-stale-failing-tests).

Scope:
- Delete these 9 tests from `tests/test_product_identity.py`. They check
  README, Dockerfile, ticket and local-only plan wording (copy text, which
  Rule 14 says not to test) and fail because those files aren't in the
  test container or the repo:
  `test_readme_and_package_description_are_independent_and_neutral`,
  `test_ticket_marks_ignored_execution_report_as_local_only`,
  `test_user_facing_editor_copy_uses_neutral_record_editor_label`,
  `test_existing_technical_identifiers_remain_compatible`,
  `test_private_docker_review_requires_google_authentication`,
  `test_docker_image_includes_project_license_and_notices`,
  `test_docker_dependency_install_precedes_changeable_license_copy`,
  `test_phase_one_plan_derives_notices_from_direct_requirements_entries`,
  `test_phase_one_plan_installs_dependencies_before_license_copy`.
- Delete these 4 tests from `tests/test_operations_render.py`. They cover
  the Streamlit page for the durable operations queue, which is switched
  off (`runmode.DURABLE_OPERATIONS_ENABLED = False`):
  `test_large_result_is_never_materialized_for_streamlit_download`,
  `test_terminal_actions_call_job_and_quick_load_services`,
  `test_action_errors_are_shown_without_mutating_row`,
  `test_job_viewer_can_download_but_never_sees_mutation_controls`.
- Remove only the imports, constants, fixtures or helpers in those two
  files that the deletions leave unused.

Out of scope:
- Any other test, including the passing tests in both files.
- Any application code, docs, Dockerfile or README.
- Fixing the failures instead of deleting them.

Likely files:
- tests/test_product_identity.py
- tests/test_operations_render.py

Acceptance tests:
- The Docker suite reports 0 failed, so a future failure is visible
  immediately.
- Exactly the 13 named tests are gone; every other test in both files still
  exists and passes, so no live coverage is lost.

Verification:
- Docker suite (AGENTS.md "Verification commands").
- `python3 -m pytest tests/test_deploy_units.py tests/test_docker_compose_config.py` on the host.

Plan:
- (S: none)

Handoff:
- (orchestrator fills in after the check)

Review:
- (orchestrator fills in)
