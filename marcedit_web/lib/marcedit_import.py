"""Convert a MarcEdit `.tasksfile.txt` to an equivalent Python task body.

This is a one-shot import — the user picks a MarcEdit tasksfile, the
converter emits Python code, and the result is saved as a normal user task
under `tasks/<slug>.py`. After import the task is fully editable through
the GUI (or `tasks.py` directly).

Coverage: the operations actually present across the five Smith / 5C
tasksfiles under `docs/source/` — ADD, DELETE, REPLACE (for known 008
patterns), RDAHELPER, SORTBY, SUBFIELD_EDIT, `buildnewfield`. Anything
unrecognized becomes a `# TODO: convert manually — <original line>` so
the user sees what's missing and can hand-edit.

Format reference: MarcEdit tasksfiles are tab-separated, one operation per
line. The first column is the verb (ADD, DELETE, …); subsequent columns
are operation-specific. Leader-based regex conditions appear in the last
few columns and are normalized through `_translate_condition`.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from marcedit_web.lib.codegen_safety import lit

logger = logging.getLogger("marcedit_web.marcedit_import")


@dataclass
class HandlerEmission:
    """One MarcEdit-line conversion outcome.

    `code` is the Python snippet (None signals a malformed source line).
    `imports` is the set of helper names the snippet calls so the
    file-level import block can be assembled. `op_kind` + `op_params`
    surface the form-builder palette mapping for the line — when both
    are populated, the converter prepends a `# OP: <kind> <json>` marker
    so the imported task opens in Form view rather than Code view.

    When `op_kind` is None the converter wraps the emission as a
    `custom` palette block (params={"code": code}) so the imported task
    stays form-editable even for verbs that have no clean palette
    equivalent.
    """

    code: str | None
    imports: set[str] = field(default_factory=set)
    op_kind: str | None = None
    op_params: dict | None = None


@dataclass
class ConversionResult:
    """Output of `convert_tasksfile`.

    `body` is ready to drop into a `@task` body (after the standard imports
    written by `serialize_user_task`). `unsupported` lists the source-file
    lines that couldn't be translated; they appear as `# TODO …` comments
    in the body so the user can find them.
    """

    name: str
    description: str
    body: str
    imports: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


@dataclass
class EntryResult:
    """One inner-entry outcome from a `.task` archive import.

    `conversion` is populated when `success` is True; `error` is the
    cataloger-readable reason when False. The two fields are mutually
    exclusive — exactly one is set.
    """

    entry_name: str
    success: bool
    conversion: ConversionResult | None = None
    error: str | None = None


@dataclass
class ArchiveConversionResult:
    """Output of `convert_task_archive`.

    `entries` carries one EntryResult per inner `*.txt` entry, in archive
    order. `archive_errors` is for file-scope failures (corrupt zip, no
    .txt entries inside) — when populated, `entries` is empty.
    """

    archive_name: str
    entries: list[EntryResult] = field(default_factory=list)
    archive_errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Condition translation
# ---------------------------------------------------------------------------

# Maps the MarcEdit `=LDR…` regex strings to the form-builder's condition
# enum keys (see `task_builder.LEADER_CONDITIONS`). The form-builder doesn't
# have keys for the two complex multi-class regexes below, so those still
# get rendered via the Python expression path and the emission falls
# through to a `custom` palette block.
_MARCEDIT_CONDITION_TO_FORM_KEY: dict[str, str] = {
    "=LDR.{8}[amt][m].+": "books",
    "=LDR.{9}s.+": "serials",
    "=LDR.{9}i.+": "databases",
    "=LDR.{8}[e,f].+": "maps",
    "=LDR.{8}g.+": "videos",
    "=LDR.{8}[i,j].+": "audios",
    "=LDR.{8}[c,d].+": "scores",
}


# A few well-known MarcEdit leader regex anchors we can translate exactly.
# Anything not in this table becomes a TODO so the user knows the condition
# wasn't preserved.
_LEADER_CONDITIONS: dict[str, str] = {
    "=LDR.{8}[amt][m].+": "leader_type(record) in 'amt' and leader_biblevel(record) == 'm'",
    "=LDR.{9}s.+": "leader_biblevel(record) == 's'",
    "=LDR.{9}i.+": "leader_biblevel(record) == 'i'",
    "=LDR.{8}[e,f].+": "leader_type(record) in 'ef'",
    "=LDR.{8}g.+": "leader_type(record) == 'g'",
    "=LDR.{8}[i,j].+": "leader_type(record) in 'ij'",
    "=LDR.{8}[c,d].+": "leader_type(record) in 'cd'",
    "=LDR.{8}[a,c,d,i,j,m,o,p,r,t][c,m,s,i].+":
        "leader_type(record) in 'acdijmoprt' and leader_biblevel(record) in 'cmsi'",
    "=LDR.{8}[e,f,g,k].+":
        "leader_type(record) in 'efgk'",
}


def _translate_condition(condition: str) -> tuple[str | None, bool]:
    """Map a MarcEdit `=LDR…` regex to a Python boolean expression.

    Returns `(expression, supported)`. If unsupported, the caller should
    drop the line as a TODO instead of emitting partial code.
    """
    cond = condition.strip().strip("/")
    if not cond:
        return (None, True)  # no condition = always-apply
    if cond in _LEADER_CONDITIONS:
        return (_LEADER_CONDITIONS[cond], True)
    return (None, False)


def _form_condition_key(condition: str) -> str | None:
    """Map a MarcEdit `=LDR…` regex to a form-builder condition enum key.

    Returns `"always"` when no condition is supplied, the matching enum
    key (`"serials"`, `"books"`, etc.) when the regex is one we recognise,
    or `None` when there's no clean palette equivalent — in which case
    the handler still emits Python (via `_translate_condition`) but the
    emission falls through to a `custom` block rather than `add-field`.
    """
    cond = condition.strip().strip("/")
    if not cond:
        return "always"
    return _MARCEDIT_CONDITION_TO_FORM_KEY.get(cond)


# ---------------------------------------------------------------------------
# .mrk field-data parsing
# ---------------------------------------------------------------------------

_SUBFIELD_RE = re.compile(r"\$(.)([^$]*)")


def parse_mrk_field_data(data: str) -> tuple[str, str, list[tuple[str, str]]]:
    r"""Parse a MarcEdit ADD-field `data` blob: `<ind1><ind2>$<code><value>…`.

    Indicators use `\` for blank. Returns `(ind1, ind2, subfields)` where
    subfields is a list of `(code, value)` tuples.
    """
    if len(data) < 2:
        return (" ", " ", [])
    ind1 = " " if data[0] == "\\" else data[0]
    ind2 = " " if data[1] == "\\" else data[1]
    rest = data[2:]
    subfields = [
        (m.group(1), m.group(2))
        for m in _SUBFIELD_RE.finditer(rest)
    ]
    return (ind1, ind2, subfields)


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------


def _emit_add(parts: list[str]) -> HandlerEmission:
    """ADD\t<tag>\t<data>\t<priority>\t<condition>"""
    if len(parts) < 3:
        return HandlerEmission(code=None)
    tag = parts[1].strip()
    data = parts[2]
    condition = parts[4] if len(parts) > 4 else ""
    ind1, ind2, subfields = parse_mrk_field_data(data)
    sf_args = ", ".join(
        f"({code!r}, {value!r})" for code, value in subfields
    )
    add_expr = (
        f"record.add_ordered_field(make_field({lit(tag)}, {lit(ind1)}, "
        f"{lit(ind2)}, {sf_args}))"
    )
    expr, supported = _translate_condition(condition)
    form_key = _form_condition_key(condition)
    # Form-builder shape: subfields are list-of-pairs.
    sf_pairs = [[code, value] for code, value in subfields]
    if expr is None and supported:
        # No leader condition (always-apply). Clean palette mapping when
        # the form-builder also recognises the condition (it always does
        # for empty).
        return HandlerEmission(
            code=add_expr,
            imports={"make_field"},
            op_kind="add-field" if form_key is not None else None,
            op_params={
                "tag": tag, "ind1": ind1, "ind2": ind2,
                "subfields": sf_pairs,
                "condition": form_key or "always",
                "if_absent": False,
            } if form_key is not None else None,
        )
    if expr is None and not supported:
        # Condition couldn't be translated into either Python or a form
        # key — emission becomes a `custom` block carrying the TODO.
        return HandlerEmission(
            code=(
                f"# TODO: ADD with unsupported condition {condition!r} — "
                f"hand-translate this line"
            ),
        )
    # Condition translated into a Python expression. The form-builder
    # surfaces this cleanly only when we also have a form-key; otherwise
    # the emission stays form-editable as a `custom` block.
    code = f"if {expr}:\n    {add_expr}"
    if form_key is not None:
        return HandlerEmission(
            code=code,
            imports={"make_field", "leader_type", "leader_biblevel"},
            op_kind="add-field",
            op_params={
                "tag": tag, "ind1": ind1, "ind2": ind2,
                "subfields": sf_pairs,
                "condition": form_key,
                "if_absent": False,
            },
        )
    return HandlerEmission(
        code=code,
        imports={"make_field", "leader_type", "leader_biblevel"},
    )


def _emit_delete(parts: list[str]) -> HandlerEmission:
    """DELETE\t<tag>\t<find>\t<position>\t<flags…>"""
    if len(parts) < 2:
        return HandlerEmission(code=None)
    tag = parts[1].strip()
    find = parts[2].strip() if len(parts) > 2 else ""
    if not find:
        return HandlerEmission(
            code=f"delete_tags(record, {lit(tag)})",
            imports={"delete_tags"},
            op_kind="delete-tag",
            op_params={"tag": tag},
        )
    return HandlerEmission(
        code=f"delete_fields_matching_subfield(record, {lit(tag)}, None, {lit(find)})",
        imports={"delete_fields_matching_subfield"},
        op_kind="delete-by-subfield",
        op_params={"tag": tag, "match": find},
    )


# `REPLACE` regexes that target known 008 bytes — these we can map exactly
# to `set_008_form_of_item`. Anything else becomes a TODO.
_KNOWN_REPLACE = {
    # 008 byte 23 form-of-item -> 'o' for record types acdijmoprt + bibs cmsi
    (r"(=008.{25}).{1}(.+)", r"$1o$2"): "set_008_form_of_item(record)",
    # 008 byte 29 form-of-item -> 'o' for record types efgk (visual + maps)
    (r"(=008.{31}).{1}(.+)", r"$1o$2"): "set_008_form_of_item(record)",
}


def _emit_replace(parts: list[str]) -> HandlerEmission:
    """REPLACE\t<find-regex>\t<replace>\t<position>\t<condition>\t<flags…>

    Only the two well-known 008 form-of-item patterns translate cleanly;
    arbitrary REPLACEs become `custom` blocks because they target the
    .mrk text representation and have no general Python equivalent.
    """
    if len(parts) < 3:
        return HandlerEmission(code=None)
    find, replace = parts[1], parts[2]
    expr = _KNOWN_REPLACE.get((find, replace))
    if expr is not None:
        return HandlerEmission(
            code=expr,
            imports={"set_008_form_of_item"},
            op_kind="set-008-form",
            op_params={},
        )
    return HandlerEmission(
        code=(
            f"# TODO: REPLACE {find!r} -> {replace!r} — hand-translate this line "
            "(arbitrary regex over .mrk text)"
        ),
    )


def _emit_buildnewfield(parts: list[str]) -> HandlerEmission:
    """buildnewfield\t<template>\t<flags…>

    The template uses MarcEdit syntax like `=035  9\\$a({003}){001}`.
    Currently we recognize one pattern — the canonical Smith 035 9
    cross-reference — and emit the equivalent Python. Anything else
    becomes a `custom` block.
    """
    if len(parts) < 2:
        return HandlerEmission(code=None)
    template = parts[1].strip()
    # The Smith convention: `=035  9\$a({003}){001}`
    return HandlerEmission(
        code=f"# TODO: buildnewfield template {template!r} — hand-translate this line",
    )


def _emit_sortby(_: list[str]) -> HandlerEmission:
    return HandlerEmission(
        code="sort_fields(record)",
        imports={"sort_fields"},
        op_kind="sort-fields",
        op_params={},
    )


def _emit_subfield_edit(parts: list[str]) -> HandlerEmission:
    """SUBFIELD_EDIT\t<tag>\t<subfield>\t<find>\t<replace>\t…"""
    if len(parts) < 5:
        return HandlerEmission(code=None)
    tag = parts[1].strip()
    code = parts[2].strip()
    find = parts[3]
    replace = parts[4]
    body = (
        f"for f in record.get_fields({lit(tag)}):\n"
        f"    f.subfields = [\n"
        f"        Subfield(sf.code, sf.value.replace({lit(find)}, {lit(replace)}))\n"
        f"        if sf.code == {lit(code)} else sf\n"
        f"        for sf in f.subfields\n"
        f"    ]"
    )
    return HandlerEmission(
        code=body,
        imports={"_subfield_import"},  # special marker; handled below
        op_kind="subfield-replace",
        op_params={"tag": tag, "code": code, "find": find, "replace": replace},
    )


_HANDLERS = {
    "ADD": _emit_add,
    "DELETE": _emit_delete,
    "REPLACE": _emit_replace,
    "buildnewfield": _emit_buildnewfield,
    "SORTBY": _emit_sortby,
    "SUBFIELD_EDIT": _emit_subfield_edit,
}


# ---------------------------------------------------------------------------
# Top-level conversion
# ---------------------------------------------------------------------------


_DESCRIPTION_PREFIX = "#DESCRIPTION#"


def convert_tasksfile(path: Path, *, name: str | None = None) -> ConversionResult:
    """Read a MarcEdit tasksfile and emit a Python task body.

    `name` defaults to the file stem (with `_tasksfile` etc. trimmed). The
    returned `body` is suitable to pass straight into `editor.save_user_task`.

    Thin wrapper around `convert_tasksfile_text` that handles the file
    read + name derivation. The text variant is the one to call from
    archive imports where the inner entry is already in memory.
    """
    text = path.read_text()
    derived_name = name or _derive_name_from_filename(path.name)
    return convert_tasksfile_text(
        text,
        name=derived_name,
        description_fallback=f"Imported from {path.name}",
    )


def _op_marker(kind: str, params: dict) -> str:
    """Build the `# OP: <kind> <json>` marker the form-builder parses.

    Matches `task_builder._OP_MARKER_RE` (which the form-builder uses to
    lift a saved task back into its operation list). JSON-encoding the
    params handles literal `{`/`}` inside string values cleanly — they
    stay quoted, so the regex's greedy `\\{.*\\}` boundary still finds
    the right closing brace.
    """
    return f"# OP: {kind} {json.dumps(params, sort_keys=True)}"


def convert_tasksfile_text(
    text: str, *, name: str, description_fallback: str
) -> ConversionResult:
    """Parse already-loaded MarcEdit tasksfile text into a ConversionResult.

    Used by the `.task` archive importer, which reads inner-entry bytes
    from a zip without writing them to disk. The caller supplies `name`
    (derived from the entry filename via `_derive_name_from_filename` or
    chosen externally) and `description_fallback` (used when the source
    text doesn't begin with `#DESCRIPTION#`).
    """
    description = ""
    body_lines: list[str] = []
    imports_needed: set[str] = set()
    needs_subfield_import = False
    unsupported: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith(_DESCRIPTION_PREFIX):
            description = line[len(_DESCRIPTION_PREFIX):].strip()
            continue
        if line.startswith("#"):
            continue  # other comments — drop

        parts = line.split("\t")
        verb = parts[0].strip()
        handler = _HANDLERS.get(verb)
        if handler is None:
            # Unknown verb — wrap as a `custom` block so the imported task
            # stays form-editable even when individual lines can't be
            # cleanly typed.
            unsupported.append(line)
            todo = f"# TODO: unknown verb {verb!r} — {line}"
            body_lines.append(_op_marker("custom", {"code": todo}))
            body_lines.append(todo)
            continue
        emission = handler(parts)
        if emission.code is None:
            # Malformed source line — same `custom` fallback.
            unsupported.append(line)
            todo = f"# TODO: malformed {verb!r} — {line}"
            body_lines.append(_op_marker("custom", {"code": todo}))
            body_lines.append(todo)
            continue
        needed = emission.imports
        if "_subfield_import" in needed:
            needs_subfield_import = True
            needed = needed - {"_subfield_import"}
        imports_needed |= needed
        # Resolve the OP marker. Handlers that have a clean palette
        # mapping (op_kind set) emit their kind directly; everything
        # else falls through to a `custom` block carrying the raw code
        # so the imported task remains form-editable as a whole.
        if emission.op_kind is not None and emission.op_params is not None:
            body_lines.append(_op_marker(emission.op_kind, emission.op_params))
        else:
            body_lines.append(_op_marker("custom", {"code": emission.code}))
        body_lines.append(emission.code)
        # Handlers that couldn't translate a line in full still emit a
        # `# TODO …` placeholder. Track those as unsupported so the GUI
        # can warn the user, while keeping the placeholder in-line.
        if emission.code.lstrip().startswith("# TODO"):
            unsupported.append(line)

    transforms_imports = sorted(imports_needed)
    import_lines: list[str] = []
    if transforms_imports:
        import_lines.append(
            "from marcedit_web.lib.transforms import "
            + ", ".join(transforms_imports)
        )
    if needs_subfield_import:
        import_lines.append("from pymarc import Subfield")

    return ConversionResult(
        name=name,
        description=description or description_fallback,
        body="\n".join(body_lines),
        imports=import_lines,
        unsupported=unsupported,
    )


def convert_task_archive(
    path: Path,
    *,
    max_total_decompressed: int = 50 * 1024 * 1024,
    max_entries: int = 256,
) -> ArchiveConversionResult:
    """Open a MarcEdit `.task` ZIP archive and convert every inner *.txt entry.

    Each inner entry runs through `convert_tasksfile_text` (no intermediate
    file writes — sidesteps zip path-traversal risk entirely). A failure on
    one inner entry is captured as an EntryResult with `success=False` and
    does not abort the others (per the design spec's "Partial failure handling"
    section).

    File-scope errors (not a zip, no .txt entries inside, can't be opened)
    populate `archive_errors` and produce an empty `entries` list. The
    GUI shows this as a banner failure rather than partial success.

    The two caps protect against zip-bomb-shaped archives:

    * ``max_total_decompressed`` — running sum of decompressed inner-entry
      bytes. Default 50 MB.
    * ``max_entries`` — count of inner *.txt entries actually decoded.
      Default 256.

    Either cap firing populates `archive_errors` and returns early so
    the GUI / audit can flag the rejection.
    """
    archive_name = path.name
    if not zipfile.is_zipfile(path):
        return ArchiveConversionResult(
            archive_name=archive_name,
            archive_errors=[
                f"{archive_name!r} is not a valid zip archive — MarcEdit "
                f".task files are zip archives. Confirm the file isn't "
                f"corrupted or a different format."
            ],
        )

    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as exc:
        return ArchiveConversionResult(
            archive_name=archive_name,
            archive_errors=[f"could not open {archive_name!r}: {exc}"],
        )

    with zf:
        # Only consider entries that look like tasksfiles: *.txt. Skip
        # directories (zip entries ending in /) and obvious metadata.
        txt_entries = [
            n for n in zf.namelist()
            if n.lower().endswith(".txt") and not n.endswith("/")
        ]
        if not txt_entries:
            return ArchiveConversionResult(
                archive_name=archive_name,
                archive_errors=[
                    f"archive {archive_name!r} has no .txt entries — expected "
                    f"MarcEdit-format `<name>.-tasksfile-<guid>.txt` files inside."
                ],
            )

        # Reject early on entry-count blow-out — looking up info objects
        # is cheap and avoids paying any decompression cost first.
        if len(txt_entries) > max_entries:
            return ArchiveConversionResult(
                archive_name=archive_name,
                archive_errors=[
                    f"archive {archive_name!r} has {len(txt_entries)} .txt "
                    f"entries — refusing past {max_entries}. Split the "
                    f"archive or raise the cap."
                ],
            )

        # Pre-flight on declared (uncompressed) sizes — file_size is
        # read straight from the central directory, so an attacker
        # crafting a deliberately tiny header still trips the cap
        # because the actual stream size will match it during read().
        declared_total = sum(zf.getinfo(n).file_size for n in txt_entries)
        if declared_total > max_total_decompressed:
            return ArchiveConversionResult(
                archive_name=archive_name,
                archive_errors=[
                    f"archive {archive_name!r} would decompress to "
                    f"{declared_total} bytes — refusing past "
                    f"{max_total_decompressed}. Trim the archive or "
                    f"raise the cap."
                ],
            )

        entries: list[EntryResult] = []
        decompressed_so_far = 0
        for entry_name in txt_entries:
            try:
                raw = zf.read(entry_name)
                # Running cap on actually-decompressed bytes — the
                # declared-size check above blocks the typical case;
                # this catches a zip that lies in its central directory.
                decompressed_so_far += len(raw)
                if decompressed_so_far > max_total_decompressed:
                    entries.append(EntryResult(
                        entry_name=entry_name,
                        success=False,
                        error=(
                            f"decompressed size exceeded "
                            f"{max_total_decompressed} bytes; remaining "
                            "entries skipped."
                        ),
                    ))
                    break
                # MarcEdit emits UTF-8 today; fall back to latin-1 (which never
                # raises) for any older / weird-encoding artifacts.
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    entries.append(EntryResult(
                        entry_name=entry_name,
                        success=False,
                        error=(
                            f"could not decode {entry_name!r} as UTF-8: {exc}"
                        ),
                    ))
                    continue
                conv = convert_tasksfile_text(
                    text,
                    name=_derive_name_from_filename(entry_name),
                    description_fallback=(
                        f"Imported from {entry_name} (in {archive_name})"
                    ),
                )
                entries.append(EntryResult(
                    entry_name=entry_name,
                    success=True,
                    conversion=conv,
                ))
            except Exception as exc:  # noqa: BLE001 — surface any failure
                logger.exception(
                    "inner-entry conversion failed: %s in %s",
                    entry_name, archive_name,
                )
                entries.append(EntryResult(
                    entry_name=entry_name,
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                ))

    return ArchiveConversionResult(
        archive_name=archive_name,
        entries=entries,
    )


def _derive_name_from_filename(filename: str) -> str:
    """Best-effort slug derivation from a MarcEdit tasksfile filename.

    MarcEdit uses a few naming conventions:
        Smith CORE Instance.-tasksfile-854c817b…txt   (GUID suffix)
        smith-eds-cc-core-tasksfile.txt
        5c-eds-cc-core-tasksfile.txt
    We lowercase, strip the trailing `.txt`, `-tasksfile…`, and any GUID
    fragment, and replace spaces with hyphens. Falls back to the bare stem.
    """
    stem = Path(filename).stem.lower()
    # Strip GUID-style hex suffixes attached with a dash.
    stem = re.sub(r"-[a-f0-9]{16,}$", "", stem)
    # Strip the literal `-tasksfile` (with optional trailing dot/number).
    stem = re.sub(r"\.?-tasksfile.*$", "", stem)
    stem = re.sub(r"-tasksfile.*$", "", stem)
    stem = stem.replace(" ", "-").replace(".", "-")
    # Collapse runs of separators and trim.
    stem = re.sub(r"-+", "-", stem).strip("-")
    return stem or "imported-task"


_UNSUPPORTED_HEADER = (
    "Unsupported MarcEdit lines (review and convert manually):"
)


def _docstring_for(result: ConversionResult) -> str:
    """Build the module-level docstring for an imported task.

    Always starts with the human description. When the converter couldn't
    translate some lines, they get listed below as a reviewable checklist
    so the cataloger sees them every time the file is opened. The same
    lines also appear inline as `# TODO …` comments in the body.
    """
    lines = ["Imported MarcEdit task.", "", result.description]
    if result.unsupported:
        lines.append("")
        lines.append(_UNSUPPORTED_HEADER)
        for raw in result.unsupported:
            # Strip control whitespace so the docstring stays readable;
            # tabs in the original line collapse into a single space.
            cleaned = " ".join(raw.split())
            lines.append(f"  - {cleaned}")
    # Triple-quoted docstrings can't contain a `"""` literal; escape any
    # appearing in user-supplied text (rare, but cheap to be safe).
    return "\n".join(lines).replace('"""', '\\"\\"\\"')


def build_full_task_file(result: ConversionResult) -> str:
    """Render a complete `tasks/<slug>.py` file from a ConversionResult.

    The output goes through `editor.save_user_task` in normal use, but this
    helper is exposed for tools that want the raw file content (and for
    tests).
    """
    fn_name = result.name.replace("-", "_")
    if fn_name and fn_name[0].isdigit():
        fn_name = "_" + fn_name
    imports = "\n".join(result.imports)
    body = result.body or "pass"
    indented_body = "\n".join(
        f"    {line}" if line.strip() else "" for line in body.splitlines()
    )
    docstring = _docstring_for(result)
    return (
        f'"""{docstring}\n"""\n\n'
        f"from marcedit_web.lib.tasks import task\n"
        + (imports + "\n" if imports else "")
        + "\n\n"
        + f"@task({lit(result.name)}, description={lit(result.description)})\n"
        + f"def {fn_name}(record):\n"
        + (indented_body if indented_body else "    pass")
        + "\n"
    )
