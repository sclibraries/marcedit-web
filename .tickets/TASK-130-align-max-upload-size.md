Title: Align Streamlit maxUploadSize with the app upload cap

Scope (REVISED during implementation — original premise was wrong):
- Original plan: drop `maxUploadSize` 2048 → 256 to match the Home cap
  (200 MB). Investigation showed the 2 GB framework cap is INTENTIONAL:
  the Diff page accepts up to 2 GB per file by design
  (quotas._DEFAULT_DIFF_BYTES, "multi-GB diffs are common cataloging
  workloads") and maxUploadSize is global, so lowering it would break
  the Diff workflow. Dropped that change.
- What lands here instead: fix the Home uploader help text that claimed
  a 2 GB limit (the Home path rejects >200 MB). Done alongside TASK-131.
- TASK-131/132 reduce Home retention and extra copies, and TASK-134 reduces
  Diff retention. They do not remove Streamlit's whole-request upload peak;
  TASK-162 owns bounded-memory large-file ingress outside Streamlit.
- OPEN QUESTION for production (needs ITS/user): does
  /home/www/html/marcedit-web/.env set MARCEDIT_WEB_MAX_UPLOAD_BYTES?
  docker-compose.pull.yml historically defaulted it to 2147483648 (2 GiB),
  which would raise the HOME cap to 2 GiB too. Also note a latent
  conflict to resolve: session.py defaults this same env var's absence
  to 200 MB while quotas.py defaults it to 2 GB (effective today:
  min = 200 MB; but any env value overrides both identically).

Success Criteria:
- Help text no longer claims 2 GB. (done)
- `session.max_upload_bytes()` and `quotas.max_upload_bytes()` no longer carry
  conflicting private defaults. `quotas.max_home_upload_bytes()` becomes the
  authority, uses `MARCEDIT_WEB_MAX_HOME_UPLOAD_BYTES`, defaults to 200 MiB in
  private mode and 5 MiB in public mode, and fails loud on an invalid or
  nonpositive configured value. Session code delegates to that resolver.
- Compose, systemd, `.env.example`, preflight checks, and help text use the Home
  variable above. The legacy `MARCEDIT_WEB_MAX_UPLOAD_BYTES` is removed rather
  than serving as a second fallback authority.
- Server `.env` checked for `MARCEDIT_WEB_MAX_UPLOAD_BYTES`; the production
  legacy value is migrated or removed, and the replacement
  `MARCEDIT_WEB_MAX_HOME_UPLOAD_BYTES` value is verified rather than inferred
  from Compose defaults.
- The Home cap decision is independent of TASK-162's 2 GiB durable-ingress
  target, which uses `MARCEDIT_WEB_DURABLE_MAX_FILE_BYTES` with an absolute
  maximum of 2,147,483,648 bytes.

Status: In-Progress (help text fixed; remaining work is the single-authority
code change plus the production `.env` verification)
