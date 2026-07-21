Title: Deliver bounded-memory durable MARC ingress and queued Diff

Related: TASK-117, TASK-130, TASK-133, TASK-134, TASK-147, TASK-156, TASK-157

Children:
- TASK-163: durable artifact registry, admission, references, and leases
- TASK-164: authenticated streaming ingress service and deployment
- TASK-165: queued Diff with ordered inputs and atomic multiple results
- TASK-166: direct artifact download, retention, and reconciliation

Scope:
- Preserve 2 GiB (2,147,483,648 bytes) as the absolute private large-MARC
  product target without routing upload or download bodies through Streamlit.
- Deliver one reusable durable-artifact contract for browser ingress, queued
  Diff, and later TASK-157 merge/split workflows.
- Keep this ticket as the parent end-to-end acceptance gate. Each child is an
  independently planned, TDD-verified, and reviewed implementation unit.
- Measure the complete authenticated browser upload, queue, retained output,
  and direct download path using libtools2 host, disk, cgroup, and service
  evidence.

Success Criteria:
- TASK-163 through TASK-166 are Completed with no unresolved Critical or
  Important review findings.
- Upload and download bodies bypass Streamlit, and Streamlit session state
  contains only bounded artifact and operation metadata.
- The system admits work only after transactional per-user and service-wide
  storage reservation succeeds; concurrent uploads cannot overcommit configured
  capacity or reserved free disk.
- The private service accepts a valid file of exactly 2,147,483,648 bytes when
  the measured host envelope supports it; the next byte is rejected before
  publication. If production capacity cannot support that run, this parent
  remains open and records the measured supported ceiling without lowering the
  2 GiB product target.
- A queued Diff survives UI, ingress, and worker restarts; it atomically exposes
  all validated outputs or none on failure/cancellation.
- Cleanup cannot race submission, worker reads, Job adoption, or active
  downloads because every consumer holds a transactional reference or renewable
  lease before cleanup may claim an artifact.
- A fixed-seed three-session production run records the deployed SHA, exact
  fixtures, service and aggregate RSS/cgroup/disk evidence, operation events,
  checksums, record counts, output integrity, and zero OOM/watchdog restarts.
- Focused and complete suites pass with every skip reported, and final design,
  security, operations, and code reviews are clean.

Dependencies:
- TASK-134 may ship first as containment but does not satisfy this ticket.
- TASK-130 establishes the separate Home limit authority.
- TASK-133 watchdog and selected memory controls are installed before maximum
  production acceptance.
- TASK-147 production acceptance consumes this ticket's final browser path.
- TASK-157 consumes the completed ordered-input/multi-result primitives.

Status: Todo
