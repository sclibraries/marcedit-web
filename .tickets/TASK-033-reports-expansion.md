# TASK-033 — Reports expansion

**Status:** Completed
**Stage:** Fourth stage of MarcEdit Web v3.1.

## Title

The Report page covers format breakdown / missing-field rollup / top
tags / top 856 URL domains / per-record table. Catalogers asked for
more pre-edit audit views: what subfields are present and how often,
language distribution from 008 35–37, pub-date distribution from
008 07–10, and a "local tags (9XX)" sweep. Plus CSV export for each
report so the cataloger can drop the numbers into a spreadsheet.

## Scope

- **`render/report.py`**: extend the existing single-pass streaming
  loop with four new aggregations:
  * ``subfield_counter[(tag, code)]`` — per ``(tag, code)``
    occurrence count.
  * ``language_counter`` — 3-char code from 008 bytes 35–37.
  * ``date_counter`` — 4-char year from 008 bytes 07–10.
  * ``local_tag_counter`` — tags matching the 9XX pattern (900–999).
- Four new collapsed expanders render the aggregates so the existing
  flow (format / missing / top tags) stays visible by default:
  * **Subfield frequency** — table sorted by (tag, code).
  * **Publication date distribution** — bar chart + table.
  * **Language distribution** — table sorted by count.
  * **Local tags (9XX)** — table with tag and occurrence count.
- **CSV export** button at the foot of each section (existing +
  new). Builds a ``records_<section>_<stamp>.csv`` via
  ``converters.write_csv``.
- **Audit**: CSV downloads from Report don't emit an audit row
  (consistent with the TASK-029 rule that downloads of bytes the
  cataloger already had access to aren't security-relevant).

## Out of scope

- **Invalid URL report.** Needs either HTTP probing (slow / network)
  or a strong regex spec. Defer to a focused ticket.
- **Duplicate control numbers report.** Already lives on Dedupe;
  surfacing it here would duplicate UI without adding capability.
- **Cross-batch reports** (comparing two uploads). Diff page covers
  the pairwise case.
- **Authority-style checks** (heading consistency, name authority
  lookups). Far out of scope for v3.1.

## Success Criteria

1. With sample.mrc loaded, the Report page shows the four new
   collapsed expanders below the existing sections.
2. Opening "Subfield frequency" lists the ``(tag, code, count)``
   triples — at minimum 245$a, 245$b, 020$a appear with non-zero
   counts on the sample fixture.
3. "Publication date distribution" surfaces a year column derived
   from 008 bytes 07–10 (sample fixture has "2025").
4. "Local tags (9XX)" surfaces tags 900–999 when present (sample
   fixture uses 891, which is 8XX — shown in "Top tags" rather than
   the local 9XX expander; this is correct).
5. Each section has a working CSV download button.
6. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
```
