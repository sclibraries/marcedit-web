Title: FOLIO rule profiles with safe assisted fixes

Scope:
- Design a configurable FOLIO option for catalogers working with MARC records.
- Support rule profiles for common FOLIO workflows, including new Instance/SRS loads and round-tripping existing Instance/SRS records.
- Capture user-adjustable standards for required, forbidden, and recommended fields/subfields/indicators/fixed-field values.
- Include safe assisted fixes that can be applied either per record from Validate or in batch after preview.
- Keep the initial implementation scoped to local validation guidance and deterministic fix operations; direct FOLIO API integration is out of scope unless added later.

Success Criteria:
- A reviewed design explains how FOLIO rule profiles fit into the existing Streamlit application.
- The design covers rule storage, validation behavior, UI entry points, per-record safe fixes, batch safe-fix preview/application, and tests.
- Any later implementation is test-driven and can be traced back to this ticket.

Status: In-Progress
