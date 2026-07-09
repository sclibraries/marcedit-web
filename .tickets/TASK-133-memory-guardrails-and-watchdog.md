Title: systemd memory guardrails + health watchdog for marcedit-web

Scope:
- TASK-117 established the failure mode: Streamlit Runtime dies inside a
  live process (health 503, ws refused, static assets fine) — invisible to
  Restart=on-failure by construction. Defenses belong at the unit layer.
- Unit hardening (deploy/marcedit-web*.service): MemoryHigh= (reclaim
  before crisis), MemoryMax= (kill → Restart=on-failure recovers),
  MemorySwapMax=0 (no thrash). Values need libtools2 RAM from ITS
  (`free -h`) before finalizing; ship with placeholders + comment.
- Health watchdog: marcedit-web-watchdog.service (oneshot: curl
  http://127.0.0.1:8501/marcedit-web/_stcore/health; on failure N times →
  systemctl restart marcedit-web) + marcedit-web-watchdog.timer (every
  2 min). NOPASSWD sudoers already exists for restart (deploy/marcedit.sudoers)
  if run as marcedit; simpler: run watchdog as root system unit.
- Remember prod path divergence: live install is /home/www/html, checked-in
  units say /var/www/html — keep unit content path-consistent with repo
  convention and note the divergence in the install docs.

Success Criteria:
- Unit files + timer checked into deploy/ with install notes.
- Watchdog restarts the service when health returns non-200 repeatedly,
  and does nothing when healthy (documented manual verification steps for
  libtools2; cannot be exercised from dev).
- Memory limits documented with the RAM-sizing rationale.

Status: Completed for the watchdog (2026-07-09: units checked in with
is-active maintenance guard and two-tier warning after code review;
docs updated with install + SIGSTOP verification steps). Memory limits
remain commented in marcedit-web.service pending ITS: free -h and
stat -fc %T /sys/fs/cgroup. NOT YET INSTALLED on libtools2.
