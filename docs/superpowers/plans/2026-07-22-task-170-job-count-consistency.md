# TASK-170 Job Count Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Jobs card file count equal its default-visible detail rows.

**Architecture:** Count non-archived durable `job_files`, the same resource rendered by `job_files.list_files()`. Keep job access as the authorization boundary and stop treating unmaterialized legacy uploads as visible files.

**Tech Stack:** Python 3.9, stdlib SQLite, pytest, Streamlit Jobs page.

## Global Constraints

- Ticket: [TASK-170](../../../.tickets/TASK-170-job-file-count-detail-consistency.md).
- TASK-167 compatibility lands first so retained legacy artifacts can migrate on restart.
- Preserve owner/editor/viewer access and archived-file hiding.
- Do not delete legacy uploads or fabricate job-file rows.
- Do not deploy or edit production data.

---

### Task 1: Align summary and detail visibility

**Files:**
- Modify: `tests/test_jobs.py`
- Modify: `marcedit_web/lib/jobs.py`

**Interfaces:**
- Consumes: `jobs.list_job_summaries(user_email, include_archived=False) -> list[dict]` and `job_files.list_files(job_id, user_email) -> list[dict]`.
- Produces: `file_count` defined as accessible `job_files` with `archived_at IS NULL`.

- [ ] **Step 1: Replace the existing upload-count fixture with a durable file**

Import `job_files`, add an autouse fixture that points
`MARCEDIT_WEB_JOB_FILES_ROOT` at `tmp_path / "job-files"`, and add this helper:

```python
def attach_job_file(job, tmp_path, filename):
    source = tmp_path / filename
    source.write_bytes(b"x")
    return job_files.attach_file(
        job_id=job["id"],
        user_email="owner@example.edu",
        source_path=source,
        filename=filename,
        record_count=1,
        file_bytes=1,
    )
```

In `test_list_job_summaries_include_counts_and_status`, call this helper and
retain `assert rows[0]["file_count"] == 1`. Remove its direct
`upload_persistence.record_upload()` setup.

- [ ] **Step 2: Add two failing visibility regressions**

```python
def test_job_summary_does_not_count_unmaterialized_legacy_upload(tmp_path):
    """A card cannot claim a file that detail cannot render."""
    job = jobs.create_job("owner@example.edu", "Routledge load")
    upload_persistence.record_upload(
        user="owner@example.edu",
        filename="legacy.mrc",
        file_path=str(tmp_path / "legacy.mrc"),
        record_count=1,
        file_bytes=1,
        job_id=job["id"],
    )

    summary = jobs.list_job_summaries("owner@example.edu")[0]

    assert summary["file_count"] == 0


def test_job_summary_count_matches_visible_non_archived_files(tmp_path):
    """Archived files stay hidden from both the card and detail list."""
    job = jobs.create_job("owner@example.edu", "Routledge load")
    visible = attach_job_file(job, tmp_path, "visible.mrc")
    archived = attach_job_file(job, tmp_path, "archived.mrc")
    with db.connect() as conn:
        conn.execute(
            "UPDATE job_files SET archived_at=?,archived_by=? WHERE id=?",
            ("2026-07-22T12:00:00Z", "owner@example.edu", archived["id"]),
        )

    summary = jobs.list_job_summaries("owner@example.edu")[0]
    detail = job_files.list_files(job["id"], "owner@example.edu")

    assert [row["id"] for row in detail] == [visible["id"]]
    assert summary["file_count"] == len(detail) == 1
```

- [ ] **Step 3: Run regressions and verify RED**

Run:

```bash
python3 -m pytest tests/test_jobs.py -q
```

Expected: the unmaterialized upload is incorrectly counted and the archived-file count disagrees with detail.

- [ ] **Step 4: Change the summary query**

In `jobs.list_job_summaries()`, replace the upload join/count with:

```sql
LEFT JOIN job_files
  ON job_files.job_id = jobs.id
 AND job_files.archived_at IS NULL
```

and:

```sql
COUNT(DISTINCT job_files.id) AS file_count
```

Keep the existing `job_access` join, job archive filter, review-note count, grouping, and ordering.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_jobs.py tests/test_job_files.py tests/test_collaboration.py -q
```

Expected: all pass; report every skip.

- [ ] **Step 6: Run static checks and commit**

```bash
python3 -m py_compile marcedit_web/lib/jobs.py
git diff --check
git add marcedit_web/lib/jobs.py tests/test_jobs.py
git commit -m "fix: align job file counts with detail"
```

### Task 2: Review and record TASK-170 evidence

**Files:**
- Modify: `.tickets/TASK-170-job-file-count-detail-consistency.md`

- [ ] **Step 1: Request independent review**

Review query semantics, authorization, archive behavior, test intent, and interaction with TASK-167 migration. Resolve every Critical and Important finding.

- [ ] **Step 2: Record evidence and commit**

Append RED/GREEN commands, exact counts/skips, static checks, hashes, and clean review verdict; set `Status: Completed`, then commit:

```bash
git add .tickets/TASK-170-job-file-count-detail-consistency.md
git commit -m "docs: complete TASK-170 evidence"
```
