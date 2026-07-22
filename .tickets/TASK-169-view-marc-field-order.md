Title: Preserve canonical MARC field order in View

Scope:
- Trace how records and fields reach the View page and determine whether View
  reorders fields or exposes an upstream mutation.
- Preserve actual source order while validating it against the application's
  ascending-tag convention, including the expected placement of tag 035.
- Warn without sorting or mutating the record.

Success Criteria:
- A regression fixture containing leader, control fields, repeated fields,
  035, and surrounding data fields renders in its original order.
- View reports a bounded diagnostic when an adjacent tag inversion occurs,
  such as 040 followed by 035.
- Repeated tags do not produce a warning and valid order remains silent.
- Applicable focused tests and review pass without unresolved Critical or
  Important findings.

Status: In-Progress
