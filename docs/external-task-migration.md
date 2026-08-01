# External task migration review

Smith Metadata Studio imports external task text through a fail-closed review
boundary. Each source line keeps its original text and SHA-256 instruction
fingerprint; source order is preserved.

## Converted

`SUBFIELD_EDIT` with a nonempty literal Find value and a one-character
subfield code converts to the guided operation. It is case-sensitive,
replaces all matched text, and preserves text before and after each match.

The two proven 008 form-of-item `REPLACE` signatures convert to **Set 008
form-of-item**. A `SORTBY` line whose scope is `ALL` converts to **Sort fields
by tag**; other sort flags remain blocking until their meaning is proven.

## Choice required

An empty Find value is never executed as Python `str.replace('', value)`. The
cataloger must choose one explicit meaning: `add_if_missing`,
`replace_existing`, or `ensure_one`. Once selected, the instruction becomes
the explicit **Imported empty-find subfield policy** operation; the review
card opens that operation in the normal task editor. Without a selection it
remains blocked.

## Unresolved

`^b`, arbitrary regex over MarcEdit's `.mrk` text, undocumented numeric flags,
`RDAHELPER`, and unknown verbs remain visible and blocking. The importer does
not claim compatibility with undocumented external behavior.
