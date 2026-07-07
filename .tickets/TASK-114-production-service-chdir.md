Title: Diagnose production systemd CHDIR startup failure

Scope:
- Investigate the reported `marcedit-web.service` startup error on libtools2.
- Identify the expected production filesystem paths from checked-in deploy docs and unit files.
- Provide the minimal operator commands needed to confirm and repair the missing path or install.

Success Criteria:
- The root cause is stated in terms of systemd `WorkingDirectory` and executable paths.
- The response includes commands to verify the production path, clone/install if missing, and reload/restart systemd.
- No application code is changed unless the investigation shows a repo-side defect.

Status: Completed
