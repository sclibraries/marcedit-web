# Partner-library FOLIO task corpus

This directory preserves the `FOLIO Marc Edit Tasks` collection from:

- Repository: <https://github.com/jenmawe/marcedit>
- Source commit: `d07377a58cba9d0936a63863c9d428498609d5e5`
- Source directory: `FOLIO Marc Edit Tasks/`
- Retrieved: 2026-08-03

The 49 `.task` archives are copied verbatim. On 2026-08-03, the project user
confirmed that the partner-library author granted Smith permission to copy the
collection for compatibility review and testing.

The upstream collection is distributed under GPL-3.0. Its license is retained
as `LICENSE` in this directory. Smith Metadata Studio's root MIT license does
not relicense these third-party files.

These files are a compatibility corpus, not production task defaults and not
Smith-authored test fixtures. They may be audited with:

```bash
PYTHONPATH=. python3 scripts/audit_external_task_corpus.py \
  third_party/task-corpora/jenmawe-marcedit
```

Corpus findings may motivate synthetic focused fixtures, but importer behavior
must not infer undocumented external semantics solely from repeated use in
this collection.
