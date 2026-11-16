# Roadmap — Smith Metadata Studio

The orchestrator keeps the milestone order and notes. The ticket tables
between the backlog markers are generated from `.tickets/` by
`scripts/backlog.py` (TASK-259); do not edit them by hand. Ticket files
are the source of truth.

## Milestones (in priority order)

1. **M0 — Production integrity**
   Keep what is deployed correct and recoverable. Main matches
   production since 2026-11-13 (TASK-260). Next: production writes
   (TASK-255, closed 2026-11-13: no longer occurs) and the 13 tests
   already failing on main (TASK-262). TASK-117 and TASK-130 need one ITS session, for host
   RAM and cgroup facts and the production `.env` upload cap.
2. **M1 — Workflow**
   The orchestrator/implementer loop and backlog tooling. Done:
   TASK-259 (first Codex build) and TASK-258.
3. **M2 — Cataloger value and speed**
   Per TASK-252: stay on Streamlit and spend effort on measured workflow
   speed and feedback rather than new infrastructure. Proposed, not yet
   ticketed:
   - Measure the slow morning refresh (auth, connection, first render)
     before guessing a cause.
   - Stop Workspace from running hidden tabs (Report walks every record).
   - Show progress while a refreshed session restores its batch.
4. **M3 — Code health**
   Low-risk Codex work: dead code, docstrings, tests, the supply-chain
   lockfile. TASK-098 and TASK-145 are close-out reviews that may need
   only a regression test.
5. **M4 — Host hardening (needs ITS)**
   systemd hardening, sandbox confinement, memory limits, and large-batch
   acceptance evidence on libtools2.
6. **M5 — Parked: durable operations**
   Blocked on one decision: re-enable the durable queue and worker
   (`runmode.DURABLE_OPERATIONS_ENABLED`) or redesign these features to
   run synchronously. TASK-252 argues against the large-file epic
   (TASK-162 to TASK-166) unless 2 GiB Diff is a proven need. TASK-097
   (presence) needs a separate yes/no.

## Unmerged branches

| Branch | State | Plan |
|---|---|---|
| `task-134-confinement-fix` | Full TASK-134 work, about 300 commits behind | Port when TASK-134 is planned |
| `task-198-decoupled-workspace` | Streamlit-replacement prototype | Kept isolated per TASK-252 |
| `task-173-infrastructure-release-envelope` | Release-staging work, stale since 2026-07 | Decide: revive or archive |

## Backlog

<!-- backlog:start -->
### M0 — Production integrity

| Ticket | Title | Status | Size |
| --- | --- | --- | --- |
| [TASK-117-overnight-service-death](.tickets/TASK-117-overnight-service-death.md) | Diagnose overnight marcedit-web service death on libtools2 | In-Progress |  |
| [TASK-130-align-max-upload-size](.tickets/TASK-130-align-max-upload-size.md) | Align Streamlit maxUploadSize with the app upload cap | In-Progress |  |
| [TASK-256-routledge-proxy-condition](.tickets/TASK-256-routledge-proxy-condition.md) | Determine conditional Smith proxy handling for Routledge task | In-Progress |  |

### M1 — Workflow

| Ticket | Title | Status | Size |
| --- | --- | --- | --- |

### M2 — Cataloger value and speed

| Ticket | Title | Status | Size |
| --- | --- | --- | --- |
| [TASK-103-canned-cataloger-record-actions](.tickets/TASK-103-canned-cataloger-record-actions.md) | TASK-103 — Canned cataloger record actions | Todo |  |
| [TASK-134-diff-uploader-widget-memory](.tickets/TASK-134-diff-uploader-widget-memory.md) | Release Diff page uploader widget memory after ingest | Todo |  |

### M3 — Code health

| Ticket | Title | Status | Size |
| --- | --- | --- | --- |
| [TASK-076-ast-allowlist-task-bodies](.tickets/TASK-076-ast-allowlist-task-bodies.md) | TASK-076 — AST allowlist for non-admin and imported task bodies | Todo |  |
| [TASK-077-python-upgrade-cve-scanning-lockfile](.tickets/TASK-077-python-upgrade-cve-scanning-lockfile.md) | TASK-077 — CVE scanning + hash-pinned lockfile on Python 3.9 (upgrade declined) | Todo |  |
| [TASK-078-dry-consolidation-marc-primitives](.tickets/TASK-078-dry-consolidation-marc-primitives.md) | TASK-078 — Consolidate duplicated MARC primitives (DRY) | Todo |  |
| [TASK-078c-keys-session-state-constants](.tickets/TASK-078c-keys-session-state-constants.md) | TASK-078c-keys — Session-state key constants | Todo |  |
| [TASK-079-security-contract-docstrings](.tickets/TASK-079-security-contract-docstrings.md) | TASK-079 — Document the load-bearing security contracts | Todo |  |
| [TASK-080-dead-code-and-stale-stub-removal](.tickets/TASK-080-dead-code-and-stale-stub-removal.md) | TASK-080 — Remove dead code and the stale Workspace diff stub | Todo |  |
| [TASK-098-collaboration-provenance-display](.tickets/TASK-098-collaboration-provenance-display.md) | TASK-098 — Collaboration provenance display | Todo |  |
| [TASK-144-history-interactive-test-coverage](.tickets/TASK-144-history-interactive-test-coverage.md) | History page interactive test-coverage gaps | Todo |  |
| [TASK-145-restore-upload-row-provenance](.tickets/TASK-145-restore-upload-row-provenance.md) | Snapshot restore creates a new upload row per restore | Todo |  |

### M4 — Host hardening (needs ITS)

| Ticket | Title | Status | Size |
| --- | --- | --- | --- |
| [TASK-058-cicd-native-deploy](.tickets/TASK-058-cicd-native-deploy.md) | TASK-058 — CI/CD pipeline + native-Python deploy at libtools2/marcedit-web | Todo |  |
| [TASK-074-sandbox-egress-seccomp-fsjail](.tickets/TASK-074-sandbox-egress-seccomp-fsjail.md) | TASK-074 — Bound the sandbox: block egress, add seccomp, read-only FS jail | Todo |  |
| [TASK-075-systemd-fs-hardening-umask](.tickets/TASK-075-systemd-fs-hardening-umask.md) | TASK-075 — Add systemd hardening directives and a restrictive umask | Todo |  |
| [TASK-147-large-batch-memory-performance](.tickets/TASK-147-large-batch-memory-performance.md) | Bound memory and accelerate 50K-100K record workflows | In-Progress |  |

### M5 — Parked: durable operations

| Ticket | Title | Status | Size |
| --- | --- | --- | --- |
| [TASK-097-collaboration-presence](.tickets/TASK-097-collaboration-presence.md) | TASK-097 — Shared job presence indicators | Todo |  |
| [TASK-157-queued-marc-merge-split](.tickets/TASK-157-queued-marc-merge-split.md) | Add queued MARC merge and split workflows | Todo |  |
| [TASK-162-durable-large-file-ingress](.tickets/TASK-162-durable-large-file-ingress.md) | Deliver bounded-memory durable MARC ingress and queued Diff | Todo |  |
| [TASK-163-durable-artifact-registry](.tickets/TASK-163-durable-artifact-registry.md) | Add durable artifact identity, admission, references, and leases | Todo |  |
| [TASK-164-streaming-ingress-service](.tickets/TASK-164-streaming-ingress-service.md) | Add the authenticated streaming MARC ingress service | Todo |  |
| [TASK-165-queued-diff-multi-results](.tickets/TASK-165-queued-diff-multi-results.md) | Queue Diff review with ordered inputs and atomic multiple results | Todo |  |
| [TASK-166-artifact-download-retention](.tickets/TASK-166-artifact-download-retention.md) | Stream durable artifact downloads and reconcile retention | Todo |  |
<!-- backlog:end -->
