"""Report tab — rollups across the loaded batch + per-record table."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from marcedit_web.lib import session
from marcedit_web.lib.reporting import RecordSnapshot


def render() -> None:
    """Render the Report tab into the current Streamlit container."""
    if not session.require_upload("see reports"):
        return

    store = session.current_store()
    malformed = store.malformed_count() if store else 0

    # Stage 16: stream the batch once. We build the aggregates AND the
    # slim per-record dicts in a single pass so a 100K-record batch never
    # materializes 100K pymarc.Record objects all at the same time.
    format_counter: Counter = Counter()
    tag_counter: Counter = Counter()
    url_domain_counter: Counter = Counter()
    # Per-tag "how many records have this tag at least once" — drives the
    # missing-field rollup below without keeping each snapshot in memory.
    tag_record_presence: Counter = Counter()
    # TASK-033 aggregates — same single-pass model.
    subfield_counter: Counter = Counter()   # keyed by (tag, code)
    language_counter: Counter = Counter()    # 008 bytes 35–37
    date_counter: Counter = Counter()        # 008 bytes 07–10
    local_tag_counter: Counter = Counter()   # 900–999
    per_record_rows: list[dict] = []

    total = 0
    if store is not None:
        for i, record in enumerate(store.iter_records(), start=1):
            total = i
            snap = RecordSnapshot.of(record, i)
            format_counter[snap.format_label] += 1
            tag_counter.update(snap.tags_present)
            url_domain_counter.update(snap.url_domains)
            tag_record_presence.update(snap.tags_present.keys())
            per_record_rows.append({
                "index": snap.index,
                "identifier": snap.identifier or "—",
                "OCLC #": snap.oclc_number or "",
                "title": (snap.title or "")[:120],
                "format": snap.format_label,
                "ldr 06": snap.leader_06,
                "ldr 07": snap.leader_07,
                "tag count": sum(snap.tags_present.values()),
            })
            # TASK-033 streaming aggregates — walk fields once,
            # update every counter. The Record stays in scope only
            # for this loop iteration so 100K records still work.
            for f in record.fields:
                tag = f.tag
                if "900" <= tag <= "999":
                    local_tag_counter[tag] += 1
                if f.is_control_field():
                    continue
                for sf in f.subfields:
                    subfield_counter[(tag, sf.code)] += 1
            field_008 = record.get("008")
            if field_008 is not None and field_008.data:
                data = field_008.data
                if len(data) >= 11:
                    date = data[7:11].strip()
                    if date:
                        date_counter[date] += 1
                if len(data) >= 38:
                    lang = data[35:38].strip()
                    if lang:
                        language_counter[lang] += 1
            # Snapshot drops out of scope on next iteration — no list of
            # snapshots is retained.

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
        _csv_download(format_df, "format_breakdown",
                      key="report_csv_format")
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
            # `tag_record_presence[tag]` counts records that had the tag at
            # least once. Missing = total - present, which dodges the
            # per-record snapshot list the v1 code held in memory.
            missing = total - tag_record_presence.get(tag, 0)
            rows.append({
                "tag": tag,
                "missing": missing,
                "of total": total,
                "missing %": f"{(missing / total * 100):.1f}%" if total else "—",
            })
        missing_df = pd.DataFrame(rows)
        st.dataframe(
            missing_df,
            hide_index=True,
            use_container_width=True,
        )
        _csv_download(missing_df, "missing_fields",
                      key="report_csv_missing")
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
            _csv_download(top_tags, "top_tags", key="report_csv_tags")
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
            _csv_download(url_df, "url_domains", key="report_csv_urls")
        else:
            st.caption("No 856 URLs found in this batch.")

    st.divider()
    st.subheader("Per record")

    per_record_df = pd.DataFrame(per_record_rows)

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
    _csv_download(per_record_df, "per_record", key="report_csv_per_record")

    # --- TASK-033 expanders ---------------------------------------------

    st.divider()
    st.subheader("More reports")
    st.caption(
        "Additional pre-edit audit views. Each section can be exported "
        "to CSV for spreadsheet review or stakeholder sign-off."
    )

    with st.expander(
        f"Subfield frequency ({len(subfield_counter):,} distinct (tag, code) pairs)",
        expanded=False,
    ):
        if subfield_counter:
            sub_rows = [
                {"tag": tag, "subfield": code, "count": count}
                for (tag, code), count in sorted(
                    subfield_counter.items(),
                    key=lambda kv: (-kv[1], kv[0][0], kv[0][1]),
                )
            ]
            sub_df = pd.DataFrame(sub_rows)
            st.dataframe(sub_df, hide_index=True, use_container_width=True,
                         height=320)
            _csv_download(sub_df, "subfield_frequency",
                          key="report_csv_subfield")
        else:
            st.caption("No subfields found in this batch.")

    with st.expander(
        f"Publication date distribution ({len(date_counter):,} distinct dates)",
        expanded=False,
    ):
        if date_counter:
            date_rows = sorted(date_counter.items(), key=lambda kv: kv[0])
            date_df = pd.DataFrame(date_rows, columns=["date", "records"])
            chart_col, table_col = st.columns([2, 1])
            chart_col.bar_chart(
                date_df.set_index("date"),
                height=240,
            )
            table_col.dataframe(
                date_df.sort_values("records", ascending=False),
                hide_index=True, use_container_width=True, height=240,
            )
            _csv_download(date_df, "pub_date_distribution",
                          key="report_csv_dates")
        else:
            st.caption(
                "No publishable dates found in 008 bytes 07–10 across this batch."
            )

    with st.expander(
        f"Language distribution ({len(language_counter):,} distinct codes)",
        expanded=False,
    ):
        if language_counter:
            lang_rows = sorted(
                language_counter.items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
            lang_df = pd.DataFrame(lang_rows, columns=["lang code", "records"])
            st.dataframe(lang_df, hide_index=True, use_container_width=True,
                         height=240)
            _csv_download(lang_df, "language_distribution",
                          key="report_csv_languages")
        else:
            st.caption(
                "No language codes found in 008 bytes 35–37 across this batch."
            )

    with st.expander(
        f"Local tags 9XX ({len(local_tag_counter):,} distinct tags)",
        expanded=False,
    ):
        if local_tag_counter:
            local_rows = sorted(
                local_tag_counter.items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
            local_df = pd.DataFrame(local_rows, columns=["tag", "count"])
            st.dataframe(local_df, hide_index=True,
                         use_container_width=True, height=240)
            st.caption(
                "9XX tags are typically institution-local. Review before "
                "exporting to vendors / discovery services."
            )
            _csv_download(local_df, "local_tags_9XX",
                          key="report_csv_local")
        else:
            st.caption("No 9XX local tags found in this batch.")


def _csv_download(df: pd.DataFrame, section: str, *, key: str) -> None:
    """Render a ``Download <section>.csv`` button for a report dataframe.

    The CSV is materialized only when the button is clicked
    (``df.to_csv`` is cheap), but the button widget itself eagerly
    builds the payload — small report DataFrames make this fine.
    """
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"report_{section}_{stamp}.csv"
    st.download_button(
        f"⬇ Download {fname}",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=fname,
        mime="text/csv",
        key=key,
    )
