"""Diff — original-vs-new MARC file comparison.

Ported from `marc-diff/app.py`. Three changes from the source:

1. Imports rewired to ``from marcedit_web.lib import marc_diff``.
2. All session keys prefixed with ``diff_`` so the Diff workflow
   doesn't clobber the Home upload / Validate / Report / View state.
3. "Start over" only clears ``diff_*`` keys, not the whole session.

Workflow:
  1. Upload one or more "original" MARC files.
  2. Upload one or more "new" MARC files.
  3. Scan samples for suggested match fields.
  4. Configure one or more FieldSpec entries.
  5. Run the diff (with optional content-change detection).
  6. Review adds / deletes / changed records.
  7. Generate downloadable adds and deletes MARC files.
"""

from __future__ import annotations

import io
from datetime import datetime

import pymarc
import streamlit as st

from marcedit_web.lib import marc_diff, session
from marcedit_web.lib.marc_diff import FieldSpec, OCOLC_SPEC


# ---------------------------------------------------------------------------
# Session-state helpers (all keys prefixed with `diff_`)
# ---------------------------------------------------------------------------


def _spec_to_form(spec: FieldSpec) -> dict:
    return {
        "tag": spec.tag,
        "subfield": spec.subfield or "",
        "byte_range": (
            f"{spec.byte_range[0]}-{spec.byte_range[1]}"
            if spec.byte_range
            else ""
        ),
        "prefix_filter": spec.prefix_filter or "",
        "strip_prefix": spec.strip_prefix,
    }


def _init_diff_state() -> None:
    st.session_state.setdefault("diff_old_buffers", None)
    st.session_state.setdefault("diff_new_buffers", None)
    st.session_state.setdefault("diff_combined_suggestions", None)
    st.session_state.setdefault("diff_preview_matches", None)
    st.session_state.setdefault("diff_preview_specs", None)
    st.session_state.setdefault("diff_specs", [_spec_to_form(OCOLC_SPEC)])
    st.session_state.setdefault("diff_result", None)
    st.session_state.setdefault("diff_include_changes", False)
    st.session_state.setdefault("diff_output_blobs", None)


def _reset_diff() -> None:
    """Clear only the Diff workflow's state. Home/View/Validate/Report stay."""
    for key in list(st.session_state.keys()):
        if key.startswith("diff_") or key.startswith("diff_page_"):
            del st.session_state[key]
    _init_diff_state()


def _form_to_spec(form: dict) -> FieldSpec | str:
    """Convert a form row to a FieldSpec, or return an error string."""
    tag = (form.get("tag") or "").strip()
    if len(tag) != 3 or not tag.isalnum():
        return f"Tag must be 3 alphanumeric chars; got {tag!r}"

    byte_range_raw = (form.get("byte_range") or "").strip()
    subfield = (form.get("subfield") or "").strip() or None
    byte_range = None
    if byte_range_raw:
        if subfield:
            return f"Tag {tag}: provide either a subfield OR a byte range, not both"
        try:
            if "-" in byte_range_raw:
                a, b = byte_range_raw.split("-", 1)
                byte_range = (int(a), int(b))
            else:
                v = int(byte_range_raw)
                byte_range = (v, v)
        except ValueError:
            return f"Tag {tag}: invalid byte range {byte_range_raw!r}"

    prefix = (form.get("prefix_filter") or "").strip() or None
    if prefix and subfield is None and byte_range is None:
        return f"Tag {tag}: prefix filter only applies with a subfield"

    return FieldSpec(
        tag=tag,
        subfield=subfield,
        byte_range=byte_range,
        prefix_filter=prefix,
        strip_prefix=bool(form.get("strip_prefix", True)),
    )


def _all_specs_or_errors(
    forms: list[dict],
) -> tuple[list[FieldSpec] | None, list[str]]:
    specs: list[FieldSpec] = []
    errors: list[str] = []
    for f in forms:
        result = _form_to_spec(f)
        if isinstance(result, str):
            errors.append(result)
        else:
            specs.append(result)
    if errors:
        return None, errors
    if not specs:
        return None, ["At least one match field is required."]
    return specs, []


def _read_uploaded(files) -> list[tuple[str, bytes]]:
    return [(f.name, f.getvalue()) for f in (files or [])]


# ---------------------------------------------------------------------------
# Modal helpers
# ---------------------------------------------------------------------------


def _render_record_at(sources: dict[str, bytes], buf_name: str, off: int) -> str:
    data = sources[buf_name]
    length = int(data[off:off + 5])
    return str(pymarc.Record(data=data[off:off + length]))


def _paginator(key: str, total: int, per_page: int) -> tuple[int, int]:
    """Render Prev/Next controls; return (start, end) slice indices."""
    pages = max(1, (total + per_page - 1) // per_page)
    state_key = f"diff_page_{key}"
    page = st.session_state.get(state_key, 0)
    page = max(0, min(page, pages - 1))
    c1, c2, c3 = st.columns([1, 2, 1])
    if c1.button("◀ Prev", key=f"diff_prev_{key}", disabled=page == 0):
        st.session_state[state_key] = page - 1
        st.rerun()
    c2.caption(f"Page {page + 1} of {pages} — {total} total")
    if c3.button("Next ▶", key=f"diff_next_{key}", disabled=page >= pages - 1):
        st.session_state[state_key] = page + 1
        st.rerun()
    return page * per_page, min(total, (page + 1) * per_page)


@st.dialog("Records", width="large")
def _dialog_records(
    title: str,
    locations: list[tuple[str, int]],
    sources: dict[str, bytes],
) -> None:
    st.subheader(title)
    if not locations:
        st.info("Nothing to show.")
        return
    start, end = _paginator(f"recs_{title}", len(locations), per_page=5)
    for buf_name, off in locations[start:end]:
        st.caption(f"`{buf_name}` @ offset {off:,}")
        st.code(_render_record_at(sources, buf_name, off), language="text")


@st.dialog("Duplicate-key groups", width="large")
def _dialog_dup_groups(
    title: str,
    groups: list[tuple[str, list[tuple[str, int]]]],
    sources: dict[str, bytes],
) -> None:
    st.subheader(title)
    if not groups:
        st.info("Nothing to show.")
        return
    start, end = _paginator(f"groups_{title}", len(groups), per_page=3)
    for key, locs in groups[start:end]:
        st.markdown(
            f"**Key:** `{key}` — {len(locs)} occurrence(s) "
            "(only the first is used for matching)"
        )
        for buf_name, off in locs:
            st.caption(f"`{buf_name}` @ offset {off:,}")
            st.code(_render_record_at(sources, buf_name, off), language="text")
        st.divider()


_DIFF_STYLES = {
    "unchanged": "",
    "changed":   "background:#fff3a8;color:#111",
    "added":     "background:#c8f5c8;color:#111",
    "removed":   "background:#fbd0d0;color:#111",
}


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_diff_html(rows: list[tuple[str, str, str]]) -> str:
    parts = [
        "<style>",
        ".marc-diff{font-family:ui-monospace,Menlo,Consolas,monospace;",
        "font-size:12px;width:100%;border-collapse:collapse}",
        ".marc-diff td{padding:2px 6px;vertical-align:top;",
        "white-space:pre-wrap;word-break:break-all;",
        "border:1px solid rgba(128,128,128,0.3)}",
        ".marc-diff th{padding:4px 6px;text-align:left;",
        "background:#444;color:white;",
        "border:1px solid rgba(128,128,128,0.3)}",
        "</style>",
        '<table class="marc-diff">',
        "<thead><tr><th>OLD</th><th>NEW</th></tr></thead><tbody>",
    ]
    for o, n, status in rows:
        style = _DIFF_STYLES.get(status, "")
        parts.append(
            f'<tr><td style="{style}">{_escape_html(o)}</td>'
            f'<td style="{style}">{_escape_html(n)}</td></tr>'
        )
    parts.append("</tbody></table>")
    return "".join(parts)


@st.dialog("Side-by-side diff", width="large")
def _dialog_diff(
    key: str,
    old_loc: tuple[str, int],
    new_loc: tuple[str, int],
    old_sources: dict[str, bytes],
    new_sources: dict[str, bytes],
) -> None:
    st.markdown(f"**Match key:** `{key}`")
    o_data = old_sources[old_loc[0]]
    n_data = new_sources[new_loc[0]]
    o_len = int(o_data[old_loc[1]:old_loc[1] + 5])
    n_len = int(n_data[new_loc[1]:new_loc[1] + 5])
    rows = marc_diff.field_diff(
        o_data[old_loc[1]:old_loc[1] + o_len],
        n_data[new_loc[1]:new_loc[1] + n_len],
    )

    counts = {"unchanged": 0, "changed": 0, "added": 0, "removed": 0}
    for _o, _n, status in rows:
        counts[status] += 1
    total = len(rows) or 1
    pct_match = counts["unchanged"] / total

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("% match", f"{pct_match:.0%}")
    c2.metric("Unchanged", counts["unchanged"])
    c3.metric("Changed", counts["changed"])
    c4.metric("Added", counts["added"])
    c5.metric("Removed", counts["removed"])

    st.caption(
        "Yellow = changed · Green = added in new · Red = removed in new · "
        "Transparent = unchanged"
    )
    st.markdown(_render_diff_html(rows), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


st.set_page_config(page_title="Diff · marcedit-web", layout="wide")
session.init()
_init_diff_state()

st.title("Diff")
st.caption(
    "Compare original and new MARC file batches. Generate adds / deletes "
    "MARC files for vendor reconciliation. Independent of the Home upload — "
    "this page reads its own uploads."
)


# --- Sidebar status --------------------------------------------------------


with st.sidebar:
    st.header("marcedit-web")
    user = st.session_state.get("user", "anonymous")
    st.caption(f"Signed in as **{user}**")
    st.divider()
    if session.has_upload():
        st.caption(f"Home batch: `{session.current_filename() or '(unnamed)'}`")
        st.caption(f"{len(session.current_records())} records (not used here)")
    else:
        st.caption("No file loaded on Home (Diff uses its own uploads).")
    st.divider()
    st.subheader("Diff session")
    if st.button("Start over (clear Diff uploads)"):
        _reset_diff()
        st.rerun()


# ----- Step 1 + 2: uploads -------------------------------------------------

st.header("1. Upload files")
col_left, col_right = st.columns(2)
with col_left:
    old_files = st.file_uploader(
        "Original files (already in your discovery service)",
        type=["mrc", "marc"],
        accept_multiple_files=True,
        key="diff_old_uploader",
    )
with col_right:
    new_files = st.file_uploader(
        "New files (from the vendor)",
        type=["mrc", "marc"],
        accept_multiple_files=True,
        key="diff_new_uploader",
    )

if old_files:
    st.session_state["diff_old_buffers"] = _read_uploaded(old_files)
if new_files:
    st.session_state["diff_new_buffers"] = _read_uploaded(new_files)

old_bufs = st.session_state["diff_old_buffers"]
new_bufs = st.session_state["diff_new_buffers"]

if old_bufs:
    st.write(
        f"**Original:** {len(old_bufs)} file(s), "
        f"{sum(len(d) for _, d in old_bufs) / 1e6:,.0f} MB"
    )
if new_bufs:
    st.write(
        f"**New:** {len(new_bufs)} file(s), "
        f"{sum(len(d) for _, d in new_bufs) / 1e6:,.0f} MB"
    )

if not (old_bufs and new_bufs):
    st.info("Upload at least one original file and one new file to continue.")
    st.stop()


# ----- Step 3: suggestions -------------------------------------------------

st.header("2. Suggested fields")
st.caption(
    "Sampled from the first 500 records on each side. **Overlap** is the "
    "share of values that appear on *both* sides — the strongest signal for "
    "a viable match key."
)

if st.button("Scan a sample for suggestions") or (
    st.session_state.get("diff_combined_suggestions") is not None
):
    if st.session_state.get("diff_combined_suggestions") is None:
        with st.spinner("Sampling records on both sides..."):
            st.session_state["diff_combined_suggestions"] = (
                marc_diff.combined_field_suggestions(
                    old_bufs, new_bufs, sample_size=500
                )
            )

    combined = st.session_state["diff_combined_suggestions"][:20]
    st.table(
        {
            "Tag/$sub": [
                (f"{s.tag}${s.subfield}" if s.subfield else s.tag)
                + (" (OCoLC)" if s.is_oclc_prefixed else "")
                for s in combined
            ],
            "Old %": [f"{s.old_coverage:.0%}" for s in combined],
            "New %": [f"{s.new_coverage:.0%}" for s in combined],
            "Distinct old": [s.old_distinct_values for s in combined],
            "Distinct new": [s.new_distinct_values for s in combined],
            "Shared": [s.shared_values for s in combined],
            "Overlap": [f"{s.overlap:.0%}" for s in combined],
            "Sample value": [(s.sample_value or "") for s in combined],
        }
    )


# ----- Step 4: configure match fields --------------------------------------

st.header("3. Match fields")
st.caption(
    "All listed fields must be present on a record for it to match (AND). "
    "Records missing any field are treated as unique (will appear in adds or "
    "deletes)."
)

forms: list[dict] = st.session_state["diff_specs"]
to_remove: list[int] = []

for i, form in enumerate(forms):
    cols = st.columns([1.5, 1, 1.5, 2, 1, 0.6])
    form["tag"] = cols[0].text_input(
        "Tag", value=form["tag"], key=f"diff_tag_{i}", max_chars=3
    )
    form["subfield"] = cols[1].text_input(
        "Subfield", value=form["subfield"], key=f"diff_sub_{i}", max_chars=1
    )
    form["byte_range"] = cols[2].text_input(
        "Byte range (e.g. 35-37)",
        value=form["byte_range"],
        key=f"diff_br_{i}",
    )
    form["prefix_filter"] = cols[3].text_input(
        "Prefix filter (e.g. (OCoLC))",
        value=form["prefix_filter"],
        key=f"diff_pref_{i}",
    )
    form["strip_prefix"] = cols[4].checkbox(
        "Strip prefix",
        value=form["strip_prefix"],
        key=f"diff_strip_{i}",
    )
    if cols[5].button("✕", key=f"diff_del_{i}", help="Remove this field"):
        to_remove.append(i)

if to_remove:
    for i in reversed(to_remove):
        forms.pop(i)
    st.rerun()

if st.button("Add another field"):
    forms.append(
        {
            "tag": "",
            "subfield": "",
            "byte_range": "",
            "prefix_filter": "",
            "strip_prefix": True,
        }
    )
    st.rerun()


# ----- Step 4: preview sample matches --------------------------------------

st.header("4. Preview sample matches")
st.caption(
    "Verify the match key works before running the full diff. This indexes "
    "both sides with your current match fields and shows a sample of records "
    "that exist on both sides."
)

if st.button("Find sample matching records"):
    specs, errors = _all_specs_or_errors(forms)
    if errors:
        for e in errors:
            st.error(e)
    else:
        with st.spinner("Indexing both sides and finding matches..."):
            st.session_state["diff_preview_matches"] = marc_diff.sample_matches(
                old_bufs, new_bufs, specs, limit=20
            )
            st.session_state["diff_preview_specs"] = specs

preview = st.session_state.get("diff_preview_matches")
if preview is not None:
    if not preview:
        st.warning(
            "No matching records found with the current match fields. "
            "Check that your fields exist on both sides and produce comparable "
            "values (e.g., for OCoLC numbers add `(OCoLC)` as the prefix filter)."
        )
    else:
        st.success(f"Found {len(preview)} matching record(s). Click any to inspect.")
        old_sources_dict = dict(old_bufs)
        new_sources_dict = dict(new_bufs)
        for key, old_loc, new_loc in preview:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"`{key}`")
            if c2.button("View diff", key=f"diff_preview_{key}"):
                _dialog_diff(
                    key,
                    old_loc,
                    new_loc,
                    old_sources_dict,
                    new_sources_dict,
                )


# ----- Step 5: run diff ----------------------------------------------------

st.header("5. Run diff")
detect_changes = st.checkbox(
    "Also detect content changes for matched records",
    value=False,
    help=(
        "When on, the app fingerprints the content of each matched record on "
        "both sides and reports records whose content has changed."
    ),
)

default_exclude = "001, 005, 008"
exclude_tags_str = st.text_input(
    "When detecting changes, ignore these tags",
    value=default_exclude,
    help=(
        "Comma-separated MARC tags excluded from fingerprinting. Volatile "
        "fields excluded by default: 001 (vendor control number), 005 "
        "(transaction timestamp), and 008 (whose first 6 bytes encode the "
        "vendor's export entry date and would flip every record as changed). "
        "The tags used in your match fields are also auto-excluded."
    ),
    disabled=not detect_changes,
)

if st.button("Run diff", type="primary"):
    specs, errors = _all_specs_or_errors(forms)
    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    exclude_tags = {
        t.strip() for t in exclude_tags_str.split(",") if t.strip()
    }
    exclude_tags |= {s.tag for s in specs}

    with st.spinner("Indexing original..."):
        old_idx = marc_diff.index_buffers(old_bufs, specs)
    with st.spinner("Indexing new..."):
        new_idx = marc_diff.index_buffers(new_bufs, specs)

    diff = marc_diff.compute_diff(old_idx, new_idx)

    changed: set[str] = set()
    if detect_changes:
        with st.spinner(
            f"Checking content of {len(diff.common_ids):,} matched records..."
        ):
            changed = marc_diff.detect_changes(
                old_idx,
                new_idx,
                dict(old_bufs),
                dict(new_bufs),
                diff.common_ids,
                exclude_tags=frozenset(exclude_tags),
            )

    st.session_state["diff_result"] = {
        "old_idx": old_idx,
        "new_idx": new_idx,
        "diff": diff,
        "changed": changed,
        "exclude_tags": sorted(exclude_tags),
        "specs": specs,
    }
    st.session_state["diff_output_blobs"] = None  # invalidate any previous build


# ----- Step 6: review ------------------------------------------------------

dr = st.session_state["diff_result"]
if dr:
    st.header("6. Results")

    old_idx = dr["old_idx"]
    new_idx = dr["new_idx"]
    diff = dr["diff"]
    changed: set[str] = dr["changed"]

    st.table(
        {
            "Metric": [
                "Records in original (total)",
                "Records in new (total)",
                "Adds (new only)",
                "Deletes (original only)",
                "Common (matched)",
                "Changed (matched, content differs)",
            ],
            "Count": [
                old_idx.total_records,
                new_idx.total_records,
                len(diff.adds_ids),
                len(diff.deletes_ids),
                len(diff.common_ids),
                len(changed),
            ],
        }
    )

    sources_by_side = {
        "Original": (old_idx, dict(old_bufs)),
        "New": (new_idx, dict(new_bufs)),
    }
    for side, (idx, sources) in sources_by_side.items():
        if idx.missing_key_count:
            outcome = (
                "will appear in deletes"
                if side == "Original"
                else "will appear in adds"
            )
            c1, c2 = st.columns([4, 1])
            c1.warning(
                f"**{side}:** {idx.missing_key_count} record(s) missing one "
                f"or more match fields — each is treated as always-different "
                f"({outcome})."
            )
            if c2.button("View", key=f"diff_view_missing_{side}"):
                _dialog_records(
                    f"{side}: records missing match field",
                    idx.all_missing_key_locations(),
                    sources,
                )
        if idx.within_buffer_duplicate_count:
            within_groups: list[tuple[str, list[tuple[str, int]]]] = []
            for buf_name, ir in idx.per_buffer:
                for k, offs in ir.duplicate_offsets.items():
                    within_groups.append(
                        (k, [(buf_name, off) for off in offs])
                    )
            c1, c2 = st.columns([4, 1])
            c1.warning(
                f"**{side}:** {idx.within_buffer_duplicate_count} duplicate "
                "match key(s) within a single file — only the first occurrence "
                "is indexed."
            )
            if c2.button("View", key=f"diff_view_within_{side}"):
                _dialog_dup_groups(
                    f"{side}: within-file duplicate keys",
                    within_groups,
                    sources,
                )
        if idx.cross_buffer_duplicate_count:
            cross_groups = list(idx.cross_buffer_duplicate_locations.items())
            c1, c2 = st.columns([4, 1])
            c1.warning(
                f"**{side}:** {idx.cross_buffer_duplicate_count} match "
                "key(s) appear in more than one chunk — only the first "
                "occurrence is indexed."
            )
            if c2.button("View", key=f"diff_view_cross_{side}"):
                _dialog_dup_groups(
                    f"{side}: keys appearing in multiple chunks",
                    cross_groups,
                    sources,
                )

    include_changes = False
    if changed:
        include_changes = st.checkbox(
            f"Include all {len(changed):,} changed records in adds AND deletes",
            value=st.session_state.get("diff_include_changes", False),
            key="diff_include_changes",
            help=(
                "When on, every record whose content differs is queued for "
                "both deletion (the old version) and addition (the new "
                "version), so your discovery service ends up with the new copy."
            ),
        )

    if changed:
        st.subheader("Changed records")
        st.caption(
            "Click any row to open a side-by-side diff with changes highlighted."
        )
        changed_list = sorted(changed)
        start, end = _paginator(
            "changed", len(changed_list), per_page=10
        )
        page_keys = changed_list[start:end]
        old_sources_dict = dict(old_bufs)
        new_sources_dict = dict(new_bufs)
        for key in page_keys:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"`{key}`")
            if c2.button("View diff", key=f"diff_changed_{key}"):
                _dialog_diff(
                    key,
                    old_idx.locations[key],
                    new_idx.locations[key],
                    old_sources_dict,
                    new_sources_dict,
                )

    # ----- Step 7+8: generate + download -----

    st.header("7. Generate downloadable files")

    if st.button("Generate adds and deletes files"):
        adds_keys = set(diff.adds_ids)
        deletes_keys = set(diff.deletes_ids)
        if include_changes:
            adds_keys |= changed
            deletes_keys |= changed

        adds_locations = [new_idx.locations[k] for k in adds_keys]
        deletes_locations = [old_idx.locations[k] for k in deletes_keys]

        with st.spinner("Building adds..."):
            adds_bytes = marc_diff.write_subset_to_bytes(
                adds_locations, dict(new_bufs)
            )
        with st.spinner("Building deletes..."):
            deletes_bytes = marc_diff.write_subset_to_bytes(
                deletes_locations, dict(old_bufs)
            )

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.session_state["diff_output_blobs"] = {
            "adds_name": f"adds_{stamp}.mrc",
            "deletes_name": f"deletes_{stamp}.mrc",
            "adds": adds_bytes,
            "deletes": deletes_bytes,
            "adds_count": len(adds_keys),
            "deletes_count": len(deletes_keys),
        }

    blobs = st.session_state.get("diff_output_blobs")
    if blobs:
        st.success(
            f"Generated {blobs['adds_count']:,} adds and "
            f"{blobs['deletes_count']:,} deletes."
        )
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                f"⬇ Download {blobs['adds_name']} "
                f"({len(blobs['adds']) / 1e6:,.1f} MB)",
                data=blobs["adds"],
                file_name=blobs["adds_name"],
                mime="application/marc",
            )
        with d2:
            st.download_button(
                f"⬇ Download {blobs['deletes_name']} "
                f"({len(blobs['deletes']) / 1e6:,.1f} MB)",
                data=blobs["deletes"],
                file_name=blobs["deletes_name"],
                mime="application/marc",
            )
