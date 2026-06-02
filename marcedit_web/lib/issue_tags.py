"""Map an :class:`Issue` back to the MARC tag it describes.

Most preflight and rule-validation issue codes encode the field
tag implicitly: either in the code itself (``missing-245``,
``duplicate-001``) or at the start of the message
(``"245 ind1 = ' '..."``). Surfaces that want to highlight the
offending line (the Validate page's record modal, the inline
editor's Ace gutter) need that tag pulled back out.

This is a thin pure helper rather than something embedded on
:class:`Issue` because (a) Issues are immutable / serializable
and we don't want to bloat the JSON-report payload, and (b) the
mapping is page-render concern, not a piece of the diagnostic
itself.
"""

from __future__ import annotations

import re

from .errors import Issue


# Stable issue codes that don't put the MARC tag in the message
# map to their tag here. The helper falls back to regex sweeps of
# the message for codes (mostly ``rule-*``) whose messages do
# carry the tag in their prose.
_CODE_TO_TAG: dict[str, str] = {
    "leader-length-invalid": "LDR",
    "missing-001": "001",
    "duplicate-001": "001",
    "missing-245": "245",
    "rule-missing-245": "245",
    "missing-856": "856",
    "empty-856-u": "856",
    "duplicate-oclc-035": "035",
    "duplicate-lccn-010": "010",
}

# ``rule-*`` checks construct messages like ``"245 ind1 = ' '..."``,
# ``"500 $x is not in..."`` — the tag is the first token. The
# ``tag '500'`` variant covers ``rule-unknown-tag`` and the
# repeatability checks.
_TAG_AT_START = re.compile(r"^(\d{3})\b")
_TAG_QUOTED = re.compile(r"tag ['\"](\d{3})['\"]")


def tag_for_issue(issue: Issue) -> str | None:
    """Return the MARC tag the issue refers to, or ``None``.

    Returns ``None`` for file-scope checks (``record-count``,
    ``no-records``) and for record-wide checks
    (``rule-only-one-1xx``) whose "tag" isn't a single field
    line — callers should treat ``None`` as "no specific line to
    point at."
    """
    tag = _CODE_TO_TAG.get(issue.code)
    if tag:
        return tag
    m = _TAG_AT_START.match(issue.message)
    if m:
        return m.group(1)
    m = _TAG_QUOTED.search(issue.message)
    if m:
        return m.group(1)
    return None
