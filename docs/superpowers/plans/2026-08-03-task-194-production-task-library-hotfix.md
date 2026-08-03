# TASK-194 Production Task-Library Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-194](../../../.tickets/TASK-194-production-task-library-hotfix.md)

**Goal:** Prepare a production release containing the reviewed task-authoring, migration, partner-pattern, and folder/search work while preserving the currently installed synchronous service topology.

**Architecture:** This plan begins with a read-only Gate-0 runtime capture and produces no deployment implementation until that evidence is approved. After the gate, the release branch is built from the exact deployed SHA, the Operations-era deploy script is rewritten to manage only the captured unit, and the release is verified with backup/restore, migration, Docker, and authenticated browser tests.

**Tech Stack:** Existing Python 3.9 venv, Streamlit `>=1.50,<2`, pymarc, stdlib sqlite3, systemd/sudo capability already installed on production, Docker Compose.

## Global Constraints

- TASK-194 planning is blocked until Gate 0 captures and records the live runtime lineage.
- Do not infer production units, paths, venvs, SQLite versions, or sudo permissions from checked-in assets.
- No durable Operations queue, worker, private unit, systemd change, sudoers change, proxy change, OAuth change, or production directory rename.
- No `RETURNING`; use the production-compatible SQLite contract.
- Backup verification must include integrity, schema inventory, user_version, and every application-table row count.
- Do not push or deploy without explicit approval of release and rollback SHAs.

---

### Task 1: Capture and approve production runtime lineage (blocking gate)

**Files:**
- Create: `/private/tmp/marcedit-task-194-runtime-lineage.md` (local/private until approved)
- Modify: `.tickets/TASK-194-production-task-library-hotfix.md` after capture review
- Test: read-only shell capture commands on production

- [ ] **Step 1: Record repository identity**: real path, clean status, branch, full SHA, and remote URL without changing the tree.
- [ ] **Step 2: Record installed service facts** with `systemctl show`/`cat`: active/enabled state, FragmentPath, WorkingDirectory, ExecStart, User, Group, EnvironmentFile, and the exact unit actually serving HTTP.
- [ ] **Step 3: Record privilege/dependency facts**: `sudo -n -l`, venv Python/Streamlit/pymarc versions, Python and CLI SQLite versions, and `inspect.signature(st.dialog)`.
- [ ] **Step 4: Record database facts**: effective path, permissions, byte size, free space, and a schema/table inventory.
- [ ] **Step 5: Compare the capture with the design’s prior evidence**. If any unit/path/version differs, amend this plan before any implementation.
- [ ] **Step 6: Obtain user approval of the captured constants**. If unavailable, stop TASK-194 implementation here.

### Task 2: Build the production-lineage release branch

**Files:**
- Create: release branch from the captured SHA
- Modify: release cherry-pick/port set only
- Test: exact-lineage commit and diff audit

- [ ] **Step 1:** Create the branch from the captured full SHA and record each source commit range for TASK-190 through TASK-193.
- [ ] **Step 2:** Port reviewed changes with conflict notes; do not merge durable Operations commits.
- [ ] **Step 3:** Audit `git diff` for forbidden queue/worker/Operations/systemd/sudoers/proxy/OAuth changes.
- [ ] **Step 4:** Run the full Python 3.9 suite before touching deployment scripts.
- [ ] **Step 5:** Commit `chore: assemble task-library production release lineage`.

### Task 3: Rewrite deploy and backup procedure after Gate 0

**Files:**
- Modify: `scripts/deploy.sh`
- Modify: `marcedit_web/ops/backup.py` to expose the verified online-backup and restore-check functions
- Test: `tests/test_deploy_script.py`, `tests/test_backup.py`, Docker deployment fixtures

- [ ] **Step 1: Add failing tests** for branch-aware `--ff-only` pull, dependency installation, Streamlit/dialog preflight, captured-unit-only restart, and rejection of worker/private/Operations commands.
- [ ] **Step 2: Add failing backup tests** for Python SQLite online backup, independent `integrity_check`, exact schema inventory, user_version, all application-table row counts, path/size/SHA recording, and restore verification.
- [ ] **Step 3: Rewrite** the Operations-era lifecycle to perform only the seven approved hotfix steps from the design; preserve pip upgrade and `requirements.txt` installation.
- [ ] **Step 4:** Run script/config tests and a Docker dry-run using a fake captured unit; confirm forbidden topology commands fail closed.
- [ ] **Step 5:** Commit `ops: make deployment script production-lineage aware`.

### Task 4: Verify upgrade, rollback, and authenticated application behavior

**Files:**
- Modify: `.tickets/TASK-194-production-task-library-hotfix.md`
- Test: Docker upgrade/rollback, authenticated browser, schema migration, synchronous execution, and full suites

- [ ] **Step 1:** Run migration tests from the captured production schema fixture, including private/shared tasks and name conflicts.
- [ ] **Step 2:** Run Docker upgrade and rollback tests; restore the verified backup into a disposable database and compare schema/row counts.
- [ ] **Step 3:** Run authenticated browser tests for authoring, import, preview, synchronous execution, folders, search, sharing, and shared editing.
- [ ] **Step 4:** Run the full supported Python 3.9 source-mounted suite and report every skip/failure/environmental limitation.
- [ ] **Step 5:** Obtain independent code, migration, authorization, and deployment review.
- [ ] **Step 6:** Record release SHA, rollback SHA, backup path, checks, and user approval. Only then update the ticket to `Completed`; a successful push alone is not completion.
