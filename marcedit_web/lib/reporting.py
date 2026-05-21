"""Per-record snapshots and aggregate counters for the Report page.

Snapshots capture observational facts about a record at a moment in time.
The Report page renders aggregate views (tag counts, format breakdown,
URL-domain distribution) by walking the records currently in session and
calling `RecordSnapshot.of(record, index)` per record.

The CLI/profile-specific concerns from the original marc-processing
package — container stamping, profile-name awareness, Smith warning
checks — are dropped here. The Tasks page records errors directly via
`errors.transform_issue` and `errors.Issue`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from pymarc import Record

Status = Literal["ok", "warning", "error"]


def _leader_format_label(leader_06: str, leader_07: str) -> str:
    """Short human label for the record format, derived from leader bytes.

    Returns 'unknown' if no condition matched.
    """
    if leader_06 in "amt" and leader_07 == "m":
        return "book"
    if leader_07 == "s":
        return "serial"
    if leader_07 == "i":
        return "database"
    if leader_06 in "ef":
        return "map"
    if leader_06 == "g":
        return "video"
    if leader_06 in "ij":
        return "audio"
    if leader_06 in "cd":
        return "score"
    return "unknown"


def _first_subfield(record: Record, tag: str, code: str) -> str | None:
    field_obj = record.get(tag)
    if field_obj is None:
        return None
    values = field_obj.get_subfields(code)
    return values[0] if values else None


def _oclc_from_035(record: Record) -> str | None:
    """Return the first OCLC-style 035 $a (i.e. `(OCoLC)<num>`)."""
    for f in record.get_fields("035"):
        for sf in f.subfields:
            if sf.code == "a" and sf.value.startswith("(OCoLC)"):
                return sf.value[len("(OCoLC)") :]
    return None


def _url_domains(record: Record) -> Counter:
    domains: Counter = Counter()
    for f in record.get_fields("856"):
        for value in f.get_subfields("u"):
            domain = _domain_from_url(value)
            if domain:
                domains[domain] += 1
    return domains


def _domain_from_url(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    return parsed.hostname.lower() if parsed.hostname else None


@dataclass
class RecordSnapshot:
    """Facts about a record at one moment in processing."""

    index: int
    identifier: str | None       # 001 control number
    oclc_number: str | None      # extracted from 035 $a (OCoLC)X
    title: str | None            # 245 $a (trimmed)
    leader_06: str
    leader_07: str
    format_label: str            # 'book', 'serial', ..., 'unknown'
    tags_present: Counter        # tag -> count
    url_domains: Counter         # 856 $u destination domain -> count

    @classmethod
    def of(cls, record: Record, index: int) -> "RecordSnapshot":
        title = _first_subfield(record, "245", "a")
        if title:
            title = title.rstrip(" /:;,.").strip()
        leader_06 = record.leader[6]
        leader_07 = record.leader[7]
        tags = Counter(f.tag for f in record.fields)
        return cls(
            index=index,
            identifier=record.get("001").data if record.get("001") else None,
            oclc_number=_oclc_from_035(record),
            title=title,
            leader_06=leader_06,
            leader_07=leader_07,
            format_label=_leader_format_label(leader_06, leader_07),
            tags_present=tags,
            url_domains=_url_domains(record),
        )


@dataclass
class RecordReport:
    """The full processing report for one record."""

    before: RecordSnapshot
    after: RecordSnapshot | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> Status:
        if self.error is not None:
            return "error"
        if self.warnings:
            return "warning"
        return "ok"

    def action_lines(self) -> list[str]:
        """Multi-line per-action detail: which tags were added/deleted/changed."""
        if self.after is None:
            return [f"  ERROR: {self.error}"]

        before_tags = self.before.tags_present
        after_tags = self.after.tags_present
        all_tags = sorted(set(before_tags) | set(after_tags))

        added: list[str] = []
        deleted: list[str] = []
        changed: list[str] = []
        for tag in all_tags:
            b = before_tags.get(tag, 0)
            a = after_tags.get(tag, 0)
            if b == 0 and a > 0:
                added.append(f"{tag}(+{a})")
            elif a == 0 and b > 0:
                deleted.append(f"{tag}(-{b})")
            elif a != b:
                delta = a - b
                changed.append(f"{tag}({delta:+d})")

        lines: list[str] = []
        if deleted:
            lines.append(f"  - deleted: {', '.join(deleted)}")
        if added:
            lines.append(f"  - added:   {', '.join(added)}")
        if changed:
            lines.append(f"  - changed: {', '.join(changed)}")
        for w in self.warnings:
            lines.append(f"  ! {w}")
        return lines


@dataclass
class RunSummary:
    """Aggregate counts across a task run."""

    total: int = 0
    ok: int = 0
    warning: int = 0
    error: int = 0
    skipped_malformed: int = 0
    formats: Counter = field(default_factory=Counter)
    url_domains: Counter = field(default_factory=Counter)
    warning_messages: Counter = field(default_factory=Counter)
    # Per-tag totals across the whole batch: the cataloger equivalent of
    # MarcEdit's "Field Count" report. Aggregated only from
    # `report.after.tags_present` so errored records aren't included.
    tag_counts: Counter = field(default_factory=Counter)
    # Slim per-record dicts captured during processing.
    record_results: list[dict] = field(default_factory=list)

    def record(self, report: RecordReport) -> None:
        self.total += 1
        if report.status == "ok":
            self.ok += 1
        elif report.status == "warning":
            self.warning += 1
        else:
            self.error += 1
        self.formats[report.before.format_label] += 1
        if report.after is not None:
            self.url_domains.update(report.after.url_domains)
            self.tag_counts.update(report.after.tags_present)
        for w in report.warnings:
            self.warning_messages[w[:60]] += 1
        self.record_results.append({
            "index": report.before.index,
            "identifier": report.before.identifier,
            "title": report.before.title,
            "format": report.before.format_label,
            "status": report.status,
            "warnings": list(report.warnings),
            "error": report.error,
        })

    def line(self) -> str:
        formats_str = ", ".join(f"{k}={v}" for k, v in self.formats.most_common())
        url_domains_str = ", ".join(
            f"{k}={v}" for k, v in self.url_domains.most_common()
        )
        return (
            f"Summary: {self.ok} ok, {self.warning} warning, "
            f"{self.error} error"
            + (f", {self.skipped_malformed} malformed" if self.skipped_malformed else "")
            + (f". Formats: {formats_str}." if formats_str else ".")
            + (f" URL domains: {url_domains_str}." if url_domains_str else "")
        )

    def warning_breakdown(self) -> list[str]:
        if not self.warning_messages:
            return []
        return [f"  {n}× {msg}" for msg, n in self.warning_messages.most_common()]

    def field_count_breakdown(self, *, limit: int | None = None) -> list[str]:
        """Render per-tag field counts (MarcEdit "Field Count" parity)."""
        if not self.tag_counts:
            return []
        if limit is not None:
            included = {tag for tag, _ in self.tag_counts.most_common(limit)}
            pairs = sorted(
                (t, c) for t, c in self.tag_counts.items() if t in included
            )
        else:
            pairs = sorted(self.tag_counts.items())
        return [f"  {tag}: {count}" for tag, count in pairs]
