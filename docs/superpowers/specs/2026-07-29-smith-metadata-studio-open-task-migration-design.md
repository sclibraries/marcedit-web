# Smith Metadata Studio and Open Task Migration Design

**Ticket:** [TASK-174](../../../.tickets/TASK-174-smith-metadata-studio-open-task-migration.md)

**Date:** 2026-07-29

**Status:** Approved in design discussion; awaiting review of this written specification

## Context

The application is an independently written Python and Streamlit system that
reads and writes MARC21 through the permissively licensed `pymarc` library.
It does not declare MarcEdit, MARCEngine, or another MarcEdit binary as a
dependency. However, the current `marcedit-web` name and README statement that
the application recreates MarcEdit features can imply affiliation with an
existing closed-source product.

The current task importer compounds that ambiguity. It converts a small subset
of MarcEdit task exports into generated Python. Unsupported lines become
`TODO` comments, while some accepted lines have semantics that differ from
MarcEdit. MarcEdit documents individual editing functions but does not publish
a complete specification for every field and flag in its exported task format.
Universal compatibility therefore cannot be verified safely.

The product will become **Smith Metadata Studio**, subject to Smith's formal
name review. It will be positioned as an independent, open metadata workflow
and MARC21 transformation platform. MarcEdit task support will become an
optional migration adapter, not the application's identity or native execution
model.

The supplied `MarcEdit Tasks` folder is the initial compatibility corpus. The
read-only inventory found 10 distinct task definitions after deduplication,
containing 165 operations and 10 operation types. The corpus is a concrete
starting contract, not evidence of complete MarcEdit compatibility.

## Goals

1. Give the application an independent, reusable, open-source identity.
2. Retain and improve the existing Tasks form rather than build a second task
   editor.
3. Make common task authoring accessible to staff without a cataloging
   background while retaining precise MARC controls for catalogers.
4. Define a versioned, documented, non-executable native task format.
5. Convert supported legacy task instructions into native operations through
   a fail-closed, reviewable migration flow.
6. Use Smith CORE Holdings and Items as the first end-to-end migration fixture.
7. Remove cataloger-facing JSON, raw template, and generated-code requirements
   from normal task authoring.
8. Restore useful Streamlit header activity feedback.
9. Preserve production startup compatibility until a single consolidated ITS
   change can be applied safely.

## Non-goals

- Claiming universal MarcEdit task compatibility.
- Executing imported MarcEdit instructions directly.
- Guessing undocumented MarcEdit Boolean, numeric, pipe-delimited, or bitmask
  options.
- Redistributing MarcEdit binaries, libraries, logos, source, or documentation.
- Replacing the current sandbox and durable-operation execution path in this
  project.
- Making raw Python part of the portable task standard.
- Publishing the supplied institutional task corpus without a privacy,
  attribution, and workflow-content review.
- Removing legacy technical aliases during the initial rebrand.

## Product Identity and Licensing Boundary

Smith Metadata Studio is the working product name. An initial exact-name search
did not find an obvious exact conflict, but "Metadata Studio" is used by
unrelated products. Smith must complete its normal name and trademark review
before public launch.

Open-source readiness requires:

- an actual MIT `LICENSE` file in addition to the current `pyproject.toml`
  declaration;
- third-party notices for distributed dependencies, including `pymarc`;
- removal of statements that the application recreates MarcEdit;
- an explicit statement that Smith Metadata Studio is independent and is not
  affiliated with or endorsed by MarcEdit or its author;
- use of "MarcEdit" only to identify the source format handled by the optional
  migration adapter; and
- review and sanitization of institutional task fixtures before publication.

This is a technical product boundary, not a legal opinion. Smith should route
the final public name, disclaimer, and release language through its normal
institutional review.

Relevant public references:

- [MarcEdit End User License Agreement](https://marcedit.reeset.net/marcedit-end-user-license-agreement)
- [USPTO: common-law trademark rights](https://www.uspto.gov/trademarks/basics/why-register-your-trademark)
- [USPTO: likelihood of confusion](https://www.uspto.gov/trademarks/search/likelihood-confusion)
- [Library of Congress MARC21 record structure](https://www.loc.gov/marc/specifications/specrecstruc)
- [pymarc project information](https://pypi.org/project/pymarc/)

## Architecture and Boundaries

The existing Tasks form remains the single task editor. Users can reach the
same ordered native operation model through:

1. a guided recipe;
2. a blank task; or
3. import and migration of an external task.

The migration path is:

```text
external task file
        |
        v
safe archive/file parser
        |
        v
line classification and proposed native operations
        |
        v
blocked review draft
        |
        v
cataloger confirmation and correction
        |
        v
native Smith Metadata Studio task
        |
        v
sample MARC preview
        |
        v
save and run through the existing durable sandbox path
```

Imported instructions are never executable inputs. Each source line retains
its original text for provenance and receives a review status. The current
deterministic operation-to-Python compiler may remain temporarily as an
internal execution artifact. The portable task definition contains no Python.

Admin-only Custom Python remains a local legacy extension. It is not part of
the open task schema and cannot be exported as a portable native task.

## Native Task Format

The canonical open task format is versioned JSON validated against a published
JSON Schema. JSON is an interchange and storage format, not a cataloger-facing
editor. The normal UI always renders structured controls and MARC previews.

A native task contains:

- schema version;
- name and description;
- applicable metadata/MARC profile;
- ordered, stable step identifiers;
- explicit operation names and parameters; and
- optional source provenance.

It contains no executable source code, hidden positional flags, or unresolved
review state. A Build Field step equivalent to the corpus's 876 instruction is
conceptually represented as:

```json
{
  "schema_version": 1,
  "name": "smith-core-holdings-and-items",
  "description": "Core changes to 852, 856, 876, and 877",
  "profile": "marc21",
  "steps": [
    {
      "id": "step-7",
      "action": "build_field",
      "target": {
        "tag": "876",
        "indicators": [" ", " "]
      },
      "subfields": [
        {
          "code": "a",
          "segments": [
            {"type": "text", "value": "B("},
            {"type": "control_field", "tag": "003"},
            {"type": "text", "value": ")"},
            {"type": "control_field", "tag": "001"},
            {"type": "text", "value": "-SC"}
          ]
        },
        {
          "code": "l",
          "segments": [
            {"type": "text", "value": "Internet"}
          ]
        }
      ],
      "missing_source": "skip_and_report",
      "existing_target": "append"
    }
  ],
  "provenance": {
    "source_format": "marcedit-task"
  }
}
```

The choices `missing_source` and `existing_target` are explicit native
semantics. They are not inferred from undocumented trailing flags.

### Storage transition

The current `tasks` table stores Python `body` and `extra_imports` text. The
native transition will add a nullable, versioned definition field rather than
silently rewrite existing rows:

- new native tasks store the structured definition as the canonical value;
- generated body/imports may be retained as a compatibility execution
  snapshot while the current loader remains in service;
- form-built tasks with valid `# OP:` markers can be offered an explicit
  migration;
- legacy raw-Python tasks remain available and clearly labeled legacy; and
- no existing task is rewritten during deployment without user action.

## Migration Review Model

Every imported source instruction receives exactly one state:

| State | Meaning | Runnable |
| --- | --- | --- |
| Converted | Behavior is understood and fully represented natively. | Yes |
| Needs confirmation | The operation is understood, but at least one option is ambiguous. | No |
| Unsupported | No proven native representation exists. | No |
| Invalid | The instruction is malformed, such as an invalid regex. | No |

An unresolved import may be saved as a **draft**, but it cannot be promoted to
a runnable task. The review screen shows:

- task-level status counts;
- one card per source instruction;
- a plain-language explanation;
- the proposed native operation form;
- the original source line, collapsed by default;
- exact unresolved questions;
- Confirm, Edit, and Remove actions; and
- filters for steps needing attention.

Removing an imported instruction is an explicit reviewed action and remains in
the migration audit. No line silently disappears.

## Initial Compatibility Corpus

The supplied task folder is inventoried deterministically by content hash.
Duplicate archive/plain-text copies do not create duplicate compatibility
requirements. Every unique instruction signature receives a support record
containing:

- source task and line number;
- parsed verb and arguments;
- proposed native action;
- support state;
- documentation or fixture supporting the interpretation; and
- tests that establish the native behavior.

The compatibility statement is limited to the observed and tested signatures:

> Smith Metadata Studio supports the task signatures identified in the
> published compatibility matrix. It does not claim complete MarcEdit task
> compatibility.

## First End-to-End Migration: Smith CORE Holdings and Items

Smith CORE Holdings and Items is the vertical slice because it exercises the
most important migration behavior in one ordered workflow:

1. add an 852;
2. temporarily retag selected 856 fields as 956;
3. prepend a proxy URL to the remaining 856$u values;
4. add or replace 856$y link text;
5. restore 956 fields to 856;
6. build an 876 from 003 and 001;
7. delete 001, 003, and existing 877 fields;
8. add an 877 value according to Leader conditions; and
9. sort the resulting fields.

Proposed translations are reviewed individually:

| Legacy instruction | Native interpretation |
| --- | --- |
| `ADD 852 ...` | Add an 852 using visible indicators and subfield rows. |
| Regex `856` to `956` replacement | Retag matching 856 fields using explicit indicator conditions. |
| `SUBFIELD_EDIT 856 u ^b ...` | Prepend the proxy URL to 856$u. |
| Empty-find `SUBFIELD_EDIT 856 y` | Ask whether to add missing `$y`, replace existing `$y`, or both. |
| `REPLACE =956 ... =856 ...` | Retag 956 fields back to 856. |
| `buildnewfield =876 ...` | Build an 876 from literal and source-field segments. |
| `DELETE 001`, `003`, `877` | Remove the named fields. |
| Conditional `ADD 877` | Add 877 through readable Leader-position conditions. |
| `SORTBY ALL` | Sort fields by tag under the native field-order policy. |

For this source record:

```marc
=001  TFeba9780020306634
=003  NhCcYBP
```

the proven portion of the Build Field template produces:

```marc
=876  \\$aB(NhCcYBP)TFeba9780020306634-SC$lInternet
```

The later deletion of 001 and 003 makes operation order material and therefore
part of the native compatibility tests.

## Existing Task Form Improvements

The current ordered operation editor remains recognizable. New Task offers:

- **Use a guided recipe**
- **Start with a blank task**
- **Import and migrate an external task**

All routes populate the same ordered operation list.

Each operation card presents:

- a plain-language title rather than the internal operation slug;
- a concise behavior summary;
- field names alongside MARC tags;
- subfield names or local definitions alongside codes;
- a live MARC preview;
- expandable advanced options;
- move, duplicate, and remove controls; and
- a generated plain-language statement of the effective operation.

### Subfield entry

The current JSON text area for subfields is removed from normal authoring.
An Add Field operation uses repeatable rows:

| Field | Value |
| --- | --- |
| Tag | `877 — Item Information: Supplementary Material` |
| Indicator 1 | Blank |
| Indicator 2 | Blank |
| Subfield code | `m` |
| Subfield value | `Map` |

The UI includes **Add another subfield** and live preview:

```marc
=877  \\$mMap
```

The JSON representation remains internal and exportable.

### Build Field entry

Raw templates such as
`=876  \\$aB({003}){001}-SC$lInternet` become visible segments:

- text `B(`;
- value from control field 003;
- text `)`;
- value from control field 001;
- text `-SC`; and
- subfield `$l` with text `Internet`.

The editor requires explicit choices for missing source data and existing
target fields.

### Find and Replace family

The UI presents related native operations through one Find and Replace family
with layered controls:

- scope: record, field range, field, complete field value, or subfield;
- matching: plain text or regex;
- case sensitivity;
- first or every occurrence;
- replacement behavior: matched text only, whole subfield, whole field,
  prepend, or append;
- optional indicator and record conditions; and
- before/after MARC preview.

Regex is hidden until requested and validated while editing. The default
matched-text behavior preserves data on both sides of the match.

### Recipes

Recipes are presets that create ordinary native operations. They do not create
a second task type. Initial recipes should be derived from repeated,
cataloger-reviewed corpus patterns such as:

- replace text while preserving surrounding data;
- add proxy information to selected 856 fields;
- build an 876 from 001 and 003;
- add 877 values from Leader conditions; and
- remove known vendor fields.

Quick Find/Replace can offer **Add to task** after preview so one-time work can
become a reusable native step.

## Validation and Failure Handling

Task import, authoring, and execution fail closed:

- every source line has a line number and state;
- archive safety and size limits are enforced before parsing;
- unknown operations remain visible and blocking;
- unknown option combinations become explicit confirmation questions;
- required form parameters are enforced before save;
- invalid regex errors appear beside the affected control;
- no runnable task contains `TODO` output;
- no unknown operation is rendered as a no-op;
- source lines never execute directly; and
- operation order is preserved exactly.

Missing source fields and existing target fields use explicit native policies.
Skip, replace, append, and error behavior is counted and reported. No default
is inferred from an undocumented legacy flag.

## Preview and Execution

A fully resolved draft must be tested against a loaded sample before it becomes
runnable. Preview uses a temporary candidate and does not mutate the source.
It reports:

- records examined, changed, and unchanged;
- per-step match and change counts;
- skipped records and reasons;
- per-record MARC before/after differences;
- validation warnings introduced or resolved; and
- field-order warnings or changes.

If the loaded file or draft changes after preview, the preview is invalidated.
Application continues through the existing versioning, recovery, durable
operation, and sandbox boundaries.

## Shared Task Authorization Conflict

Current main documentation says shared tasks are editable only by their owner.
The approved production hotfix work is intended to allow other authorized
catalogers to correct shared tasks. TASK-174 must not silently choose between
these contradictory states.

Before implementation touches shared-task controls, the hotfix branch must be
integrated or its final authorization contract recorded. Code, help text,
tests, and the native task migration must then follow that one proven policy.

## Streamlit Activity Feedback

The Streamlit framework header/status area is restored so users see the
running animation during reruns and operations that otherwise leave the page
quiet.

The current `[client] toolbarMode = "minimal"` setting was intended to suppress
developer controls. The first tested configuration is `viewer`, which
Streamlit documents as hiding developer options from viewers. The choice is
verified in the project's pinned Streamlit version inside Docker.

Acceptance requirements:

- a deliberately slow rerun shows the framework running indicator;
- developer and deployment controls remain unavailable to catalogers;
- Account and operation-notification controls do not overlap the header;
- public and private modes behave consistently;
- existing in-page progress remains available; and
- if configuration alone is insufficient, styling hides only proven unwanted
  controls rather than the complete header.

Reference:
[Streamlit app chrome](https://docs.streamlit.io/develop/concepts/architecture/app-chrome).

## Verification Strategy

### Deterministic corpus checks

- Deduplicate supplied task definitions by content hash.
- Assert that every line in every unique task receives one classification.
- Emit a machine-readable compatibility report.
- Fail tests if a source line disappears or has an unrecognized state.

### Operation tests

- Use synthetic MARC records to test each supported signature.
- Encode why the behavior matters, including matched-text preservation,
  operation ordering, missing-source policy, repeatable fields, indicators,
  and conditional adds.
- Test valid and invalid regex paths.
- Test structured subfield and Build Field round trips.

### End-to-end tests

- Migrate Smith CORE Holdings and Items into a blocked draft.
- Resolve each known confirmation through native choices.
- Preview the complete task against representative MARC fixtures.
- Assert exact expected MARC output, counts, warnings, and preserved data.
- Require cataloger review of ambiguous workflow fixtures before marking those
  signatures fully compatible.

### Compatibility and regression tests

- Validate native JSON against schema version 1.
- Export and re-import native tasks without changing step order or values.
- Keep existing form-built tasks runnable.
- Keep raw-Python tasks available and clearly legacy.
- Verify shared-task authorization against the integrated hotfix contract.
- Verify the Streamlit running indicator and hidden developer controls in
  Docker browser testing.
- Run the full suite with every skip reported.

The isolated TASK-174 baseline is 1,573 passed and 4 skipped. All four skips
are the Docker Compose rendering tests, skipped because the network-disabled
test container does not contain the Docker CLI. The initial Compose attempt
could not allocate a new Docker network because the local predefined address
pool is exhausted; the successful baseline used the existing development image
with `--network none`.

## Rebrand and Production Rollout

The rebrand is staged so current ITS-managed startup remains valid:

1. Add the new user-facing identity, documentation, license material, native
   task model, and new entry points on main.
2. Retain existing `marcedit_web` modules, environment variables, paths, and
   service entry points as compatibility aliases.
3. Prove that the current production unit can start the new code unchanged.
4. Prepare and test `/smith-metadata-studio/` routing locally.
5. Give ITS one consolidated request for the new route and any desired service
   unit changes.
6. Keep `/marcedit-web/` as a temporary redirect or compatibility route.
7. Remove legacy technical aliases only in a separately approved later release.

ITS applying its portion before the application deployment must fail safely:
main will contain the referenced new entry points before the request is made,
and existing entry points will remain valid throughout the transition.

## Implementation Decomposition

TASK-174 is a program-level design and must be implemented through bounded
child tickets after the written specification and plan are approved. The
recommended order is:

1. licensing, public identity, and backwards-compatible naming;
2. native task schema and storage compatibility;
3. existing-form field, subfield, Build Field, and Find/Replace improvements;
4. import review state model and compatibility report;
5. Smith CORE Holdings and Items vertical-slice migration;
6. remaining corpus signatures and recipes;
7. task preview promotion gate;
8. Streamlit activity-header restoration and browser verification; and
9. consolidated production/ITS migration envelope.

Each child ticket must have independent success criteria, TDD evidence, and
review. No child may broaden MarcEdit compatibility beyond a documented,
tested signature.

## Success Criteria

The design is successfully implemented when:

- the application presents itself as Smith Metadata Studio with reviewed
  independent-product language;
- repository licensing and third-party notices are complete;
- native tasks have a documented, versioned, non-executable schema;
- the existing form supports guided, blank, and migration entry paths;
- catalogers never need to author JSON or raw Build Field templates;
- every unique supplied task instruction is classified;
- Smith CORE Holdings and Items migrates through a fully reviewed native draft
  and passes exact end-to-end MARC fixtures;
- unresolved imported behavior cannot run;
- native task preview shows step and record outcomes before promotion;
- legacy tasks remain available without silent rewriting;
- the Streamlit activity indicator is restored without developer controls;
- the current production startup path remains valid until the consolidated ITS
  change; and
- all applicable tests pass with every skip reported and code review has no
  unresolved Critical or Important findings.
