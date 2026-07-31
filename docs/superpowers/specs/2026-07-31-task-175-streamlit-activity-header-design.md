# TASK-175 Streamlit Activity Header Design

**Ticket:** [TASK-175](../../../.tickets/TASK-175-streamlit-activity-header.md)

**Status:** Approved

## Purpose

The current minimal Streamlit chrome hides useful running feedback. Catalogers
can interpret quiet reruns as a stalled application. TASK-175 restores the
supported viewer-facing activity surface without exposing developer controls.

## Approach

Change `.streamlit/config.toml` from `toolbarMode = "minimal"` to
`toolbarMode = "viewer"` against the pinned Streamlit 1.50 contract. Use the
framework's native header and running indicator.

Configuration is the first and preferred implementation. Custom CSS is added
only when browser evidence demonstrates one specific unwanted control or
overlap. Any CSS selector must be narrowly tested and may not hide the complete
header, status widget, Account control, or operation notifications.

## Required Behavior

- A deliberately slow rerun visibly displays the native running indicator.
- Viewer/cataloger sessions do not expose developer, deployment, source,
  cache-clearing, or rerun controls beyond ordinary application use.
- Existing Account and operation-notification controls remain visible and do
  not overlap the header.
- Public and private modes use the same safe viewer chrome.
- Existing in-page progress and operation notifications remain unchanged.

## Failure Handling

If `viewer` exposes an unsafe control in the pinned version, implementation
stops and records browser evidence before adding CSS or choosing another
supported configuration. The task must not restore activity by enabling a
developer toolbar. A later Streamlit dependency change must rerun the contract
and browser checks.

## Testing

Configuration tests pin the intended mode. Docker preflight confirms the
pinned Streamlit version and accepted configuration. Browser acceptance covers
slow activity, idle state, desktop widths, Account/notification coexistence,
and absence of developer controls in public and private modes.

Focused and complete mounted-source Docker suites report every skip.
Independent review must find no unresolved Critical or Important issue.

## Rollout

This is an application configuration change. It does not alter systemd,
Apache, routes, working directories, workers, cron, authentication, or other
ITS-managed configuration. The normal application restart after deployment is
sufficient.
