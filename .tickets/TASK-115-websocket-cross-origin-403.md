Title: Fix production WebSocket 403 "Cross origin websockets not allowed"

Scope:
- Diagnose the wss://libtools2.smith.edu/marcedit-web/_stcore/stream handshake failure.
- Root cause (verified by replaying the browser handshake with curl): the upgrade
  passes Apache/Shibboleth/wstunnel and reaches Streamlit's Tornado server, which
  returns 403 because the forwarded Origin (https://libtools2.smith.edu) does not
  match the backend Host (127.0.0.1:8501) — Apache does not preserve the Host header.
- Fix app-side via `server.corsAllowedOrigins` (added in Streamlit 1.46.0) so the
  proxy origin is allowlisted while CORS and XSRF protection stay enabled.

Success Criteria:
- `.streamlit/config.toml` allowlists https://libtools2.smith.edu.
- After deploy + service restart, replaying the WS handshake returns
  HTTP 101 Switching Protocols instead of 403, and the app loads in the browser
  without the reconnect banner.

Status: Completed (verified 2026-07-07: handshake replay returns 101 Switching Protocols on libtools2)
