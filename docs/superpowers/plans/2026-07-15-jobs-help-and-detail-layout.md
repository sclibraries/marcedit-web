# Jobs Help and Detail Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-152](../../../.tickets/TASK-152-jobs-help-and-detail-layout.md)

**Design:** [Jobs Help and Detail Layout](../specs/2026-07-15-jobs-help-and-detail-layout-design.md)

**Goal:** Add canonical in-application Jobs help and reorganize an opened job into a file-first workspace that substantially reduces routine scrolling without changing workflow or permissions.

**Architecture:** Keep `B_Jobs.py` as the page renderer and reuse every existing jobs/job-files service. Load one canonical Markdown guide from `docs/jobs.md`, show it in a Streamlit dialog, and organize the existing detail controls with `st.columns` and `st.tabs`. The only deployment change is copying that guide into the Docker image.

**Tech Stack:** Python 3.9, Streamlit 1.37–1.x, pytest 8.x, Markdown documentation, Docker.

## Global Constraints

- Preserve all existing permissions, persistence, checkout, version, export, status, review-note, sharing, activity, and archive behavior.
- Do not add workflow states, database changes, notifications, simultaneous editing, or a global Help page.
- Keep the Jobs list substantially unchanged apart from discoverable help.
- Keep Files and Next handoff above Review notes, People, Activity, and Settings.
- Use `docs/jobs.md` as the single canonical full help copy; do not duplicate it in Python.
- Use a generic recurring vendor-load example, not a vendor-specific example.
- Resolve the guide from the source tree, not the process working directory.
- A missing guide must show a visible error without breaking Jobs.
- Complete verification requires zero failures, zero skips, interactive review, and code review.
- Follow TDD: observe each new test fail for the intended reason before implementation.

---

### Task 1: Canonical cataloger guide and deployable loader

**Files:**
- Modify: `tests/test_jobs_page.py`
- Modify: `tests/test_docker_compose_config.py`
- Modify: `marcedit_web/views/B_Jobs.py`
- Modify: `docs/jobs.md`
- Modify: `Dockerfile`

**Interfaces:**
- Produces: `JOBS_HELP_PATH: pathlib.Path`
- Produces: `_read_jobs_help(path: pathlib.Path | None = None) -> str`
- `_read_jobs_help()` returns UTF-8 Markdown and lets `OSError` propagate to the UI boundary added in Task 2.

- [ ] **Step 1: Write failing tests for the canonical guide and Docker packaging**

Add to `tests/test_jobs_page.py`:

```python
def test_jobs_help_explains_one_job_with_independent_vendor_files(monkeypatch):
    """Help must make the recurring two-file workflow understandable."""
    page = _load_jobs_page(monkeypatch)

    guide = page._read_jobs_help()

    assert "# Jobs and Shared Cataloging" in guide
    assert "## Quick start" in guide
    assert "## Recurring vendor load example" in guide
    assert "second file" in guide
    assert "its own checkout" in guide
    assert "retained export" in guide
    assert "Routledge" not in guide


def test_jobs_help_path_does_not_depend_on_working_directory(
    monkeypatch, tmp_path
):
    """The deployed service may start outside the repository root."""
    page = _load_jobs_page(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert "# Jobs and Shared Cataloging" in page._read_jobs_help()
```

Add to `tests/test_docker_compose_config.py`:

```python
def test_docker_image_includes_canonical_jobs_help():
    """Private Docker deployments must have the same guide as source."""
    content = _build_context_file("Dockerfile")

    assert "COPY docs/jobs.md ./docs/jobs.md" in content
```

- [ ] **Step 2: Run the tests and verify the intended failures**

Run:

```bash
docker compose run --rm -v "$PWD:/workspace" -w /workspace marcedit-web \
  pytest tests/test_jobs_page.py::test_jobs_help_explains_one_job_with_independent_vendor_files \
  tests/test_jobs_page.py::test_jobs_help_path_does_not_depend_on_working_directory \
  tests/test_docker_compose_config.py::test_docker_image_includes_canonical_jobs_help -v
```

Expected: the Jobs tests fail with `AttributeError` for `_read_jobs_help`, and the Docker test fails because the COPY line is absent. No test may skip.

- [ ] **Step 3: Add the source-relative loader**

At the top of `marcedit_web/views/B_Jobs.py`, add the import, constant, and pure reader:

```python
from pathlib import Path

JOBS_HELP_PATH = Path(__file__).resolve().parents[2] / "docs" / "jobs.md"


def _read_jobs_help(path: Path | None = None) -> str:
    """Return the canonical cataloger guide from the deployed source tree."""
    return (path or JOBS_HELP_PATH).read_text(encoding="utf-8")
```

- [ ] **Step 4: Replace `docs/jobs.md` with the complete canonical guide**

Use this structure and copy. Preserve these exact headings and key phrases because they are the cataloger contract asserted by tests:

```markdown
# Jobs and Shared Cataloging

Jobs are shared workspaces for MARC files that need handoff, review, or a record
of what happened before loading records into FOLIO, EDS, or another system. A
job can contain multiple related files, and each file is an independent work
item.

## Quick start

1. Create or open a job and attach one or more related `.mrc` files.
2. Check out one file before changing it. Only one cataloger edits that file at
   a time.
3. Run edits or tasks, review the result, and create a retained export for the
   external load.
4. Return the file for review, add notes when needed, and update the job's
   handoff status.

## Job, file, and export

- A **job** is the shared project. It holds the people, overall status, review
  notes, activity, and all related files.
- A **file** is one work item inside the job. Each file has its own checkout,
  current version, history, workflow state, approval context, and exports.
- A **retained export** is a saved copy of one exact file version prepared for
  an external load. Marking it loaded records the destination; it does not
  automatically complete the file or job.

## Quick Load or a shared Job?

Use **Quick Load** for one-off viewing, validation, reporting, editing, or
conversion. Quick Load places the upload in your Personal uploads workspace.

Use a named **Job** when files need to be shared, checked out, reviewed,
processed in stages, or kept together as one recurring project.

## Create or open a job

Use Home's Job Workspace to create a named job, or open an existing job from
Jobs. Give recurring work a stable descriptive name such as `Monthly vendor
load`; dates and stages belong on the individual files and exports.

## Attach related files

Open the job and use **Attach MARC file**. Attaching a later delivery creates a
second file in the same job; it does not replace the earlier file. Owners and
editors can attach files. Viewers can inspect files but cannot attach or change
them.

## Check out, edit, and return a file

Owners and editors check out a file before editing, applying a task, running a
batch operation, restoring a version, or creating an export. Other catalogers
may inspect the file while it is checked out, but only the checkout holder can
change it. When finished, choose **Done** or **Return for review** so another
cataloger can check it out.

Each accepted change creates a new immutable version. History identifies who
made the version and what operation created it. Restoring an older result
creates a new current version; it does not erase later history.

## Create and record exports

Create a retained export from the exact version you intend to load. Give it a
clear purpose such as `Deletion load` or `Replacement load`. Download that
artifact for the external system, then use **Mark loaded** to record its
destination and optional external identifier. The retained artifact remains
with the file for later review.

## Invite catalogers

Open the **People** tab. Owners can grant or revoke access:

- **Owner** manages people, job status, notes, and archive or restore actions,
  and can perform editor work.
- **Editor** can attach, check out, edit, review, and export files and can add
  or resolve review notes.
- **Viewer** can inspect files, notes, people, and activity without making
  changes.

## Review and handoff

Use **Next handoff** for the job's overall advisory status and an optional
handoff note. Each file keeps its own workflow state, so one file may be
complete while another still needs review. Use Review notes for questions that
another cataloger must address, and resolve a note when the concern is handled.

## Recurring vendor load example

Use one long-lived vendor job for the related round trip:

1. Attach the current catalog extract or deletion file as the first file.
2. Check it out, run the deletion edit, review it, and create a labeled retained
   export for the external system. Mark that export loaded after the load.
3. Attach the fresh vendor delivery as a second file in the same job.
4. Check out the fresh file, run the saved vendor task, review the new version,
   and create the replacement export.
5. Return either file for review or complete it independently. The job keeps the
   shared people, notes, and activity together across both stages.

## Complete, archive, or restore

Use **Complete** when the work is finished but should remain visible with active
jobs. Owners may archive a completed or stale job from Settings; archiving is a
soft delete that retains files, history, notes, people, and activity. Owners can
show archived jobs and restore one later. Personal uploads cannot be archived.
```

- [ ] **Step 5: Copy the guide into the Docker image**

In `Dockerfile`, immediately after `COPY data ./data`, add:

```dockerfile
COPY docs/jobs.md ./docs/jobs.md
```

- [ ] **Step 6: Run focused tests and commit**

Run the Step 2 command again.

Expected: 3 passed, zero skipped.

Commit:

```bash
git add marcedit_web/views/B_Jobs.py docs/jobs.md Dockerfile \
  tests/test_jobs_page.py tests/test_docker_compose_config.py
git commit -m "docs: add canonical jobs workflow help"
```

---

### Task 2: Discoverable in-page help dialog

**Files:**
- Modify: `tests/test_jobs_page.py`
- Modify: `marcedit_web/views/B_Jobs.py`

**Interfaces:**
- Consumes: `_read_jobs_help(path: Path | None = None) -> str` from Task 1.
- Produces: `_show_jobs_help() -> None`.
- Produces: `_render_jobs_heading(title: str, caption: str, *, help_key: str) -> None`.

- [ ] **Step 1: Extend the fake column only for controls used by the heading**

Add these methods to `_FakeColumn` in `tests/test_jobs_page.py`:

```python
    def title(self, text: str) -> None:
        self._st.titles.append(text)

    def caption(self, text: str) -> None:
        self._st.captions.append(text)
```

- [ ] **Step 2: Write failing help-dialog tests**

Add:

```python
def test_jobs_list_help_opens_canonical_guide_without_navigation(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit(clicked_keys={"jobs_help_list"})
    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setattr(page, "_read_jobs_help", lambda: "# Canonical jobs guide")
    monkeypatch.setattr(page.jobs, "list_job_summaries", lambda *_args, **_kwargs: [])

    page._render_list("alice@example.edu")

    assert fake_st.dialogs == ["How jobs work"]
    assert "# Canonical jobs guide" in fake_st.writes
    assert "jobs_help_list" in [
        kwargs.get("key") for _label, kwargs in fake_st.button_calls
    ]


def test_jobs_help_failure_is_visible_without_breaking_list(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit(clicked_keys={"jobs_help_list"})
    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setattr(
        page,
        "_read_jobs_help",
        lambda: (_ for _ in ()).throw(OSError("missing")),
    )
    monkeypatch.setattr(page.jobs, "list_job_summaries", lambda *_args, **_kwargs: [])

    page._render_list("alice@example.edu")

    assert fake_st.errors == [
        "Jobs help is unavailable. Ask an administrator to check docs/jobs.md."
    ]
    assert fake_st.infos == ["No jobs found."]


def test_opened_job_has_its_own_help_control(monkeypatch):
    page = _load_jobs_page(monkeypatch)
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(page, "st", fake_st)
    monkeypatch.setattr(page.jobs, "get_access_role", lambda *_args: "viewer")
    monkeypatch.setattr(
        page.jobs,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "name": "Vendor load",
            "status": "active",
            "owner_email": "owner@example.edu",
            "active": 1,
        },
    )
    monkeypatch.setattr(page.work_files, "list_files", lambda *_args: [])
    monkeypatch.setattr(page.jobs, "list_access", lambda *_args: [])
    monkeypatch.setattr(page.jobs, "list_review_notes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(page.jobs, "list_activity", lambda *_args, **_kwargs: [])

    page._render_detail("viewer@example.edu", 17)

    assert "jobs_help_detail_17" in [
        kwargs.get("key") for _label, kwargs in fake_st.button_calls
    ]
```

- [ ] **Step 3: Run tests and confirm the help controls are missing**

Run:

```bash
docker compose run --rm -v "$PWD:/workspace" -w /workspace marcedit-web \
  pytest tests/test_jobs_page.py::test_jobs_list_help_opens_canonical_guide_without_navigation \
  tests/test_jobs_page.py::test_jobs_help_failure_is_visible_without_breaking_list \
  tests/test_jobs_page.py::test_opened_job_has_its_own_help_control -v
```

Expected: all 3 fail because no Jobs help control or dialog is rendered.

- [ ] **Step 4: Implement the dialog and compact reusable heading**

Add to `B_Jobs.py`:

```python
def _show_jobs_help() -> None:
    @st.dialog("How jobs work", width="large")
    def _dialog() -> None:
        try:
            guide = _read_jobs_help()
        except OSError:
            st.error(
                "Jobs help is unavailable. Ask an administrator to check "
                "docs/jobs.md."
            )
            return
        st.markdown(guide)

    _dialog()


def _render_jobs_heading(
    title: str,
    caption: str,
    *,
    help_key: str,
) -> None:
    title_col, help_col = st.columns([5, 1], vertical_alignment="center")
    title_col.title(title)
    if help_col.button(
        "How jobs work",
        key=help_key,
        icon=":material/help:",
    ):
        _show_jobs_help()
    st.caption(caption)
```

Replace the list title/caption with:

```python
    _render_jobs_heading(
        "Jobs",
        "Shared cataloging workspaces for vendor loads, review, and handoff.",
        help_key="jobs_help_list",
    )
```

Replace the detail title/caption with:

```python
    _render_jobs_heading(
        str(job["name"]),
        f"{_status_label(job['status'])} · {role} · owned by {job['owner_email']}",
        help_key=f"jobs_help_detail_{job_id}",
    )
```

- [ ] **Step 5: Run focused and existing Jobs tests**

Run:

```bash
docker compose run --rm -v "$PWD:/workspace" -w /workspace marcedit-web \
  pytest tests/test_jobs_page.py -v
```

Expected: all Jobs-page tests pass with zero skipped. If an existing title or column assertion changes only because the title now uses `_FakeColumn.title`, update that assertion without weakening its behavioral check.

- [ ] **Step 6: Commit**

```bash
git add marcedit_web/views/B_Jobs.py tests/test_jobs_page.py
git commit -m "feat: add in-page jobs help"
```

---

### Task 3: File-first opened-job layout

**Files:**
- Modify: `tests/test_jobs_page.py`
- Modify: `marcedit_web/views/B_Jobs.py`

**Interfaces:**
- Produces these private renderers, each returning `None`: `_render_handoff`, `_render_files`, `_render_people`, `_render_review_notes`, `_render_activity`, and `_render_settings`.
- All renderers consume the same job dictionaries, user strings, role strings, and existing service functions already used by `_render_detail`; none changes a service signature.

- [ ] **Step 1: Extend the Streamlit fake for columns, tabs, and render order**

Add context-manager methods to `_FakeColumn`:

```python
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
```

Add state in `_FakeStreamlit.__init__`:

```python
        self.tab_calls: list[list[str]] = []
        self.render_order: list[tuple[str, Any]] = []
```

Update `_FakeStreamlit.subheader` and add `tabs`:

```python
    def subheader(self, text: str) -> None:
        self.subheaders.append(text)
        self.render_order.append(("subheader", text))

    def tabs(self, labels: list[str]) -> list[_FakeContainer]:
        self.tab_calls.append(list(labels))
        self.render_order.append(("tabs", tuple(labels)))
        return [_FakeContainer(self) for _label in labels]
```

- [ ] **Step 2: Replace the old stacked-page assertion with a failing hierarchy test**

Rename `test_render_detail_loads_sharing_and_review_notes_for_job_members` to
`test_render_detail_is_file_first_and_preserves_owner_controls`, keep its
existing service-call assertions, and replace the final assertions with:

```python
    assert access_calls == [17]
    assert note_calls == [(17, "alice@example.edu", True)]
    assert fake_st.tab_calls == [
        ["Review notes", "People", "Activity", "Settings"]
    ]
    files_position = fake_st.render_order.index(("subheader", "Files"))
    handoff_position = fake_st.render_order.index(("subheader", "Next handoff"))
    tabs_position = fake_st.render_order.index((
        "tabs",
        ("Review notes", "People", "Activity", "Settings"),
    ))
    assert files_position < tabs_position
    assert handoff_position < tabs_position
    assert [label for label, _ in fake_st.button_calls] == [
        "Back to jobs",
        "How jobs work",
        "Update status",
        "Grant access",
        "Add note",
        "Archive job",
    ]
```

Update the Personal uploads archive test to assert only the behavior that
matters after Archive becomes a tab rather than a subheader:

```python
    assert "Archive job" not in [label for label, _ in fake_st.button_calls]
```

- [ ] **Step 3: Run the hierarchy test and verify it fails**

Run:

```bash
docker compose run --rm -v "$PWD:/workspace" -w /workspace marcedit-web \
  pytest tests/test_jobs_page.py::test_render_detail_is_file_first_and_preserves_owner_controls -v
```

Expected: FAIL because `_FakeStreamlit.tabs` is not called and the page still renders the old Status/Sharing/Archive stack.

- [ ] **Step 4: Extract the existing blocks into single-purpose renderers**

In `B_Jobs.py`, move code without changing its service calls or exception
handling:

- Move the current block from `st.subheader("Status")` through its read-only
  `st.write` branch into `_render_handoff(user, job_id, job, role)`. Rename only
  the subheader to `Next handoff`.
- Move the current block from `st.subheader("Files")` through the empty-files
  caption into `_render_files(user, job_id, role)`.
- Move the current Sharing block into `_render_people(user, job_id, role)`;
  remove only `st.subheader("Sharing")` because the tab supplies the label.
- Move the current Review notes block into
  `_render_review_notes(user, job_id, role)`; remove only its subheader.
- Move the current Activity block into `_render_activity(user, job_id)`; remove
  only its subheader.
- Move the current Archive/restore block into
  `_render_settings(user, job_id, job, role)`; remove its Archive subheader.
  When no archive/restore control is allowed, render
  `st.caption("No job settings are available here.")`.

The resulting helpers must be exactly equivalent to these complete bodies:

```python
def _render_handoff(
    user: str,
    job_id: int,
    job: dict[str, object],
    role: str | None,
) -> None:
    st.subheader("Next handoff")
    if _can_edit(role) and job["active"]:
        workflow_statuses = _workflow_statuses()
        current_status = str(job["status"])
        current_index = workflow_statuses.index(current_status)
        selected_status = st.selectbox(
            "Workflow status",
            workflow_statuses,
            index=current_index,
            format_func=_status_label,
            key=f"job_status_{job_id}",
        )
        status_note = st.text_input(
            "Status note",
            key=f"job_status_note_{job_id}",
            placeholder="Optional handoff note",
        )
        if st.button("Update status", key=f"job_status_update_{job_id}"):
            try:
                jobs.set_status(
                    job_id,
                    selected_status,
                    by=user,
                    note=status_note,
                )
            except jobs.JobError as exc:
                st.error(str(exc))
            else:
                st.rerun()
    else:
        st.write(_status_label(str(job["status"])))


def _render_files(user: str, job_id: int, role: str | None) -> None:
    st.subheader("Files")
    job_files.render_attach_file(
        job_id,
        user,
        role,
        key_prefix=f"job_file_attach_{job_id}",
    )
    files = work_files.list_files(job_id, user)
    if files:
        job_files.render_job_files_table(
            files,
            user=user,
            role=role,
            key_prefix="job_upload",
        )
    else:
        st.caption("No files attached to this job yet.")


def _render_people(user: str, job_id: int, role: str | None) -> None:
    access_rows = jobs.list_access(job_id)
    st.dataframe(access_rows, hide_index=True, use_container_width=True)
    if not _can_manage(role):
        return
    share_email = st.text_input(
        "Cataloger email",
        placeholder="name@example.edu",
        key=f"job_share_email_{job_id}",
    )
    share_role = st.selectbox(
        "Role",
        ["editor", "viewer"],
        key=f"job_share_role_{job_id}",
    )
    if st.button("Grant access", key=f"job_share_grant_{job_id}"):
        try:
            jobs.grant_access(job_id, share_email, share_role, by=user)
        except jobs.JobError as exc:
            st.error(str(exc))
        else:
            st.rerun()

    revoke_options = [
        row["user_email"] for row in access_rows if row["role"] != "owner"
    ]
    if revoke_options:
        revoke_email = st.selectbox(
            "Remove access",
            revoke_options,
            key=f"job_share_revoke_email_{job_id}",
        )
        if st.button("Revoke access", key=f"job_share_revoke_{job_id}"):
            try:
                jobs.revoke_access(job_id, revoke_email, by=user)
            except jobs.JobError as exc:
                st.error(str(exc))
            else:
                st.rerun()


def _render_review_notes(user: str, job_id: int, role: str | None) -> None:
    notes = jobs.list_review_notes(job_id, user_email=user)
    if notes:
        for note in notes:
            with st.container(border=True):
                state = "Resolved" if note["resolved"] else "Open"
                st.write(
                    f"**{state}** · {note['anchor_kind']} "
                    f"{note['anchor_value']}"
                )
                st.write(note["note"])
                st.caption(f"{note['author_email']} · {note['created_at']}")
                if _can_edit(role) and not note["resolved"]:
                    if st.button("Resolve", key=f"resolve_note_{note['id']}"):
                        try:
                            jobs.resolve_review_note(note["id"], by=user)
                        except jobs.JobError as exc:
                            st.error(str(exc))
                        else:
                            st.rerun()
    else:
        st.caption("No review notes yet.")

    if not _can_edit(role):
        return
    anchor_kind = st.selectbox(
        "Note anchor",
        ["job", "record", "control_number", "validation_issue", "field"],
        key=f"note_anchor_kind_{job_id}",
    )
    anchor_value = st.text_input(
        "Anchor value",
        key=f"note_anchor_value_{job_id}",
        placeholder="Record number, 001/OCLC, issue id, or field",
    )
    note_text = st.text_area("Note", key=f"note_text_{job_id}")
    if st.button("Add note", key=f"add_note_{job_id}"):
        try:
            jobs.add_review_note(
                job_id,
                anchor_kind=anchor_kind,
                anchor_value=anchor_value,
                note=note_text,
                author=user,
            )
        except jobs.JobError as exc:
            st.error(str(exc))
        else:
            st.rerun()


def _render_activity(user: str, job_id: int) -> None:
    activity = jobs.list_activity(job_id, user_email=user)
    if activity:
        for row in reversed(activity[-20:]):
            st.write(
                f"{row['created_at']} — {row['actor_email']}: "
                + _activity_message(row)
            )
    else:
        st.caption("No activity recorded yet.")


def _render_settings(
    user: str,
    job_id: int,
    job: dict[str, object],
    role: str | None,
) -> None:
    can_change_archive = _can_manage(role) and (
        not job["active"] or _can_archive(job)
    )
    if not can_change_archive:
        st.caption("No job settings are available here.")
        return
    if job["active"]:
        if st.button("Archive job", key=f"archive_job_{job_id}"):
            try:
                jobs.archive_job(job_id, by=user)
            except jobs.JobError as exc:
                st.error(str(exc))
            else:
                st.session_state.pop("selected_job_detail_id", None)
                st.rerun()
    elif st.button("Restore job", key=f"restore_job_{job_id}"):
        try:
            jobs.restore_job(job_id, by=user)
        except jobs.JobError as exc:
            st.error(str(exc))
        else:
            st.rerun()
```

- [ ] **Step 5: Compose the approved file-first detail page**

After Back/header rendering in `_render_detail`, replace the former stacked
blocks with:

```python
    files_col, handoff_col = st.columns(
        [4, 1],
        vertical_alignment="top",
        gap="large",
    )
    with files_col:
        _render_files(user, job_id, role)
    with handoff_col:
        _render_handoff(user, job_id, job, role)

    review_tab, people_tab, activity_tab, settings_tab = st.tabs(
        ["Review notes", "People", "Activity", "Settings"]
    )
    with review_tab:
        _render_review_notes(user, job_id, role)
    with people_tab:
        _render_people(user, job_id, role)
    with activity_tab:
        _render_activity(user, job_id)
    with settings_tab:
        _render_settings(user, job_id, job, role)
```

- [ ] **Step 6: Run Jobs tests and repair only presentation expectations**

Run:

```bash
docker compose run --rm -v "$PWD:/workspace" -w /workspace marcedit-web \
  pytest tests/test_jobs_page.py -v
```

Expected: all Jobs-page tests pass with zero skipped. Preserve every assertion
covering checkout tokens, file actions, access roles, status options, generic
authorization errors, default-job archive protection, and session state.

- [ ] **Step 7: Commit**

```bash
git add marcedit_web/views/B_Jobs.py tests/test_jobs_page.py
git commit -m "feat: make job details file-first"
```

---

### Task 4: Verification, review, and ticket completion

**Files:**
- Modify after successful review: `.tickets/TASK-152-jobs-help-and-detail-layout.md`

**Interfaces:**
- Consumes the complete feature from Tasks 1–3.
- Produces a reviewed branch with a Completed ticket and recorded verification.

- [ ] **Step 1: Run source and focused checks**

Run:

```bash
git diff --check main...HEAD
docker compose run --rm -v "$PWD:/workspace" -w /workspace marcedit-web \
  pytest tests/test_jobs_page.py tests/test_docker_compose_config.py -v
```

Expected: no whitespace errors; all selected tests pass; zero skipped.

- [ ] **Step 2: Run the complete suite from the whole worktree**

Run:

```bash
docker compose run --rm -v "$PWD:/workspace" -w /workspace marcedit-web \
  pytest -q
```

Expected: all tests pass with zero failures and zero skipped tests. Treat any
skip as a verification failure.

- [ ] **Step 3: Verify the built image contains the guide**

Run:

```bash
docker build -t marcedit-web:task-152 .
docker run --rm --entrypoint test marcedit-web:task-152 \
  -r /app/docs/jobs.md
```

Expected: both commands exit 0; the guide is readable by the unprivileged
runtime user.

- [ ] **Step 4: Perform signed-in interactive verification**

Start the private app using the project development configuration, then use the
browser testing skill to verify:

1. Jobs list shows **How jobs work** and still opens jobs.
2. Help opens in a large dialog and includes Quick start and the generic
   recurring vendor-load example.
3. An opened job shows Files and Next handoff above the four tabs.
4. A job with at least two files keeps both file rows visible while switching
   Review notes, People, Activity, and Settings.
5. Owner sees status, people, notes, and archive controls in their new places.
6. Editor retains file/status/note actions but not owner-only people/archive
   actions.
7. Viewer can inspect the content but receives no mutation controls.
8. Personal uploads still has no archive action.

Expected: all eight checks pass without a Python exception or lost job context.

- [ ] **Step 5: Request code review and resolve every finding**

Use `superpowers:requesting-code-review` on `main...HEAD`. Require explicit
review of permission preservation, help-file packaging, test intent, and the
absence of unrelated refactoring. Fix every Critical, Important, and Minor
finding, then rerun Steps 1–4. Do not mark the ticket complete while any finding
is unresolved.

- [ ] **Step 6: Mark TASK-152 Completed only after verification and review**

In `.tickets/TASK-152-jobs-help-and-detail-layout.md`, replace:

```markdown
## Status

In-Progress
```

with:

```markdown
## Status

Completed

## Final verification

- Complete workspace-mounted Docker pytest suite passed with zero failures and
  zero skipped tests.
- Signed-in Jobs list, help dialog, file-first detail layout, tab switching,
  multi-file visibility, and owner/editor/viewer behavior were verified.
- The built Docker image contains a readable canonical Jobs guide.
- Code review completed with no unresolved findings.
```

- [ ] **Step 7: Commit the completion record**

```bash
git add .tickets/TASK-152-jobs-help-and-detail-layout.md
git commit -m "docs: complete TASK-152 verification record"
```

- [ ] **Step 8: Run final branch-state checks**

Run:

```bash
git status --short
git log --oneline main..HEAD
```

Expected: clean status and a reviewable sequence containing the design, help,
layout, any review-fix commits, and the final verification record.
