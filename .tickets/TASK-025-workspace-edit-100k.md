# TASK-025 — Workspace Edit tab usable at 100K records

**Status:** Completed
**Stage:** Post-v3 — direct user request.

## Title

Workspace's Edit tab currently shows a read-only batch-text view +
banner pointing catalogers at the View page when the batch exceeds the
5K-record cap. For a 61,830-record batch, the cataloger has to leave
the Workspace tab they're working in to make any edit. Give the Edit
tab the same per-record inline editor View grew in TASK-024, so the
Workspace workflow stays self-contained.

## Scope

- Extract the inline single-record editor + helpers from
  `marcedit_web/render/view.py` into a shared
  `marcedit_web/render/single_record_edit.py` module so both callers
  (View page, Edit tab over-cap branch) use the same code path.
  Accept a ``key_prefix`` parameter so the two callers get isolated
  session-state keys and widget keys.
- `marcedit_web/render/view.py` switches to the shared helper.
- `marcedit_web/render/edit.py`: when over the batch cap, render a
  small record-picker (number input + Prev/Next) and the inline
  editor against the picked record. Under cap, behavior is
  unchanged.

## Out of scope

- Bulk subset edit (pick record range, edit them as one .mrk text).
  Still future work if anyone asks.
- A separate cap for the picker view. The picker shows one record
  at a time regardless of batch size.

## Success Criteria

1. With a 60K-record batch loaded, the Workspace Edit tab shows a
   record-number picker + the same per-record inline editor View
   has. No "go to View page" banner.
2. The under-5K behavior of the Edit tab is unchanged — full
   batch-text editor still loads.
3. View page still works the same way (uses the shared helper).
4. `pytest -q` stays green.
5. Live verification on `sample.mrc` (7 records, under cap) AND a
   synthetic 6K-record batch (over cap).

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
```
