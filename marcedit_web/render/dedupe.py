"""Dedupe page — TASK-043 rewrite for 4K-group workloads.

Old design (v3.1):
  * one ``st.expander`` per duplicate group → 4000 expanders → lag
  * per-group manual radio for keeper selection → infeasible at scale
  * no progress indicator on the indexing pass

New design (this stage):
  * single virtualized ``st.dataframe`` of groups
  * click a row → ``@st.dialog`` modal with side-by-side record diff
  * keeper-selection strategies (first / most fields / most-of-tag /
    field-matches-regex) live in :mod:`marcedit_web.lib.dedupe_strategy`;
    cataloger picks one + params, "Apply strategy" pre-fills keepers
    across all groups, per-group manual overrides in the modal
  * indexing wrapped in ``st.status`` so the 8-second pass on a 10K
    batch shows visible progress

Streaming guarantees from TASK-020 / TASK-028 are preserved — the
loaded RecordStore is written to a per-session buffer file and
indexed via mmap.
"""

from __future__ import annotations

import mmap
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymarc
import streamlit as st

from marcedit_web.lib import dedupe_strategy as ds_lib, marc_diff, session
from marcedit_web.lib.dedupe_strategy import (
    KeeperStrategy,
    StrategyParams,
    apply_strategy_to_groups,
)
from marcedit_web.lib.marc_diff import FieldSpec


# Session-state keys, namespaced under ``dedupe_``.
_K_RESULT = "dedupe_result"
_K_BUFFER_PATH = "dedupe_buffer_path"
_K_SPEC_LABEL = "dedupe_spec_label"
_K_KEEPERS = "dedupe_keepers"             # dict[group_key, offset]
_K_STRATEGY = "dedupe_strategy"           # KeeperStrategy.value (str)
_K_STRATEGY_PARAMS = "dedupe_strategy_params"  # dict
_K_EXPORT_BYTES = "dedupe_export_bytes"
_K_EXPORT_COUNT = "dedupe_export_count"
_K_TABLE = "dedupe_groups_table"          # st.dataframe widget key


@contextmanager
def _open_mmap(path: Path):
    """Yield a read-only mmap view of ``path`` (or empty bytes if empty).

    Shared with the Diff page (TASK-027 / TASK-028). The OS pages in
    only the bytes ``marc_diff`` actually reads.
    """
    fh = open(path, "rb")
    try:
        try:
            mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:
            yield b""
            return
        try:
            yield mm
        finally:
            mm.close()
    finally:
        fh.close()


def render() -> None:
    """Render the Dedupe tab."""
    if not session.require_upload("dedupe within the loaded batch"):
        return

    store = session.current_store()
    total = store.count() if store else 0
    if total == 0:
        st.warning("The loaded file produced no parseable records.")
        return

    st.caption(
        "Find records that share a match key (OCoLC number, ISBN, etc.) "
        "within the loaded batch, pick which one to keep, and export the "
        "rest as a deletes file."
    )

    _render_match_config()

    if st.button(
        "Find duplicates",
        type="primary",
        key="dedupe_find_btn",
        help=(
            "Scan the loaded batch with the match field above and surface "
            "every match key that occurs more than once."
        ),
    ):
        _run_indexing(store)

    result = st.session_state.get(_K_RESULT)
    buffer_path_str = st.session_state.get(_K_BUFFER_PATH)
    if result is None or not buffer_path_str:
        return
    buffer_path = Path(buffer_path_str)

    _render_summary(result)
    if not result.duplicate_offsets:
        st.success("No duplicate match keys found.")
        return

    _render_strategy_picker(buffer_path, result.duplicate_offsets)
    _render_groups_table(buffer_path, result.duplicate_offsets)
    _render_export(buffer_path, result.duplicate_offsets)


# ---------------------------------------------------------------------------
# Match config
# ---------------------------------------------------------------------------


def _render_match_config() -> None:
    st.subheader("Match field")
    st.caption(
        "Default matches on OCoLC 035 $a, which is the most common dedup "
        "key. Customize for ISBN-based matches or other identifiers."
    )

    cols = st.columns([1.5, 1, 1.5, 2, 1])
    cols[0].text_input("Tag", value="035", max_chars=3, key="dedupe_tag")
    cols[1].text_input("Subfield", value="a", max_chars=1, key="dedupe_subfield")
    cols[2].text_input(
        "Byte range (e.g. 35-37)", value="", key="dedupe_byte_range",
    )
    cols[3].text_input(
        "Prefix filter (e.g. (OCoLC))",
        value="(OCoLC)",
        key="dedupe_prefix_filter",
        help=(
            "When set, the spec only considers values starting with this "
            "prefix. `(OCoLC)` is the canonical OCLC-number marker."
        ),
    )
    cols[4].checkbox("Strip prefix", value=True, key="dedupe_strip_prefix")


# ---------------------------------------------------------------------------
# Indexing (with progress)
# ---------------------------------------------------------------------------


def _run_indexing(store) -> None:
    spec = _build_spec(
        st.session_state.get("dedupe_tag", "035"),
        st.session_state.get("dedupe_subfield", "a"),
        st.session_state.get("dedupe_byte_range", ""),
        st.session_state.get("dedupe_prefix_filter", "(OCoLC)"),
        st.session_state.get("dedupe_strip_prefix", True),
    )
    if spec is None:
        st.session_state.pop(_K_RESULT, None)
        return

    buf_path = _ensure_dedupe_buffer_path()
    with st.status("Indexing records…", expanded=True) as status:
        st.write(f"📥 Snapshotting **{store.count():,}** records to disk")
        store.write_mrc_to(buf_path)
        st.write("🔎 Building offsets index")
        try:
            with _open_mmap(buf_path) as mm:
                idx_result = marc_diff.index_buffer("loaded", mm, [spec])
        except Exception as exc:  # noqa: BLE001
            status.update(
                label=f"Indexing failed: {exc}", state="error",
            )
            return
        groups = idx_result.duplicate_offsets
        st.write(
            f"📊 Found **{len(groups):,}** duplicate group(s) covering "
            f"{sum(len(o) for o in groups.values()):,} records"
        )
        status.update(label="✅ Indexing complete", state="complete", expanded=False)

    st.session_state[_K_RESULT] = idx_result
    st.session_state[_K_BUFFER_PATH] = str(buf_path)
    st.session_state[_K_SPEC_LABEL] = spec.label()
    st.session_state.pop(_K_EXPORT_BYTES, None)
    # Default keepers: first occurrence per group.
    st.session_state[_K_KEEPERS] = {
        key: offsets[0] for key, offsets in idx_result.duplicate_offsets.items()
    }
    st.session_state[_K_STRATEGY] = KeeperStrategy.FIRST_OCCURRENCE.value
    st.session_state[_K_STRATEGY_PARAMS] = {}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _render_summary(result) -> None:
    st.divider()
    spec_label = st.session_state.get(_K_SPEC_LABEL, "?")
    groups = result.duplicate_offsets
    delete_candidates = sum(max(0, len(o) - 1) for o in groups.values())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Match field", spec_label)
    c2.metric("Records scanned", result.total_records)
    c3.metric("Duplicate groups", len(groups))
    c4.metric("Deletes if all kept", delete_candidates)

    if result.missing_key_offsets:
        st.warning(
            f"{len(result.missing_key_offsets)} record(s) had no match-key "
            "value and were skipped. Pick a different match field if dedupe "
            "should include them."
        )


# ---------------------------------------------------------------------------
# Strategy picker
# ---------------------------------------------------------------------------


_STRATEGY_LABELS = [
    (KeeperStrategy.FIRST_OCCURRENCE.value, "First occurrence (default)"),
    (KeeperStrategy.MOST_FIELDS.value, "Most fields (richest record)"),
    (KeeperStrategy.MOST_OF_TAG.value, "Most occurrences of a tag"),
    (KeeperStrategy.FIELD_MATCHES_REGEX.value, "Field value matches regex"),
]


def _render_strategy_picker(
    buffer_path: Path, dup_groups: dict[str, list[int]],
) -> None:
    st.subheader("Choose keepers")
    st.caption(
        "Pre-fill keepers across all groups via a strategy. Manual "
        "overrides via the row dialog stay sticky — re-applying a "
        "strategy resets ALL keepers to the strategy's choice."
    )

    strategy_key = st.selectbox(
        "Strategy",
        options=[k for k, _ in _STRATEGY_LABELS],
        format_func=lambda k: dict(_STRATEGY_LABELS)[k],
        index=[k for k, _ in _STRATEGY_LABELS].index(
            st.session_state.get(_K_STRATEGY, KeeperStrategy.FIRST_OCCURRENCE.value)
        ),
        key="dedupe_strategy_select",
    )
    strategy = KeeperStrategy(strategy_key)
    params = _render_strategy_params(strategy)

    # TASK-044: pre-validate the params before Apply fires. Previously a
    # bad regex (e.g. ``^(SCSK`` with an unbalanced paren) compiled-fail
    # SILENTLY and the strategy fell back to first-occurrence on every
    # group — the cataloger saw "Applied to 4000 groups" with no records
    # actually matched. Now we block Apply on invalid params and show a
    # clear error pointing at how to fix it (escape literal parens).
    validation_error = ds_lib.validate_params(strategy, params)
    if validation_error:
        st.error(validation_error)

    if st.button(
        "Apply strategy to all groups",
        key="dedupe_apply_strategy",
        disabled=validation_error is not None,
    ):
        with st.spinner("Applying strategy…"):
            with _open_mmap(buffer_path) as mm:
                # mmap → bytes copy is needed once; pymarc.Record can't
                # slice an mmap when constructed via Record(data=...).
                # For typical dedupe-buffer sizes this is fine; for
                # the 1.5 GB case we'd revisit.
                source_bytes = bytes(mm)
                keepers, matched = apply_strategy_to_groups(
                    dup_groups, source_bytes, strategy, params,
                )
        st.session_state[_K_KEEPERS] = keepers
        st.session_state[_K_STRATEGY] = strategy_key
        st.session_state[_K_STRATEGY_PARAMS] = params.__dict__
        st.session_state.pop(_K_EXPORT_BYTES, None)

        # Surface match counts so the cataloger can tell whether the
        # strategy actually hit. FIELD_MATCHES_REGEX in particular can
        # silently fall back to first-occurrence when no group member
        # matches the pattern; previously this was invisible.
        total = len(keepers)
        if strategy == KeeperStrategy.FIELD_MATCHES_REGEX:
            fallbacks = total - matched
            if matched == 0:
                st.warning(
                    f"Regex matched **0 of {total:,}** groups — all keepers "
                    "fell back to first-occurrence. Check the pattern (`(` "
                    "and `)` need to be escaped as `\\(` and `\\)` for "
                    "literal parens) and the target tag/subfield."
                )
            elif fallbacks > 0:
                st.success(
                    f"Applied {dict(_STRATEGY_LABELS)[strategy_key]}: "
                    f"**{matched:,}** group(s) matched the regex; "
                    f"**{fallbacks:,}** fell back to first-occurrence."
                )
            else:
                st.success(
                    f"Applied {dict(_STRATEGY_LABELS)[strategy_key]} to "
                    f"all **{matched:,}** groups."
                )
        else:
            st.success(
                f"Applied {dict(_STRATEGY_LABELS)[strategy_key]} to "
                f"{total:,} groups."
            )


def _render_strategy_params(strategy: KeeperStrategy) -> StrategyParams:
    """Render the param widgets for the chosen strategy; return params."""
    if strategy == KeeperStrategy.MOST_OF_TAG:
        tag = st.text_input(
            "Tag (count occurrences of this tag per record)",
            value=st.session_state.get("dedupe_tag", "035"),
            max_chars=3,
            key="dedupe_strategy_tag",
            help=(
                "Example: tag=035 → keep the record with the most 035 "
                "fields (e.g. EDZ + SCSK + OCoLC beats EDZ alone)."
            ),
        )
        return StrategyParams(tag=(tag or "").strip())

    if strategy == KeeperStrategy.FIELD_MATCHES_REGEX:
        cols = st.columns([1, 1, 3, 1])
        tag = cols[0].text_input(
            "Tag", value="035", max_chars=3, key="dedupe_strategy_regex_tag",
        )
        subfield = cols[1].text_input(
            "Subfield", value="a", max_chars=1,
            key="dedupe_strategy_regex_sub",
        )
        pattern = cols[2].text_input(
            "Regex pattern",
            value=st.session_state.get("dedupe_strategy_regex_pattern", "^SCSK"),
            key="dedupe_strategy_regex_pattern",
            placeholder=r"e.g. ^SCSK\d+  or  ^\(OCoLC\)",
            help=(
                "First record in the group whose tag$subfield value "
                "matches the regex wins. No match → first occurrence."
            ),
        )
        case_sensitive = cols[3].checkbox(
            "Case-sensitive", value=False,
            key="dedupe_strategy_regex_case",
        )
        return StrategyParams(
            tag=(tag or "").strip(),
            subfield=(subfield or "").strip() or None,
            pattern=pattern or "",
            case_sensitive=bool(case_sensitive),
        )

    return StrategyParams()


# ---------------------------------------------------------------------------
# Virtualized groups table
# ---------------------------------------------------------------------------


def _render_groups_table(
    buffer_path: Path, dup_groups: dict[str, list[int]],
) -> None:
    st.subheader(f"Duplicate groups ({len(dup_groups):,})")
    st.caption(
        "Click a row to open the side-by-side diff dialog and pick a "
        "keeper manually for that group."
    )

    keepers: dict[str, int] = st.session_state.get(_K_KEEPERS, {})
    rows = _build_group_rows(buffer_path, dup_groups, keepers)
    df = pd.DataFrame(rows)

    event = st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        height=400,
        column_config={
            "key": st.column_config.TextColumn("Match key", width="medium"),
            "size": st.column_config.NumberColumn("Group size", width="small"),
            "keeper_offset": st.column_config.NumberColumn(
                "Keeper byte offset", width="medium",
            ),
            "identifiers": st.column_config.TextColumn(
                "001s in group", width="large",
            ),
        },
        on_select="rerun",
        selection_mode="single-row",
        key=_K_TABLE,
    )

    selection = getattr(event, "selection", None)
    if selection and getattr(selection, "rows", None):
        selected_idx = selection.rows[0]
        if 0 <= selected_idx < len(rows):
            key = rows[selected_idx]["key"]
            _dialog_compare_group(
                key=key,
                offsets=dup_groups[key],
                buffer_path_str=str(buffer_path),
            )


def _build_group_rows(
    buffer_path: Path,
    dup_groups: dict[str, list[int]],
    keepers: dict[str, int],
) -> list[dict]:
    """Build the per-group display rows. Reads each record once for the 001."""
    rows: list[dict] = []
    with buffer_path.open("rb") as fh:
        for key, offsets in dup_groups.items():
            ids: list[str] = []
            for off in offsets:
                try:
                    fh.seek(off)
                    length = int(fh.read(5))
                    fh.seek(off)
                    chunk = fh.read(length)
                    rec = pymarc.Record(data=chunk)
                    f001 = rec.get("001")
                    if f001 is not None and f001.data:
                        ids.append(f001.data)
                    else:
                        ids.append("(no 001)")
                except Exception:  # noqa: BLE001
                    ids.append("(parse error)")
            rows.append({
                "key": key,
                "size": len(offsets),
                "keeper_offset": keepers.get(key, offsets[0]),
                "identifiers": " · ".join(ids),
            })
    return rows


# ---------------------------------------------------------------------------
# Modal: side-by-side comparison
# ---------------------------------------------------------------------------


@st.dialog("Compare duplicates", width="large")
def _dialog_compare_group(
    key: str, offsets: list[int], buffer_path_str: str,
) -> None:
    """Render a side-by-side record diff for one duplicate group.

    The cataloger sees every member of the group, picks the keeper
    via radio, clicks Save. The choice lands in
    ``session_state[_K_KEEPERS]`` and overrides the strategy default
    for this specific group.
    """
    st.markdown(f"**Match key:** `{key}` — {len(offsets)} record(s)")
    buffer_path = Path(buffer_path_str)
    keepers: dict[str, int] = st.session_state.get(_K_KEEPERS, {})
    current = keepers.get(key, offsets[0])
    if current not in offsets:
        current = offsets[0]

    choice = st.radio(
        "Keeper",
        options=offsets,
        index=offsets.index(current),
        format_func=lambda o: f"record @ byte offset {o:,}",
        key=f"dedupe_modal_keep_{key}",
        horizontal=False,
    )

    st.caption(
        "All members of the group are shown below; the keeper is the "
        "record you save. Other members will be queued for the deletes "
        "export."
    )

    # One column per record. For 2-record groups this is the cleanest
    # side-by-side; for 3+ it wraps as cards in a flow.
    cols = st.columns(min(len(offsets), 3))
    with buffer_path.open("rb") as fh:
        for i, off in enumerate(offsets):
            target_col = cols[i % len(cols)]
            with target_col:
                fh.seek(off)
                length = int(fh.read(5))
                fh.seek(off)
                chunk = fh.read(length)
                try:
                    rec = pymarc.Record(data=chunk)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Offset {off:,}: parse error ({exc})")
                    continue
                ident = ""
                f001 = rec.get("001")
                if f001 is not None:
                    ident = f001.data or ""
                marker = "✅ keeper" if off == choice else "🗑 will be exported as delete"
                st.markdown(f"**Offset {off:,}** — `{ident}` — {marker}")
                st.code(str(rec), language="text")

    if st.button("Save keeper choice", type="primary", key=f"dedupe_modal_save_{key}"):
        keepers[key] = choice
        st.session_state[_K_KEEPERS] = keepers
        # Invalidate any built deletes; they may not reflect the new choice.
        st.session_state.pop(_K_EXPORT_BYTES, None)
        st.rerun()


# ---------------------------------------------------------------------------
# Export deletes
# ---------------------------------------------------------------------------


def _render_export(buffer_path: Path, dup_groups: dict[str, list[int]]) -> None:
    delete_candidates = sum(max(0, len(o) - 1) for o in dup_groups.values())

    st.divider()
    st.subheader("Export deletes")
    st.caption(
        "Build a `.mrc` containing one copy of every non-keeper from the "
        "groups above. Load this into your discovery service's delete "
        "import to actually remove them."
    )

    build_clicked = st.button(
        "Build deletes file",
        type="primary",
        disabled=delete_candidates == 0,
        key="dedupe_build_btn",
    )
    if build_clicked:
        keepers: dict[str, int] = st.session_state.get(_K_KEEPERS, {})
        delete_locations: list[tuple[str, int]] = []
        for key, offsets in dup_groups.items():
            keeper = keepers.get(key, offsets[0])
            for off in offsets:
                if off != keeper:
                    delete_locations.append(("loaded", off))
        try:
            with _open_mmap(buffer_path) as mm:
                deletes_bytes = marc_diff.write_subset_to_bytes(
                    delete_locations, {"loaded": mm}
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Build failed: {exc}")
            return
        st.session_state[_K_EXPORT_BYTES] = deletes_bytes
        st.session_state[_K_EXPORT_COUNT] = len(delete_locations)

    export_bytes = st.session_state.get(_K_EXPORT_BYTES)
    if export_bytes is not None:
        count = st.session_state.get(_K_EXPORT_COUNT, 0)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = Path(session.current_filename() or "deletes").stem or "deletes"
        fname = f"{stem}_deletes_{stamp}.mrc"
        st.success(
            f"Built `{fname}` with **{count}** record(s) "
            f"({len(export_bytes) / 1e6:,.2f} MB)."
        )
        st.download_button(
            label=f"Download {fname}",
            data=export_bytes,
            file_name=fname,
            mime="application/marc",
            key="dedupe_download_btn",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dedupe_buffer_path() -> Path:
    """Return (and lazily create) the per-session path for the dedupe buffer.

    Reused across reruns so the buffer file isn't rewritten unnecessarily.
    """
    key = "dedupe_buffer_dir"
    if key not in st.session_state:
        st.session_state[key] = tempfile.mkdtemp(prefix="marcedit-web-dedupe-")
    return Path(st.session_state[key]) / "dedupe_buffer.mrc"


def _build_spec(
    tag: str,
    subfield: str,
    byte_range: str,
    prefix_filter: str,
    strip_prefix: bool,
) -> FieldSpec | None:
    tag = (tag or "").strip()
    if len(tag) != 3 or not tag.isalnum():
        st.error(f"Tag must be 3 alphanumeric chars; got {tag!r}")
        return None

    subfield = (subfield or "").strip() or None
    byte_range_str = (byte_range or "").strip()
    byte_range_tuple = None
    if byte_range_str:
        if subfield:
            st.error("Provide either a subfield OR a byte range, not both.")
            return None
        try:
            if "-" in byte_range_str:
                a, b = byte_range_str.split("-", 1)
                byte_range_tuple = (int(a), int(b))
            else:
                v = int(byte_range_str)
                byte_range_tuple = (v, v)
        except ValueError:
            st.error(f"Invalid byte range {byte_range_str!r}.")
            return None

    prefix = (prefix_filter or "").strip() or None
    if prefix and subfield is None and byte_range_tuple is None:
        st.error("Prefix filter only applies with a subfield.")
        return None

    return FieldSpec(
        tag=tag,
        subfield=subfield,
        byte_range=byte_range_tuple,
        prefix_filter=prefix,
        strip_prefix=bool(strip_prefix),
    )
