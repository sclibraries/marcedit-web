"""View tab — render a single record as `.mrk` with help lookup."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import help_lookup, rules as rules_mod, session, tooltips, viewer


def render(rule_set: rules_mod.RuleSet | None = None) -> None:
    """Render the View tab into the current Streamlit container."""
    if not session.has_upload():
        st.info(
            "Upload a `.mrc` file on **Home** to view records here. "
            "View reads records already in this session."
        )
        return

    store = session.current_store()
    total = store.count() if store else 0
    if total == 0:
        st.warning("The loaded file produced no parseable records.")
        return

    if rule_set is None:
        from marcedit_web.render import rules_for_page
        rule_set = rules_for_page()

    # Navigator state survives reruns in session_state.
    if (
        "view_index" not in st.session_state
        or st.session_state["view_index"] > total
        or st.session_state["view_index"] < 1
    ):
        st.session_state["view_index"] = 1

    def _step(delta: int) -> None:
        current = int(st.session_state.get("view_index", 1))
        nxt = current + delta
        if nxt < 1:
            nxt = 1
        elif nxt > total:
            nxt = total
        st.session_state["view_index"] = nxt

    nav_a, nav_b, nav_c, nav_d = st.columns([1, 3, 1, 1])
    with nav_a:
        st.button(
            "◀ Prev",
            on_click=_step,
            args=(-1,),
            disabled=st.session_state["view_index"] <= 1,
            use_container_width=True,
        )
    with nav_b:
        st.number_input(
            "Record #",
            min_value=1,
            max_value=total,
            step=1,
            key="view_index",
            label_visibility="collapsed",
        )
    with nav_c:
        st.button(
            "Next ▶",
            on_click=_step,
            args=(1,),
            disabled=st.session_state["view_index"] >= total,
            use_container_width=True,
        )
    with nav_d:
        st.caption(f"of **{total}**")

    index = int(st.session_state["view_index"])
    record = store.get(index - 1)
    if record is None:
        st.warning(f"Record {index} not found.")
        return
    identifier = viewer.record_identifier(record)
    title = viewer.record_title(record) or "(no 245 $a)"
    st.markdown(
        f"**Record {index} of {total}** — `{identifier}` — {title}"
    )

    # --- Field help expander -----------------------------------------------

    with st.expander("Field help", expanded=False):
        st.caption(
            "Look up a tag, subfield, or byte position against "
            "`data/marc-rules.txt`. Coverage depends on what `:help` / "
            "`:byte` directives have been added to the rules file — start "
            "with `008 byte 28` for the canonical example."
        )

        tags_in_record: list[str] = []
        seen: set[str] = set()
        for f in record.fields:
            if f.tag not in seen:
                tags_in_record.append(f.tag)
                seen.add(f.tag)
        tag_options = ["LDR"] + tags_in_record

        hc_tag, hc_sub, hc_byte, hc_clear = st.columns([2, 1, 1, 1])
        help_tag = hc_tag.selectbox(
            "Tag",
            options=tag_options,
            key="help_tag",
        )

        is_control = help_tag == "LDR" or (
            len(help_tag) == 3
            and help_tag.isdigit()
            and help_tag.startswith("00")
            and help_tag != "000"
        )

        help_subfield = hc_sub.text_input(
            "Subfield code",
            max_chars=1,
            placeholder="a",
            key="help_subfield",
            disabled=is_control,
            help=(
                "Single character. Disabled for control fields and the leader; "
                "use the byte input on the right instead."
            ),
        )

        help_byte_raw = hc_byte.text_input(
            "Byte position",
            placeholder="28",
            key="help_byte",
            disabled=not is_control,
            help=(
                "Zero-based byte position. Only meaningful for LDR, 006, 007, "
                "008 (and other control fields)."
            ),
        )

        if hc_clear.button("Clear", key="help_clear_btn"):
            st.session_state.pop("help_subfield", None)
            st.session_state.pop("help_byte", None)
            st.rerun()

        byte_position: int | None = None
        if is_control and help_byte_raw.strip():
            try:
                byte_position = int(help_byte_raw.strip())
            except ValueError:
                st.warning(f"`{help_byte_raw!r}` is not a number; ignoring.")

        entry = help_lookup.help_for(
            rule_set,
            tag=help_tag,
            subfield=(help_subfield or None) if not is_control else None,
            byte=byte_position,
        )
        st.markdown(tooltips.render_help_entry(entry), unsafe_allow_html=True)

    # --- Tag filter -------------------------------------------------------

    with st.expander("Filter fields", expanded=False):
        show_leader = st.checkbox(
            "Show leader (LDR)",
            value=True,
            help="When unchecked, the leader line is omitted from the output.",
            key="view_show_leader",
        )
        tags_input = st.text_input(
            "Tags (blank = all)",
            placeholder="e.g. 035, 856 — comma or space separated",
            help=(
                "Filter to specific 3-character tags. Combine with the leader "
                "checkbox above. Blank field means: render every tag."
            ),
            key="view_tags_input",
        )

    tag_filter: set[str] | None = None
    if tags_input.strip():
        try:
            tag_filter = viewer.parse_fields(tags_input)
        except ValueError as exc:
            st.warning(f"Could not parse tag filter: {exc}")
            tag_filter = None
        else:
            if show_leader:
                tag_filter.add("LDR")
    elif not show_leader:
        tag_filter = {f.tag for f in record.fields}

    text = viewer.render_record(record, fields=tag_filter)
    st.code(text, language="text")
