Title: Diagnose overnight marcedit-web service death on libtools2

Scope:
- The service was down on the morning of 2026-07-08 (first morning after the
  TASK-116 deploy); re-running scripts/deploy.sh restored it.
- Determine from journalctl why the process stopped and why Restart=on-failure
  did not bring it back (clean exit? OOM? ExecStartPre failure loop? external
  stop?).
- Fix the root cause; consider Restart=always if a clean-exit path is found.

Success Criteria:
- Root cause identified from journal evidence, not conjecture.
- A fix is applied (unit hardening, code fix, or documented external cause).
- Service survives a subsequent overnight period.

Status: In-Progress

Update 2026-07-09: service survived the night of 07-08→07-09. NOTE: no fix
was deployed before that night, so survival means the trigger (heavy
upload activity like 07-07 16:07) didn't recur — not that the bug is
gone. Keep the watch cron running. Fixes now ready to deploy: streaming
ingest + widget release + download gating (TASK-131/132/135) remove the
suspected memory trigger; the watchdog (TASK-133) bounds any future
zombie to ~2.5 min of downtime.

Investigation notes (2026-07-08):
- The journal excerpt provided (tail -60) shows only a 16:07 Streamlit
  "Uncaught app execution" traceback from Home.py:74
  (`current_job_id` StreamlitAPIException). This is a page-level error that
  Streamlit catches and renders in the browser; it does NOT terminate the
  server process, so it is not the cause of death. It is the (locally fixed,
  never pushed) TASK-117-current-job-create-state bug — production deploys
  from origin/main, which is ~20 commits behind local main and still
  contains the old create-job code.
- The excerpt cannot be from the stated command: `--since "2026-07-07 19:00"`
  cannot emit 16:07 entries from the same day. The actual 19:00→09:00 window
  has not been seen yet. Need a re-run.
- If the true window contains no systemd unit-state messages, the process
  never exited — i.e. the service was hung, not dead, and Restart=on-failure
  was never triggered. deploy.sh "restored" it only because it runs
  `systemctl restart marcedit-web`.
- ITS confirmed (2026-07-08): the unit journal is EMPTY for the whole
  19:00→09:00 outage window — they had to move --since back to get any
  output, and the last entries are the 16:07 traceback. systemd logs every
  unit state change, so an empty window means the process never exited.
  Conclusion so far: the service HUNG rather than crashed. That also answers
  the ticket's second question — Restart=on-failure never fired because
  there was no failure event to react to; a hung process looks "active
  (running)" to systemd. deploy.sh restored it only via its
  `systemctl restart`.
- Leading hypothesis (unconfirmed): memory pressure / swap thrash. Uploads
  (limit 2 GB per .streamlit/config.toml) are held in memory in
  session_state, in several copies (raw bytes + parsed store + download
  payload). Exhausted memory with swap available wedges the process without
  any log line and without triggering the kernel OOM killer — matching the
  silent journal exactly. Deadlock/fd-exhaustion fit less well (fd
  exhaustion spams the journal; a deadlocked script thread doesn't stop
  Tornado's health endpoint).
- CONFIRMED by full journal (ITS, 2026-07-08): PID 1834865 was still alive
  at the 09:56 morning restart — systemd "Stopping…" reached it, it printed
  "Stopping...", answered localhost health checks in 3–310 ms (503 =
  RuntimeState.STOPPING, normal during shutdown), rejected a websocket with
  RuntimeStoppedError, and exited cleanly ("marcedit-web.service:
  Succeeded"). So the service NEVER crashed; Restart= had nothing to react
  to. The outage was unreachability/wedge, not death.
- REVISION of the memory hypothesis: 3 ms health responses at 09:56 mean
  the Tornado event loop was responsive at restart time — a box-wide swap
  thrash at that moment is unlikely. Either (a) memory pressure occurred
  overnight and self-resolved when sessions disconnected, (b) the Streamlit
  Runtime/script layer wedged while the web layer stayed healthy (stuck
  script threads; the 80-second shutdown with a CancelledError hints at
  lingering tasks), or (c) the failure was in front of the app
  (Apache/Shibboleth/WebSocket path) — note TASK-115/116 changed the auth
  and WS story the same day.
- External probing is impossible: all /marcedit-web/_stcore/* paths 302 to
  Shibboleth WAYF unauthenticated (verified 2026-07-08). Monitoring must
  run on-box.
- Browser symptom (user, morning of 07-08): loading skeleton rendered but
  never progressed; network tab showed `health` and `ws` requests red
  (status codes not captured). Interpretation: static assets were served
  fine through Apache→Tornado, so the proxy chain and the web server were
  healthy — the refusal was at the Streamlit Runtime layer. This is the
  "zombie runtime" state: Runtime dead/stopped, Tornado alive. It matches
  the 09:56 log exactly (millisecond 503 health responses,
  RuntimeStoppedError on ws connect, clean stop) and explains the silent
  journal (no process-level event ever occurred). Upstream reports of this
  hang class exist (streamlit#9004, closed unresolved) — no fix version to
  upgrade to.
- Memory link, revised: a MemoryError raised inside the Runtime coroutine
  or session machinery kills the Runtime but leaves Tornado serving; after
  GC the process is responsive again but the app never recovers. With
  maxUploadSize=2048, a single large upload buffers up to 2 GB into
  Tornado-process RAM (MemoryUploadedFileManager) before the app's 200 MB
  check ever runs — prime candidate trigger. Unproven: the health status
  code was not captured, journal shows no MemoryError (it can fail to log
  by nature).
- Alternative not yet excluded: expired Shibboleth session making XHR/WS
  302 to login.smith.edu (cross-origin → red in network tab). Argues
  against: restarting only marcedit-web restored service, and Shib is
  untouched by that (confound: the user also re-logged-in after restart).
- Discriminating evidence still needed:
  1. THE WATCH CRON (below) — on-box curl bypasses Shibboleth and records
     the health status code every 5 min. If health flips 200→503 overnight,
     runtime death is confirmed with a timestamp; if it stays 200 while
     users see failures, the fault is in the Apache/Shib layer.
  2. How ITS determined "down between 19:00 and 09:00" — which monitor,
     probing what URL, seeing what error. (Their monitor may treat the
     Shib 302 as down — it 302s even now while healthy.)
  3. Kernel log: sudo journalctl -k --since "2026-07-07 16:00" --until "2026-07-08 09:00" --no-pager | grep -iE "oom|out of memory|killed process|blocked for more"
  4. Memory/swap overnight if sysstat runs: sar -r -f /var/log/sa/sa07; sar -S -f /var/log/sa/sa07
- On-box overnight instrumentation for tonight (root crontab), so a repeat
  incident yields an exact wedge time + memory trajectory:
    */5 * * * * echo "$(date -Is) health=$(curl -sm5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8501/marcedit-web/_stcore/health) rss_kb=$(ps -o rss= -p $(systemctl show -p MainPID --value marcedit-web) 2>/dev/null)" >> /var/log/marcedit-watch.log
- Remediation direction (pending confirmation): Restart=always will NOT fix
  a hang (no exit → no restart). Options that do cover hangs: (a) MemoryMax=
  on the unit so runaway memory becomes a SIGKILL that Restart=on-failure
  can recover from; (b) a systemd timer that curls
  /marcedit-web/_stcore/health and restarts the unit on failure; (c) lower
  the 2 GB upload ceiling to something the box can actually hold in RAM
  several times over.
