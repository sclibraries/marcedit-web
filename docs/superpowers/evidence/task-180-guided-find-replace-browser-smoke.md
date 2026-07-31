# TASK-180 Guided Find and Replace Browser Smoke Evidence

- Candidate implementation commit: `cc7cf4d`
- Current Docker candidate image identifier:
  `sha256:a18d1383729a5eafe4d983b9afa7fbd5c50d588961960d6aed64a950458a62fb`
- Browser URL: `http://localhost:8501`
- Service status: the isolated `task-180-marcedit-web` harness was healthy and
  `/_stcore/health` returned `ok` during the initial Task 6 attempt at
  `906781c`. The current candidate was not started for a second browser
  attempt because controller discovery reconfirmed that the required browser
  runtime remains unavailable.
- Non-production authentication method: the existing local OAuth
  configuration directory was mounted read-only. `smith.edu` was seeded only
  into this worktree's isolated test database. No production or main-worktree
  database was read or modified.
- Synthetic input intended for the walkthrough:
  `035 $aTFeba9780020306634`.
- Exact intended result:
  `035 $a(SCTFEBA)9780020306634`.
- Browser-control availability: unavailable. Two required discovery attempts
  did not expose the `node_repl js` tool needed by the in-app browser-control
  skill. The only discovered browser automation was a separate Playwright
  server, which that skill explicitly forbids as a substitute. Controller
  discovery reconfirmed the same limitation after commits `9c6dca1` and
  `cc7cf4d`.

## Acceptance Checklist

None of the following checks was performed or passed. The healthy service and
automated tests are not substitutes for browser acceptance.

1. **Unchecked:** build a guided 035 `$a` Contains operation for `TFeba`,
   matched-text replacement `(SCTFEBA)`, case-sensitive, every occurrence.
2. **Unchecked:** preview `TFeba9780020306634` and observe
   `(SCTFEBA)9780020306634`.
3. **Unchecked:** switch deliberately to whole-selected-value and verify that
   the summary names the number of previewed values to be discarded.
4. **Unchecked:** build prepend and append operations and verify that Find and
   regex controls are absent and each action occurs once per selected value.
5. **Unchecked:** target one control field and then all subfields in a
   data-field tag.
6. **Unchecked:** save raw regex `^(TFeba)(\d+)$` with replacement
   `(SCTFEBA)\2`, verify submission is blocked before preview, preview it, and
   then submit.
7. **Unchecked:** change the raw replacement after preview and verify
   submission is blocked until a new preview succeeds.
8. **Unchecked:** save and reopen, verifying target, match mode, raw strings,
   replacement scope, occurrences, case setting, and condition are unchanged.
9. **Unchecked:** import a synthetic empty-find `SUBFIELD_EDIT`, verifying it
   remains unresolved and is not saved as executable.
10. **Unchecked:** confirm that legacy Subfield Replace, Quick Find/Replace,
    and AI drafting surfaces have no new behavior.

## Unavailable Observations

- Matched values: unavailable.
- Changed values: unavailable.
- Matched occurrences: unavailable.
- Raw-regex save, submission, and staleness observations: unavailable.
- Save/reopen result: unavailable.
- Empty-find refusal result: unavailable.
- Legacy/Quick/AI characterization result in the browser: unavailable.
- Accessibility snapshot: unavailable because the required browser-control
  runtime was not exposed.
- Screenshot path: unavailable for the same reason.

## Deviations and Disposition

- Browser acceptance is incomplete. No external Playwright, Computer Use, or
  alternate browser automation was substituted.
- The three Important implementation/test findings from the initial review
  were resolved by `9c6dca1` and `cc7cf4d`; scoped re-reviews were clean.
  This does not convert any unchecked browser item into a pass.
- TASK-180 remains `In-Progress`. A cataloger must complete all ten checks
  through the approved in-app browser-control runtime (or an explicitly
  approved manual browser session), record the metrics and save/reopen
  observations, and capture an accessibility snapshot and screenshot before
  this evidence can support completion.
