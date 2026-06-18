"""Marc Tools — conversion hub render module.

Four target formats: MarcEdit ``.mrk``, MARC binary ``.mrc``,
MARCXML, and CSV preview/export. The cataloger picks the target via
radio; the form below switches to match. Sources are either an
uploaded file or the loaded session batch (when one is present).

Each successful conversion emits a ``conversion-issued`` audit event
so the security log captures what data left the box in which shape.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import pandas as pd
import pymarc
import streamlit as st

from marcedit_web.lib import converters, quotas, session
from marcedit_web.lib.audit import audit_event


@dataclass
class _Source:
    """Deferred-materialize source for a Marc Tools conversion.

    ``materialize()`` is only called inside the Convert button block,
    so:

    * the session batch isn't serialized to bytes just because the
      cataloger opened the Marc Tools page (TASK-035 fix);
    * the ``upload-accepted`` audit event fires once per conversion
      attempt, not once per Streamlit rerun (TASK-035 fix).

    For ``kind == "upload"``, materialize hands back the bytes
    Streamlit already holds AND emits the audit event. For ``kind ==
    "session"``, materialize streams the live :class:`RecordStore` to
    bytes inside the click handler.
    """

    kind: str           # "upload" or "session"
    name: str           # filename or "session-batch"
    size: int           # bytes count (precomputed cheaply for both)
    materialize: Callable[[], bytes]


_TARGETS: list[tuple[str, str]] = [
    ("mrk", "MarcEdit .mrk (mnemonic text)"),
    ("mrc", "MARC binary .mrc"),
    ("xml", "MARCXML"),
    ("csv", "CSV (preview + export)"),
]


def render() -> None:
    """Render the Marc Tools page."""
    st.title("Marc Tools")
    st.caption(
        "Convert between MARC binary `.mrc`, MarcEdit `.mrk` text, "
        "MARCXML, and tabular CSV. Source is either an uploaded file "
        "or the records currently loaded on Home."
    )

    target = st.radio(
        "Convert to",
        options=[k for k, _ in _TARGETS],
        format_func=lambda k: dict(_TARGETS)[k],
        horizontal=True,
        key="marc_tools_target",
    )

    st.divider()

    if target == "mrk":
        _convert_to_mrk()
    elif target == "mrc":
        _convert_to_binary()
    elif target == "xml":
        _convert_to_xml()
    elif target == "csv":
        _render_csv()


# ---------------------------------------------------------------------------
# Source pickers
# ---------------------------------------------------------------------------


def _binary_source(*, key_prefix: str) -> _Source | None:
    """File uploader for binary .mrc + session-batch radio.

    Returns a deferred-materialize :class:`_Source`. The actual
    serialization (for session) or in-memory hand-back (for upload)
    runs only when ``materialize()`` is called inside the convert
    handler's button block.
    """
    use_session = _session_radio(key_prefix)
    if use_session == "session":
        store = session.current_store()
        if store is None:
            st.info("No file loaded on **Home**. Switch to upload above.")
            return None

        def materialize_session() -> bytes:
            # Streams to BytesIO inside the click handler — no
            # serialization on page render.
            bio = io.BytesIO()
            writer = pymarc.MARCWriter(bio)
            for r in store.iter_records():
                writer.write(r)
            return bio.getvalue()

        return _Source(
            kind="session",
            name=session.current_filename() or "session-batch",
            size=0,  # unknown until materialized; UI shows "(session)" instead
            materialize=materialize_session,
        )

    upload = st.file_uploader(
        "MARC binary file (.mrc / .marc)",
        type=["mrc", "marc"],
        key=f"{key_prefix}_uploader",
    )
    return _check_upload(upload, kind="upload")


def _mrk_source(*, key_prefix: str) -> _Source | None:
    upload = st.file_uploader(
        "MarcEdit .mrk text file",
        type=["mrk", "txt"],
        key=f"{key_prefix}_uploader",
    )
    return _check_upload(upload, kind="upload")


def _xml_source(*, key_prefix: str) -> _Source | None:
    upload = st.file_uploader(
        "MARCXML file (.xml)",
        type=["xml"],
        key=f"{key_prefix}_uploader",
    )
    return _check_upload(upload, kind="upload")


def _session_radio(key_prefix: str) -> str:
    """Radio between 'upload a file' and 'use loaded session batch'.

    Only shows the session option when a batch is loaded; otherwise
    upload is the only choice.
    """
    if not session.has_upload():
        return "upload"
    return st.radio(
        "Source",
        options=["session", "upload"],
        format_func=lambda k: (
            f"Use loaded session batch "
            f"({session.record_count()} records)"
            if k == "session"
            else "Upload a file"
        ),
        horizontal=True,
        key=f"{key_prefix}_source_radio",
    )


def _check_upload(upload, *, kind: str) -> _Source | None:
    """Validate the uploaded file at render time; defer accept-audit.

    Render-time work:

    * Run the per-feature size cap (``quotas.check_upload``). A
      rejection still emits ``upload-rejected`` immediately + shows
      the user a visible error — the cataloger needs that feedback
      before they click Convert.

    Deferred to ``materialize()`` (i.e. Convert click):

    * The ``upload-accepted`` audit event. Streamlit reruns the page
      script on every interaction; emitting accept here would add an
      audit row per radio toggle / target switch, swamping the log.
      The convert handler invokes ``materialize()`` exactly once per
      conversion attempt, which is the natural granularity for an
      audit row.
    """
    if upload is None:
        return None
    raw = upload.getvalue()  # Streamlit already holds these bytes
    size = len(raw)
    name = upload.name
    user = session.current_user_id()
    try:
        quotas.check_upload(size, kind=kind)
    except quotas.QuotaExceeded as exc:
        audit_event(
            "upload-rejected",
            user=user,
            source="marc-tools",
            filename=name,
            size=size,
            reason=exc.kind,
            limit=exc.limit,
        )
        st.error(f"`{name}` rejected: {exc}")
        return None

    def materialize_upload() -> bytes:
        audit_event(
            "upload-accepted",
            user=user,
            source="marc-tools",
            filename=name,
            size=size,
        )
        return raw

    return _Source(
        kind="upload",
        name=name,
        size=size,
        materialize=materialize_upload,
    )


# ---------------------------------------------------------------------------
# Conversion handlers
# ---------------------------------------------------------------------------


def _convert_to_mrk() -> None:
    st.header("Convert binary `.mrc` → MarcEdit `.mrk`")
    src = _binary_source(key_prefix="tools_mrc_to_mrk")
    if src is None:
        return
    if st.button("Convert to .mrk", type="primary", key="tools_to_mrk_btn"):
        raw = src.materialize()  # serialize / audit happens here, not on render
        with st.spinner("Converting to .mrk…"):
            result = converters.to_mrk_text(raw)
        _show_preflight(result)
        if isinstance(result.output, str) and result.output:
            fname = session.stamped_filename("records", ".mrk")
            st.download_button(
                f"⬇ Download {fname}",
                data=result.output.encode("utf-8"),
                file_name=fname,
                mime="text/plain",
                key="tools_dl_mrk",
            )
            _audit_conversion("mrc_to_mrk", len(raw),
                              len(result.output.encode("utf-8")))


def _convert_to_binary() -> None:
    st.header("Convert to MARC binary `.mrc`")
    sub_target = st.radio(
        "From",
        options=["mrk", "xml"],
        format_func=lambda k: (
            "MarcEdit `.mrk` text" if k == "mrk" else "MARCXML"
        ),
        horizontal=True,
        key="tools_to_mrc_subtarget",
    )
    if sub_target == "mrk":
        src = _mrk_source(key_prefix="tools_mrk_to_mrc")
        if src is None:
            return
        if st.button("Convert to .mrc", type="primary",
                     key="tools_mrk_to_mrc_btn"):
            raw = src.materialize()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            with st.spinner("Converting .mrk → .mrc…"):
                result = converters.to_binary_from_mrk(text)
            _show_preflight(result)
            _show_line_errors(result.line_errors)
            if result.output:
                _offer_download_binary(result.output, len(raw))
                _audit_conversion("mrk_to_mrc", len(raw), len(result.output))
    else:
        src = _xml_source(key_prefix="tools_xml_to_mrc")
        if src is None:
            return
        if st.button("Convert to .mrc", type="primary",
                     key="tools_xml_to_mrc_btn"):
            raw = src.materialize()
            try:
                with st.spinner("Converting MARCXML → .mrc…"):
                    result = converters.to_binary_from_marcxml(raw)
            except ValueError as exc:
                st.error(f"MARCXML parse error: {exc}")
                return
            _show_preflight(result)
            if result.output:
                _offer_download_binary(result.output, len(raw))
                _audit_conversion("xml_to_mrc", len(raw), len(result.output))


def _convert_to_xml() -> None:
    st.header("Convert binary `.mrc` → MARCXML")
    src = _binary_source(key_prefix="tools_mrc_to_xml")
    if src is None:
        return
    if st.button("Convert to MARCXML", type="primary", key="tools_to_xml_btn"):
        raw = src.materialize()
        with st.spinner("Converting to MARCXML…"):
            result = converters.to_marcxml(raw)
        _show_preflight(result)
        if result.output:
            fname = session.stamped_filename("records", ".xml")
            st.download_button(
                f"⬇ Download {fname}",
                data=result.output,
                file_name=fname,
                mime="application/xml",
                key="tools_dl_xml",
            )
            _audit_conversion("mrc_to_xml", len(raw), len(result.output))


def _render_csv() -> None:
    st.header("CSV preview + export")
    st.caption(
        "Flatten records to a tabular view for spreadsheets / audit. "
        "This is one-way — the CSV doesn't round-trip back to MARC."
    )
    src = _binary_source(key_prefix="tools_csv")
    if src is None:
        return
    if st.button("Build CSV", type="primary", key="tools_csv_btn"):
        raw = src.materialize()
        with st.spinner("Flattening records to CSV…"):
            records, malformed = converters._read_binary(raw)
            rows = converters.records_to_csv_rows(iter(records))
        col_names = [c for c, _t, _s in converters.DEFAULT_CSV_COLUMNS]
        st.caption(
            f"**{len(records)}** record(s) flattened to "
            f"**{len(col_names)}** column(s)"
            + (f"; **{malformed}** malformed records skipped" if malformed else "")
        )
        st.dataframe(
            pd.DataFrame(rows, columns=col_names),
            hide_index=True,
            use_container_width=True,
        )
        csv_text = converters.write_csv(rows, columns=col_names)
        fname = session.stamped_filename("records", ".csv")
        st.download_button(
            f"⬇ Download {fname}",
            data=csv_text.encode("utf-8"),
            file_name=fname,
            mime="text/csv",
            key="tools_dl_csv",
        )
        _audit_conversion("mrc_to_csv", len(raw), len(csv_text.encode("utf-8")))


# ---------------------------------------------------------------------------
# Shared UI helpers
# ---------------------------------------------------------------------------


def _show_preflight(result: converters.ConversionResult) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Records", result.record_count)
    c2.metric("Malformed (skipped)", result.malformed_count)
    c3.metric("Output bytes",
              len(result.output) if isinstance(result.output, (bytes, bytearray))
              else len(result.output.encode("utf-8")))


def _show_line_errors(line_errors) -> None:
    if not line_errors:
        return
    with st.expander(
        f"Line-pinned errors ({len(line_errors)})",
        expanded=any(e.code in {"missing-leader", "no-tag-prefix",
                                "bad-line", "encoding"} for e in line_errors),
    ):
        for e in line_errors[:50]:
            st.error(f"line {e.line_no}: {e.code} — {e.message}")
        if len(line_errors) > 50:
            st.caption(f"…and {len(line_errors) - 50} more")


def _offer_download_binary(blob: bytes, source_bytes: int) -> None:
    fname = session.stamped_filename("records")
    st.download_button(
        f"⬇ Download {fname}",
        data=blob,
        file_name=fname,
        mime="application/marc",
        key=f"tools_dl_mrc_{stamp}",
    )


def _audit_conversion(kind: str, source_bytes: int, output_bytes: int) -> None:
    user = session.current_user_id()
    audit_event(
        "conversion-issued",
        user=user,
        conversion=kind,
        source_bytes=source_bytes,
        output_bytes=output_bytes,
    )
