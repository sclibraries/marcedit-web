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
- Require `MARCEDIT_WEB_ARTIFACT_ORIGIN` in production as one normalized HTTPS
  origin with no path, query, or fragment. Origin mismatch fails closed.
- Serve a small same-origin uploader page from the Shibboleth-protected artifact
  route. It uses the browser File/Blob streaming request directly and is not a
  sandboxed Streamlit component or cross-origin iframe. Streamlit links to this
  page and discovers the authenticated owner's ready artifacts through bounded
  metadata; Shibboleth cookies and the exact-Origin contract therefore remain
  valid and no proxy secret enters browser code.
- `POST /uploads` validates filename/declared bytes/idempotency key and reserves
  capacity. `PUT /uploads/{opaque_id}/content` streams fixed 1 MiB chunks to a
  private generated pending name, verifies the exact reserved length, computes
  SHA-256, performs incremental structural MARC validation/counting as chunks
  arrive, renews the upload lease while active, fsyncs the file and
  parent, renames to its generated final path, fsyncs the final parent, then
  commits ready metadata.
  `GET /uploads/status/{idempotency_key}` recovers lost acknowledgements.
- Run at most 8 concurrent upload bodies with a connection backlog of 32;
  excess reservations or connections receive a bounded retryable response
  without consuming upload capacity.
- Synchronous upload validation is a cheap sequential length walk: reject empty
  files, nonnumeric or impossible five-byte record lengths, leader lengths
  outside the remaining body, truncation, trailing bytes, and a walk that does
  not consume exactly to EOF with at least one record. Full per-record pymarc
  parsing is deferred to TASK-165 profiling so a long CPU parse does not hold an
  upload connection open; parse failure prevents review or publication.
- Normalize display filenames to Unicode NFC, basename-only metadata with
  control characters removed and at most 255 UTF-8 bytes. Storage paths never
  derive from display names.
- On write/validation failure, retain the prior artifact state when applicable,
  remove or reconcile the partial, release reservations, and return a bounded
  safe error.
- Add systemd/Compose health checks, restart policy, dedicated writable roots,
  shared-group permissions, ingress cgroup limits, Apache body/timeout/proxy
  streaming configuration sized for transfer time rather than worker parse
  time, deployment/preflight docs, and audit events.
- On only the protected artifact route, configure Apache
  `LimitRequestBody 0` so Apache does not reject exactly 2,147,483,648 bytes one
  byte early. The application must reject missing, chunked, mismatched, or
  greater-than-2-GiB content length before reading the body. Preserve proxy
  request streaming without buffering the body in Apache or Streamlit.
- Complete streaming, hashing, validation, fsync, and rename before a short
  ready-metadata transaction; never keep a SQLite writer transaction open for
  file or request-body work.

Success Criteria:
- Upload RSS remains chunk-bounded as payload size grows and the body never
  enters Streamlit.
- A transfer that remains active renews its upload lease and cannot be reaped
  by age-based pending reconciliation.
- Tests cover direct-port bypass, forged headers, anonymous/unapproved users,
  wrong Origin, CORS preflight, cross-user access, malformed request types,
  length boundaries, filenames, disconnects before/after commit, idempotent
  recovery, service-wide connection/upload admission, disk-full behavior,
  strict MARC/EOF validity, checksum/count integrity, and audit bounds.
- A real protected Apache-route integration test accepts exactly
  2,147,483,648 declared/body bytes and rejects 2,147,483,649 before body read;
  deployment inspection verifies the route-scoped `LimitRequestBody 0` and
  Shibboleth identity/header-stripping contract.
- A crash before DB commit leaves no visible artifact; a crash after commit but
  before response is recoverable by the owner-bound status endpoint.
- Deployment renders one healthy loopback service with only required writable
  storage and records Streamlit, ingress, worker, and aggregate memory limits.
- Complete suites and independent review pass with no unresolved Critical or
  Important findings.

Status: Todo
