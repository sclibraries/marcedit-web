"""Lossless parsing for the reviewed external MARC field syntax."""

from __future__ import annotations

import re
from typing import Any, Mapping


_FIELD_RE = re.compile(r"^=(\d{3})  (.{2})(.*)$")
_REFERENCE_RE = re.compile(r"\{(\d{3})(?:\$([a-z0-9]))?\}")
_LEADER_CONDITIONS = {
    "=LDR.{8}[amt][m].+": "books",
    "=LDR.{9}s.+": "serials",
    "=LDR.{9}i.+": "databases",
    "=LDR.{8}[e,f].+": "maps",
    "=LDR.{8}g.+": "videos",
    "=LDR.{8}[i,j].+": "audios",
    "=LDR.{8}[c,d].+": "scores",
}


def _parse_field(value: str) -> tuple[str, str, str, list[list[str]]]:
    match = _FIELD_RE.fullmatch(value)
    if match is None:
        if value.startswith("=") and len(value) >= 4:
            raise ValueError("field tag must be exactly three numeric characters")
        raise ValueError("field must use '=TAG  II$codevalue' mnemonic syntax")
    tag, indicators, payload = match.groups()
    ind1, ind2 = (
        " " if indicator == "\\" else indicator
        for indicator in indicators
    )
    if not payload:
        raise ValueError("field needs at least one subfield")
    subfields: list[list[str]] = []
    offset = 0
    while offset < len(payload):
        if payload[offset] != "$":
            raise ValueError("field data must begin with a subfield marker")
        if offset + 1 >= len(payload):
            raise ValueError("incomplete subfield marker")
        code = payload[offset + 1]
        if re.fullmatch(r"[a-z0-9]", code) is None:
            raise ValueError("subfield marker needs a lowercase letter or digit")
        end = offset + 2
        brace_depth = 0
        while end < len(payload):
            character = payload[end]
            if character == "{":
                brace_depth += 1
            elif character == "}" and brace_depth:
                brace_depth -= 1
            elif character == "$" and brace_depth == 0:
                break
            end += 1
        content = payload[offset + 2 : end]
        if end < len(payload) and (
            end + 1 >= len(payload)
            or re.fullmatch(r"[a-z0-9]", payload[end + 1]) is None
        ):
            raise ValueError("incomplete subfield marker")
        subfields.append([code, content])
        offset = end
    return tag, ind1, ind2, subfields


def parse_mnemonic_field(value: str) -> dict[str, Any]:
    """Parse one exact external mnemonic field without changing its text."""

    tag, ind1, ind2, subfields = _parse_field(value)
    return {
        "tag": tag,
        "ind1": ind1,
        "ind2": ind2,
        "subfields": subfields,
    }


def _parse_segments(value: str) -> list[dict[str, str]]:
    if re.search(r"\[x\]", value, re.IGNORECASE):
        raise ValueError("multi-field [x] references are unsupported")
    segments: list[dict[str, str]] = []
    offset = 0
    for match in _REFERENCE_RE.finditer(value):
        if match.start() > offset:
            literal = value[offset : match.start()]
            if "{" in literal or "}" in literal:
                raise ValueError("unsupported brace or function syntax")
            segments.append({"type": "text", "value": literal})
        tag, code = match.groups()
        if code is None:
            if not tag.startswith("00") or tag == "000":
                raise ValueError(
                    "data-field references must name a subfield code"
                )
            segments.append({"type": "control_field", "tag": tag})
        else:
            if tag.startswith("00"):
                raise ValueError("control-field references cannot name a subfield")
            segments.append({
                "type": "data_subfield",
                "tag": tag,
                "code": code,
            })
        offset = match.end()
    remainder = value[offset:]
    if "{" in remainder or "}" in remainder:
        raise ValueError("unsupported brace or function syntax")
    if remainder or not segments:
        segments.append({"type": "text", "value": remainder})
    return segments


def parse_build_template(value: str) -> dict[str, Any]:
    """Parse a reviewed Build Field template into typed source segments."""

    if re.search(r"\[x\]", value, re.IGNORECASE):
        raise ValueError("multi-field [x] references are unsupported")
    tag, ind1, ind2, subfields = _parse_field(value)
    return {
        "tag": tag,
        "ind1": ind1,
        "ind2": ind2,
        "structured_subfields": [
            [code, _parse_segments(text)] for code, text in subfields
        ],
    }


def _external_indicator(value: object) -> str:
    return "\\" if str(value or " ") == " " else str(value)


def render_external_field(field: Mapping[str, Any]) -> str:
    """Render one parsed field back to exact external mnemonic syntax."""

    prefix = "={0}  {1}{2}".format(
        field["tag"],
        _external_indicator(field.get("ind1", " ")),
        _external_indicator(field.get("ind2", " ")),
    )
    if "structured_subfields" not in field:
        return prefix + "".join(
            "${0}{1}".format(code, value)
            for code, value in field.get("subfields", [])
        )
    rendered = []
    for code, segments in field["structured_subfields"]:
        value = []
        for segment in segments:
            if segment["type"] == "text":
                value.append(segment["value"])
            elif segment["type"] == "control_field":
                value.append("{{{0}}}".format(segment["tag"]))
            elif segment["type"] == "data_subfield":
                value.append("{{{0}${1}}}".format(
                    segment["tag"], segment["code"]
                ))
            else:
                raise ValueError("unsupported structured field segment")
        rendered.append("${0}{1}".format(code, "".join(value)))
    return prefix + "".join(rendered)


def parse_leader_condition(value: str) -> str:
    """Map one reviewed external Leader regex to an authoring condition."""

    condition = value.strip()
    if not condition:
        return "always"
    if condition.startswith("/") or condition.endswith("/"):
        leading = len(condition) - len(condition.lstrip("/"))
        trailing = len(condition) - len(condition.rstrip("/"))
        if leading != trailing or leading not in {1, 2, 3}:
            raise ValueError("unsupported Leader condition delimiter")
        condition = condition[leading:-trailing]
    try:
        return _LEADER_CONDITIONS[condition]
    except KeyError as exc:
        raise ValueError("unsupported Leader condition") from exc
