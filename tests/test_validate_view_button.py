"""Tests for the Validate page's View-button helpers (TASK-055).

Two pieces are testable without booting Streamlit:

* ``_tag_for_issue`` — pure function from ``Issue`` to MARC tag.
  Drives the highlight feature in the record modal.
* ``_record_modal._render_mrk_highlighted`` — calls into
  ``st.markdown`` for layout, so we intercept that call instead of
  asserting on rendered HTML directly. The HTML payload is
  inspected for the expected shading on the matching ``=TAG`` line
  and plain rendering for the others.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from marcedit_web.lib.errors import Issue
from marcedit_web.render import _record_modal
from marcedit_web.render.validate import _tag_for_issue


# ---------------------------------------------------------------------------
# _tag_for_issue
# ---------------------------------------------------------------------------


def _make_issue(code: str, message: str, severity: str = "warning") -> Issue:
    return Issue(
        severity=severity,  # type: ignore[arg-type]
        scope="record",
        code=code,
        message=message,
        record_index=1,
    )


@pytest.mark.parametrize(
    "code, expected",
    [
        ("leader-length-invalid", "LDR"),
        ("missing-001", "001"),
        ("duplicate-001", "001"),
        ("missing-245", "245"),
        ("rule-missing-245", "245"),
        ("missing-856", "856"),
        ("empty-856-u", "856"),
        ("duplicate-oclc-035", "035"),
        ("duplicate-lccn-010", "010"),
    ],
)
def test_tag_for_issue_resolves_preflight_codes(code: str, expected: str):
    # The preflight + cross-record codes don't put the tag in the
    # message in a regex-friendly way, so we lean on the code map.
    issue = _make_issue(code, "irrelevant message text")
    assert _tag_for_issue(issue) == expected


def test_tag_for_issue_picks_up_tag_at_message_start():
    # ``rule-bad-indicator`` / ``rule-bad-subfield`` /
    # ``rule-length-mismatch`` all start the message with the tag.
    issue = _make_issue("rule-bad-indicator", "245 ind1 = ' '; allowed: '0', '1'")
    assert _tag_for_issue(issue) == "245"


def test_tag_for_issue_picks_up_quoted_tag_in_message():
    # ``rule-unknown-tag`` / ``rule-tag-nonrepeatable`` put the tag in
    # quotes mid-message.
    issue = _make_issue(
        "rule-unknown-tag",
        "tag '500' has no entry in marc-rules.txt",
    )
    assert _tag_for_issue(issue) == "500"


def test_tag_for_issue_returns_none_for_record_wide_check():
    # ``rule-only-one-1xx`` — the "tag" is "1XX", not a specific
    # field line, so we can't highlight one line.
    issue = _make_issue(
        "rule-only-one-1xx",
        "marc-rules.txt declares only one 1XX is allowed; record has 2",
    )
    assert _tag_for_issue(issue) is None


def test_tag_for_issue_returns_none_for_file_scope_checks():
    # ``record-count`` / ``no-records`` / ``malformed-records`` etc.
    # describe the file, not a tag.
    issue = Issue(
        severity="info",
        scope="file",
        code="record-count",
        message="42 parseable records",
    )
    assert _tag_for_issue(issue) is None


# ---------------------------------------------------------------------------
# _render_mrk_highlighted
# ---------------------------------------------------------------------------


_SAMPLE_MRK = (
    "=LDR  00000nam a2200000 a 4500\n"
    "=001  ocm12345\n"
    "=245  10$aTitle :$bsubtitle /$cby Author.\n"
    "=500  $aA general note."
)


def _captured_html(highlight_tag: str, severity: str | None = "warning") -> str:
    # ``st.markdown`` is the only Streamlit call we make; capture
    # its single positional arg for assertion.
    with patch.object(_record_modal.st, "markdown") as md:
        _record_modal._render_mrk_highlighted(
            _SAMPLE_MRK, highlight_tag, severity
        )
    assert md.call_count == 1
    args, kwargs = md.call_args
    assert kwargs.get("unsafe_allow_html") is True
    return args[0]


def test_render_mrk_highlights_matching_field_tag():
    html = _captured_html("245", "warning")
    # The 245 line should be wrapped with the warning-colored span.
    assert "background:#fff3cd" in html
    # And the literal 245 line content must appear escaped inside it.
    assert "=245  10$aTitle :$bsubtitle /$cby Author." in html
    # The non-matching 001 / 500 / LDR lines must NOT be inside a
    # highlight wrapper.
    assert html.count("background:#fff3cd") == 1


def test_render_mrk_highlights_ldr_when_requested():
    # Leader matching uses the literal ``=LDR  `` prefix; make sure
    # the helper picks it up even though it's not a 3-digit tag.
    html = _captured_html("LDR", "error")
    assert "background:#fde2e2" in html  # error-themed bg
    assert html.count("background:#fde2e2") == 1


def test_render_mrk_does_not_highlight_partial_tag_collision():
    # ``=001`` should NOT match a highlight request for ``=00`` —
    # the helper requires the tag prefix to be followed by
    # whitespace or end-of-line.
    html = _captured_html("00", "warning")
    # No line genuinely starts with ``=00`` + whitespace, so the
    # warning background should not appear anywhere.
    assert "background:#fff3cd" not in html


def test_render_mrk_severity_defaults_to_warning_when_missing():
    # ``highlight_severity=None`` should fall back to warning colors
    # rather than crashing on a None lookup.
    html = _captured_html("001", None)
    assert "background:#fff3cd" in html
