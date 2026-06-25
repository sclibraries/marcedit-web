# TASK-074 — Bound the sandbox: block egress, add seccomp, read-only FS jail

**Status:** Todo
**Priority:** Tier 1 — Hardening (defense-in-depth)
**Source:** Deep code audit 2026-06-17 — horizon hardening (egress/seccomp/fs-jail)

## Title

Tighten the task sandbox so an escaped or hostile task body can't exfiltrate
over the network, call dangerous syscalls, or read other catalogers' data.

## Scope

- `lib/sandbox.py:30-37` documents no network namespace, no chroot, no seccomp.
  These are the only OS-level RCE containment given the sandbox is explicitly
  not a security boundary.
- Block outbound network for the child (`PrivateNetwork=true` /
  `IPAddressDeny=any` on a dedicated slice, or `unshare(CLONE_NEWNET)` in
  `preexec_fn`) — tasks never need the network.
- Apply a seccomp syscall allowlist to the child (`prctl(PR_SET_SECCOMP)` via a
  small helper, or a per-exec `SystemCallFilter`). Kill on disallowed syscalls.
- Make the child's filesystem read-only except its workdir (bind-mount/chroot
  or systemd `RootDirectory`/`ReadOnlyPaths`) so it can't read `marcedit.db`,
  audit logs, or other catalogers' batches.

## Success Criteria

1. A task body that opens an outbound socket fails.
2. A task body that calls a blocked syscall (e.g. `exec` of `/bin/sh`) is killed.
3. A task body cannot read any path outside its workdir.
4. Legitimate transforms still run; the `sandbox.py` docstring is updated to
   reflect the new boundaries; focused tests and the Docker test suite pass.
