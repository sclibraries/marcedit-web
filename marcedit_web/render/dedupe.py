"""Dedupe tab — find duplicates within the loaded batch, pick keepers, export deletes.

Companion to the two-file Diff page. Same underlying primitives —
``marc_diff.index_buffer`` exposes ``duplicate_offsets`` for keys seen
more than once within a single buffer; ``marc_diff.write_subset_to_bytes``
materializes a chosen subset to a ``.mrc`` blob.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pymarc
import streamlit as st

from marcedit_web.lib import marc_diff, session
from marcedit_web.lib.marc_diff import FieldSpec, OCOLC_SPEC


def render() -> None:
    """Render the Dedupe tab into the current Streamlit container."""
    if not session.has_upload():
        st.info(
            "Upload a `.mrc` file on **Home** to dedupe within it. Dedupe "
            "uses the records currently loaded in this session."
        )
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

    # --- Match-field config -----------------------------------------------

    st.subheader("Match field")
    st.caption(
        "Default matches on OCoLC 035 $a, which is the most common dedup "
        "key. Customize for ISBN-based matches or other identifiers."
    )

    cols = st.columns([1.5, 1, 1.5, 2, 1])
    tag = cols[0].text_input(
        "Tag", value="035", max_chars=3, key="dedupe_tag",
    )
    subfield = cols[1].text_input(
        "Subfield", value="a", max_chars=1, key="dedupe_subfield",
    )
    byte_range = cols[2].text_input(
        "Byte range (e.g. 35-37)", value="", key="dedupe_byte_range",
    )
    prefix_filter = cols[3].text_input(
        "Prefix filter (e.g. (OCoLC))",
        value="(OCoLC)",
        key="dedupe_prefix_filter",
        help=(
            "When set, the spec only considers values starting with this "
            "prefix. `(OCoLC)` is the canonical OCLC-number marker."
        ),
    )
    strip_prefix = cols[4].checkbox(
        "Strip prefix", value=True, key="dedupe_strip_prefix",
    )

    # --- Find duplicates --------------------------------------------------

    find_clicked = st.button(
        "Find duplicates",
        type="primary",
        key="dedupe_find_btn",
        help=(
            "Scan the loaded batch with the match field above and surface "
            "every match key that occurs more than once."
        ),
    )

    if find_clicked:
        spec = _build_spec(tag, subfield, byte_range, prefix_filter, strip_prefix)
        if spec is None:
            st.session_state.pop("dedupe_result", None)
            return
        raw_bytes = store.to_mrc_bytes()
        try:
            idx_result = marc_diff.index_buffer("loaded", raw_bytes, [spec])
        except Exception as exc:  # noqa: BLE001
            st.error(f"Indexing failed: {exc}")
            return
        st.session_state["dedupe_result"] = idx_result
        st.session_state["dedupe_buffer"] = raw_bytes
        st.session_state["dedupe_spec_label"] = spec.label()
        st.session_state.pop("dedupe_export_bytes", None)

    result = st.session_state.get("dedupe_result")
    buffer_bytes = st.session_state.get("dedupe_buffer")
    if result is None or buffer_bytes is None:
        return

    # --- Summary metrics --------------------------------------------------

    st.divider()
    spec_label = st.session_state.get("dedupe_spec_label", "?")
    dup_groups = result.duplicate_offsets
    dup_record_count = sum(len(offsets) for offsets in dup_groups.values())
    delete_candidates = sum(
        max(0, len(offsets) - 1) for offsets in dup_groups.values()
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Match field", spec_label)
    c2.metric("Records scanned", result.total_records)
    c3.metric("Duplicate groups", len(dup_groups))
    c4.metric("Deletes if all kept", delete_candidates)

    if result.missing_key_offsets:
        st.warning(
            f"{len(result.missing_key_offsets)} record(s) had no match-key "
            "value and were skipped. Pick a different match field if dedupe "
            "should include them."
        )

    if not dup_groups:
        st.success("No duplicate match keys found.")
        return

    # --- Group inspection + keeper picker ---------------------------------

    st.subheader(f"Duplicate groups ({len(dup_groups)})")
    st.caption(
        "Pick the record to KEEP per group. Everything else in the group "
        "is queued for the deletes export."
    )

    for key, offsets in dup_groups.items():
        keeper_state_key = f"dedupe_keeper_{key}"
        if keeper_state_key not in st.session_state:
            st.session_state[keeper_state_key] = offsets[0]

        with st.expander(
            f"Key `{key}` — {len(offsets)} record(s)",
            expanded=False,
        ):
            # Radio defaults to the first occurrence (matches index_buffer's
            # own tie-break) but the user can override per group.
            current = st.session_state[keeper_state_key]
            if current not in offsets:
                current = offsets[0]
                st.session_state[keeper_state_key] = current

            choice = st.radio(
                "Keep:",
                options=offsets,
                index=offsets.index(current),
                format_func=lambda o: f"record @ byte offset {o:,}",
                key=f"dedupe_keeper_radio_{key}",
                horizontal=False,
            )
            st.session_state[keeper_state_key] = choice

            for off in offsets:
                length = int(buffer_bytes[off:off + 5])
                record = pymarc.Record(
                    data=buffer_bytes[off:off + length]
                )
                marker = (
                    "✅ keeper"
                    if off == choice
                    else "🗑 will be exported as a delete"
                )
                st.markdown(
                    f"**Offset {off:,}** — {marker}"
                )
                st.code(str(record), language="text")

    # --- Export deletes ---------------------------------------------------

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
        delete_locations: list[tuple[str, int]] = []
        for key, offsets in dup_groups.items():
            keeper = st.session_state.get(
                f"dedupe_keeper_{key}", offsets[0]
            )
            for o in offsets:
                if o != keeper:
                    delete_locations.append(("loaded", o))
        try:
            deletes_bytes = marc_diff.write_subset_to_bytes(
                delete_locations, {"loaded": buffer_bytes}
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Build failed: {exc}")
            return
        st.session_state["dedupe_export_bytes"] = deletes_bytes
        st.session_state["dedupe_export_count"] = len(delete_locations)

    export_bytes = st.session_state.get("dedupe_export_bytes")
    if export_bytes is not None:
        count = st.session_state.get("dedupe_export_count", 0)
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


def _build_spec(
    tag: str,
    subfield: str,
    byte_range: str,
    prefix_filter: str,
    strip_prefix: bool,
) -> FieldSpec | None:
    """Build a FieldSpec from the form inputs, surfacing errors via st.error.

    Mirrors the Diff page's `_form_to_spec` but inlined here so Dedupe
    stays self-contained.
    """
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
