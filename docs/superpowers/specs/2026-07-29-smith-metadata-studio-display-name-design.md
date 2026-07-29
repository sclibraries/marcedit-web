# Smith Metadata Studio Display-Name Design

**Ticket:** [TASK-177](../../../.tickets/TASK-177-smith-metadata-studio-display-name.md)

## Decision

`Smith Metadata Studio` is the approved public product name for this release.
The change is display-only. It finalizes the working name already established
by TASK-174 without renaming any technical or deployment identifier.

## Identity Boundary

The centralized `PRODUCT_NAME` constant is the canonical public name. Browser
metadata, application headings and sidebars, README identity, and
model-facing application identity consume that value.

`Record Editor` remains the user-facing name of the record-editing page.
MarcEdit may still be named referentially when identifying supported external
task or mnemonic text formats; it is not the application's identity.

## Preserved Technical Compatibility

The following remain unchanged:

- production folder and working directory `marcedit-web`;
- production URL path `/marcedit-web/`;
- Python distribution `marcedit-web` and package `marcedit_web`;
- `MARCEDIT_WEB_*` environment variables;
- Docker image, container, Compose, and service identifiers;
- systemd units, startup commands, and deployment scripts;
- technical `MarcEditor` route and `views/5_MarcEditor.py` filename.

This rename therefore requires no ITS startup-service, filesystem, proxy, or
deployment configuration change.

## Implementation

The implementation changes the centralized product-name value and the
user-facing documentation and tests that intentionally assert its exact
interim value. Existing consumers continue to import the same constant. No
new identity abstraction or deployment compatibility layer is added.

TASK-174, TASK-176, and their historical evidence retain accurate descriptions
of the interim identity where they document completed work. Current-state
sections are updated only where leaving the interim name would misdescribe the
released application.

## Verification

TDD first demonstrates that the existing interim value fails the approved-name
contract. Verification then covers:

- exact centralized name and all current product-name consumers;
- neutral `Record Editor` labels and preserved technical routes;
- retained `marcedit-web` technical identifiers;
- focused identity/navigation/model-prompt tests;
- a rebuilt Docker image and packaged licensing artifacts;
- the complete supported test suite with all skips disclosed;
- browser acceptance of the exact page title, main heading, sidebar heading,
  upload controls, and absence of the interim public label.

Screenshot capture is attempted once through the trusted browser connector.
If the connector cannot produce it, the failure is reported and a durable
accessibility snapshot records the observed browser state.

## Merge Gate

The branch is not merged until Docker verification and independent review have
no unresolved Critical or Important findings. The merge itself does not
authorize a production deployment.
