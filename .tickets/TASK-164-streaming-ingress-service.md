Title: Add the authenticated streaming MARC ingress service

Parent: TASK-162
Dependency: TASK-163

Scope:
- Add a private loopback-only ingress service and matching Compose service.
  Apache exposes only its `/marcedit-web-artifacts/` route behind Shibboleth,
  strips client identity/attestation headers, then injects server-side identity
  and the existing proxy attestation secret. Public/OAuth-only ingress is not
  supported in the first release.
- Fail closed unless proxy attestation passes in constant time and the canonical
  Shibboleth user is an approved private application user. Direct-port,
  anonymous, unapproved, and forged-header requests are rejected.
- Require the exact configured Origin, deny CORS, require a non-simple custom
  request header, accept JSON reservation requests and raw MARC content only,
  and reject missing/mismatched `Content-Length`.
- `POST /uploads` validates filename/declared bytes/idempotency key and reserves
  capacity. `PUT /uploads/{opaque_id}/content` streams fixed 1 MiB chunks to a
  private generated pending name, verifies the exact reserved length, computes
  SHA-256, validates MARC/counts, fsyncs the file and parent, renames to its
  generated final path, fsyncs the final parent, then commits ready metadata.
  `GET /uploads/status/{idempotency_key}` recovers lost acknowledgements.
- Run at most 8 concurrent upload bodies with a connection backlog of 32;
  excess reservations or connections receive a bounded retryable response
  without consuming upload capacity.
- MARC publication rejects empty files, nonnumeric or impossible five-byte
  record lengths, leader lengths outside the remaining body, truncated or
  trailing bytes, and any record pymarc cannot parse. Validation consumes the
  file exactly to EOF and produces at least one record.
- Normalize display filenames to Unicode NFC, basename-only metadata with
  control characters removed and at most 255 UTF-8 bytes. Storage paths never
  derive from display names.
- On write/validation failure, retain the prior artifact state when applicable,
  remove or reconcile the partial, release reservations, and return a bounded
  safe error.
- Add systemd/Compose health checks, restart policy, dedicated writable roots,
  shared-group permissions, ingress cgroup limits, Apache body/timeout/proxy
  streaming configuration, deployment/preflight docs, and audit events.

Success Criteria:
- Upload RSS remains chunk-bounded as payload size grows and the body never
  enters Streamlit.
- Tests cover direct-port bypass, forged headers, anonymous/unapproved users,
  wrong Origin, CORS preflight, cross-user access, malformed request types,
  length boundaries, filenames, disconnects before/after commit, idempotent
  recovery, service-wide connection/upload admission, disk-full behavior,
  strict MARC/EOF validity, checksum/count integrity, and audit bounds.
- A crash before DB commit leaves no visible artifact; a crash after commit but
  before response is recoverable by the owner-bound status endpoint.
- Deployment renders one healthy loopback service with only required writable
  storage and records Streamlit, ingress, worker, and aggregate memory limits.
- Complete suites and independent review pass with no unresolved Critical or
  Important findings.

Status: Todo
