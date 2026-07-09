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
- The RAM exposure the lower cap would have addressed is closed
  structurally instead: TASK-131/132 (Home widget release + streaming
  ingest) and TASK-134 (Diff widget release).
- OPEN QUESTION for production (needs ITS/user): does
  /home/www/html/marcedit-web/.env set MARCEDIT_WEB_MAX_UPLOAD_BYTES?
  docker-compose.pull.yml historically defaulted it to 2147483648 (2 GiB),
  which would raise the HOME cap to 2 GiB too. Also note a latent
  conflict to resolve: session.py defaults this same env var's absence
  to 200 MB while quotas.py defaults it to 2 GB (effective today:
  min = 200 MB; but any env value overrides both identically).

Success Criteria:
- Help text no longer claims 2 GB. (done)
- Server .env checked for MARCEDIT_WEB_MAX_UPLOAD_BYTES; decision
  recorded on the effective production Home cap.

Status: In-Progress (2026-07-08: help text fixed; blocked on server .env
check for the production cap question)
