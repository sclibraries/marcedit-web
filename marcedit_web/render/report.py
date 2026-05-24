"""Report tab — rollups across the loaded batch + per-record table."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from marcedit_web.lib import session
from marcedit_web.lib.reporting import RecordSnapshot


def render() -> None:
    """Render the Report tab into the current Streamlit container."""
    if not session.has_upload():
        st.info(
            "Upload a `.mrc` file on **Home** to see reports. Report walks "
            "records already in this session."
        )
        return

    store = session.current_store()
    records = list(store.iter_records()) if store else []
    total = len(records)
    malformed = store.malformed_count() if store else 0

    snapshots = [RecordSnapshot.of(r, i) for i, r in enumerate(records, start=1)]

    format_counter: Counter = Counter()
    tag_counter: Counter = Counter()
    url_domain_counter: Counter = Counter()
    for snap in snapshots:
        format_counter[snap.format_label] += 1
        tag_counter.update(snap.tags_present)
        url_domain_counter.update(snap.url_domains)

    st.subheader("Across the batch")

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Records", total)
    col_b.metric("Malformed", malformed)
    col_c.metric("Distinct tags", len(tag_counter))

    st.markdown("**Format breakdown** (derived from leader bytes 06/07).")
    if format_counter:
        format_df = pd.DataFrame(
            sorted(format_counter.items(), key=lambda kv: (-kv[1], kv[0])),
            columns=["format", "records"],
        )
        chart_col, table_col = st.columns([2, 1])
        chart_col.bar_chart(format_df.set_index("format"), height=220)
        table_col.dataframe(
            format_df,
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("No format data available.")

    st.markdown("**Missing-field rollup**")
    default_check = [
        t for t in ("001", "245", "856")
        if t in tag_counter or t in {"001", "245", "856"}
    ]
    check_tags = st.multiselect(
        "Check for records missing these tags",
        options=sorted(set(tag_counter) | {"001", "245", "856"}),
        default=default_check,
        help=(
            "For each selected tag, count the records where that tag does "
            "not appear at least once."
        ),
        key="report_check_tags",
    )

    if check_tags:
        rows = []
        for tag in check_tags:
            missing = sum(
                1 for snap in snapshots if snap.tags_present.get(tag, 0) == 0
            )
            rows.append({
                "tag": tag,
                "missing": missing,
                "of total": total,
                "missing %": f"{(missing / total * 100):.1f}%" if total else "—",
            })
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("Select one or more tags to see the missing-field counts.")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Top tags** (across all records)")
        if tag_counter:
            top_tags = pd.DataFrame(
                sorted(tag_counter.items(), key=lambda kv: (-kv[1], kv[0])),
                columns=["tag", "count"],
            )
            st.dataframe(
                top_tags, hide_index=True, use_container_width=True, height=280,
            )
        else:
            st.caption("No tags found in this batch.")

    with col_right:
        st.markdown("**Top 856 URL domains**")
        if url_domain_counter:
            url_df = pd.DataFrame(
                sorted(url_domain_counter.items(), key=lambda kv: (-kv[1], kv[0])),
                columns=["domain", "count"],
            )
            st.dataframe(
                url_df, hide_index=True, use_container_width=True, height=280,
            )
        else:
            st.caption("No 856 URLs found in this batch.")

    st.divider()
    st.subheader("Per record")

    per_record_df = pd.DataFrame(
        [
            {
                "index": snap.index,
                "identifier": snap.identifier or "—",
                "OCLC #": snap.oclc_number or "",
                "title": (snap.title or "")[:120],
                "format": snap.format_label,
                "ldr 06": snap.leader_06,
                "ldr 07": snap.leader_07,
                "tag count": sum(snap.tags_present.values()),
            }
            for snap in snapshots
        ]
    )

    st.dataframe(
        per_record_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "index": st.column_config.NumberColumn("Record #", width="small"),
            "identifier": st.column_config.TextColumn("Identifier", width="medium"),
            "OCLC #": st.column_config.TextColumn("OCLC #", width="medium"),
            "title": st.column_config.TextColumn("Title", width="large"),
            "format": st.column_config.TextColumn("Format", width="small"),
            "ldr 06": st.column_config.TextColumn("LDR 06", width="small"),
            "ldr 07": st.column_config.TextColumn("LDR 07", width="small"),
            "tag count": st.column_config.NumberColumn("Tags", width="small"),
        },
    )
