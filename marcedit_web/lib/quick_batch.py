"""Deterministic one-shot quick batch operations (TASK-137)."""

from __future__ import annotations

import copy
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymarc
from pymarc import Field, Subfield

from . import transforms


@dataclass(frozen=True)
class CodeOption:
    value: str
    label: str


LEADER_OPTIONS: dict[str, tuple[CodeOption, ...]] = {
    "05": (
        CodeOption("a", "Increase in encoding level"),
        CodeOption("c", "Corrected or revised"),
        CodeOption("d", "Deleted"),
        CodeOption("n", "New"),
        CodeOption("p", "Increase in encoding level from prepublication"),
    ),
    "06": (
        CodeOption("a", "Language material"),
        CodeOption("c", "Notated music"),
        CodeOption("d", "Manuscript notated music"),
        CodeOption("e", "Cartographic material"),
        CodeOption("f", "Manuscript cartographic material"),
        CodeOption("g", "Projected medium"),
        CodeOption("i", "Nonmusical sound recording"),
        CodeOption("j", "Musical sound recording"),
        CodeOption("k", "Two-dimensional nonprojectable graphic"),
        CodeOption("m", "Computer file"),
        CodeOption("o", "Kit"),
        CodeOption("p", "Mixed materials"),
        CodeOption("r", "Three-dimensional artifact or naturally occurring object"),
        CodeOption("t", "Manuscript language material"),
    ),
    "07": (
        CodeOption("a", "Monographic component part"),
        CodeOption("b", "Serial component part"),
        CodeOption("c", "Collection"),
        CodeOption("d", "Subunit"),
        CodeOption("i", "Integrating resource"),
        CodeOption("m", "Monograph/item"),
        CodeOption("s", "Serial"),
    ),
    "08": (
        CodeOption(" ", "No specified type"),
        CodeOption("a", "Archival"),
    ),
    "17": (
        CodeOption(" ", "Full level"),
        CodeOption("1", "Full level, material not examined"),
        CodeOption("2", "Less-than-full level, material not examined"),
        CodeOption("3", "Abbreviated level"),
        CodeOption("4", "Core level"),
        CodeOption("5", "Partial preliminary level"),
        CodeOption("7", "Minimal level"),
        CodeOption("8", "Prepublication level"),
        CodeOption("u", "Unknown"),
        CodeOption("z", "Not applicable"),
    ),
    "18": (
        CodeOption(" ", "Non-ISBD"),
        CodeOption("a", "AACR2"),
        CodeOption("c", "ISBD punctuation omitted"),
        CodeOption("i", "ISBD punctuation included"),
        CodeOption("n", "Non-ISBD punctuation omitted"),
        CodeOption("u", "Unknown"),
    ),
    "19": (
        CodeOption(" ", "Not specified or not applicable"),
        CodeOption("a", "Set"),
        CodeOption("b", "Part with independent title"),
        CodeOption("c", "Part with dependent title"),
    ),
}

FORM_OF_ITEM_OPTIONS: tuple[CodeOption, ...] = (
    CodeOption(" ", "Not specified"),
    CodeOption("a", "Microfilm"),
    CodeOption("b", "Microfiche"),
    CodeOption("c", "Microopaque"),
    CodeOption("d", "Large print"),
    CodeOption("f", "Braille"),
    CodeOption("o", "Online"),
    CodeOption("q", "Direct electronic"),
    CodeOption("r", "Regular print reproduction"),
    CodeOption("s", "Electronic"),
)

QUICK_BATCH_KINDS: tuple[str, ...] = (
    "leader",
    "008-form",
    "040-cleanup",
    "856-url",
    "035-oclc",
    "9xx-delete",
    "655-cleanup",
)

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class QuickBatchRequest:
    kind: str
    position: str = ""
    value: str = ""
    action: str = ""
    agency: str = ""
    tag: str = ""
    url_contains: str = ""
    proxy_prefix: str = ""
    genre_term: str = ""
    genre_source: str = ""
    unwanted_text: str = ""


@dataclass
class QuickBatchPreview:
    request: QuickBatchRequest
    output_path: Path | None = None
    workdir: Path | None = None
    record_count: int = 0
    changed_count: int = 0
    skipped_count: int = 0
    store_revision: int | None = None
    detail_counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None


@dataclass
class QuickBatchResult:
    changed_count: int = 0
    skipped_count: int = 0
    error: str | None = None

    @property
    def applied(self) -> bool:
        return self.error is None and self.changed_count > 0


def validate_request(request: QuickBatchRequest) -> str | None:
    if request.kind not in QUICK_BATCH_KINDS:
        return "Choose a supported quick batch operation."
    if request.kind == "leader":
        if request.position not in LEADER_OPTIONS:
            return "That leader position is not available for quick batch editing."
        allowed = {option.value for option in LEADER_OPTIONS[request.position]}
        if request.value not in allowed:
            return "Choose one of the available leader values."
    if request.kind == "008-form":
        allowed = {option.value for option in FORM_OF_ITEM_OPTIONS}
        if request.value not in allowed:
            return "Choose one of the available 008 form-of-item values."
    if request.kind == "040-cleanup" and not request.agency.strip():
        return "Cataloging agency is required for 040 cleanup."
    if request.kind == "856-url":
        if request.action not in {"add-proxy", "remove-proxy", "delete-matching"}:
            return "Choose a supported 856 URL action."
        if request.action in {"add-proxy", "remove-proxy"} and not request.proxy_prefix:
            return "Proxy prefix is required for this 856 URL action."
        if request.action == "delete-matching" and not request.url_contains.strip():
            return "URL text is required when deleting 856 fields."
    if request.kind == "9xx-delete":
        tag = request.tag.upper()
        if tag != "9XX" and not re.fullmatch(r"9\d\d", tag):
            return "Choose a 9XX tag or exact 9xx tag."
    if request.kind == "655-cleanup":
        if not request.genre_term.strip():
            return "Genre/form term is required for 655 cleanup."
        if not request.genre_source.strip():
            return "Genre/form source is required for 655 cleanup."
    return None


def build_preview(
    store,
    request: QuickBatchRequest,
    *,
    progress: ProgressCallback | None = None,
) -> QuickBatchPreview:
    error = validate_request(request)
    if error:
        return QuickBatchPreview(request=request, error=error)

    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-quick-batch-"))
    output_path = workdir / "output.mrc"
    changed_count = 0
    skipped_count = 0
    detail_counts: Counter[str] = Counter()
    total = store.count()
    try:
        with output_path.open("wb") as output_fh:
            writer = pymarc.MARCWriter(output_fh)
            for idx, record in enumerate(store.iter_records()):
                new_record = copy.deepcopy(record)
                before = new_record.as_marc()
                _apply_to_record(new_record, request)
                after = new_record.as_marc()
                writer.write(new_record)
                if after != before:
                    changed_count += 1
                    detail_counts.update(
                        _detail_counts_for(record, new_record, request)
                    )
                else:
                    skipped_count += 1
                if progress is not None:
                    progress(idx + 1, total)
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return QuickBatchPreview(
        request=request,
        output_path=output_path,
        workdir=workdir,
        record_count=total,
        changed_count=changed_count,
        skipped_count=skipped_count,
        store_revision=store.revision,
        detail_counts=dict(detail_counts),
    )


def apply_request(store, request: QuickBatchRequest) -> QuickBatchResult:
    preview = build_preview(store, request)
    try:
        return apply_preview(store, preview)
    finally:
        cleanup_preview(preview)


def apply_preview(
    store,
    preview: QuickBatchPreview,
    *,
    progress: ProgressCallback | None = None,
) -> QuickBatchResult:
    if preview.error:
        return QuickBatchResult(error=preview.error)
    if preview.store_revision != store.revision:
        return QuickBatchResult(error="Loaded batch changed since preview.")
    if preview.output_path is None or not preview.output_path.is_file():
        return QuickBatchResult(error="Preview output is no longer available.")
    if progress is not None and preview.record_count:
        progress(preview.record_count, preview.record_count)
    store.replace_from_path(preview.output_path)
    return QuickBatchResult(
        changed_count=preview.changed_count,
        skipped_count=preview.skipped_count,
    )


def cleanup_preview(preview: QuickBatchPreview | None) -> None:
    """Remove a superseded preview's disk artifact."""
    workdir = getattr(preview, "workdir", None)
    if workdir is None:
        return
    shutil.rmtree(workdir, ignore_errors=True)


def _apply_to_record(record: pymarc.Record, request: QuickBatchRequest) -> None:
    if request.kind == "leader":
        _set_leader_value(record, request.position, request.value)
    elif request.kind == "008-form":
        transforms.set_008_form_of_item(record, request.value)
    elif request.kind == "040-cleanup":
        _cleanup_040(record, request.agency.strip())
    elif request.kind == "856-url":
        _update_856_urls(record, request)
    elif request.kind == "035-oclc":
        _cleanup_oclc_035(record)
    elif request.kind == "9xx-delete":
        transforms.delete_tags(record, request.tag.upper())
    elif request.kind == "655-cleanup":
        _cleanup_655(record, request)


def _detail_counts_for(
    before: pymarc.Record,
    after: pymarc.Record,
    request: QuickBatchRequest,
) -> Counter[str]:
    if request.kind == "9xx-delete":
        return _removed_tag_counts(before, after, request.tag.upper())
    if request.kind == "856-url" and request.action == "delete-matching":
        return _removed_856_url_counts(before, request.url_contains)
    if request.kind == "655-cleanup" and request.unwanted_text.strip():
        return _removed_655_counts(before, request.unwanted_text.strip())
    return Counter({_operation_detail_label(request): 1})


def _removed_tag_counts(
    before: pymarc.Record,
    after: pymarc.Record,
    tag: str,
) -> Counter[str]:
    before_counts = Counter(
        field.tag for field in before.fields if _tag_matches(field.tag, tag)
    )
    after_counts = Counter(
        field.tag for field in after.fields if _tag_matches(field.tag, tag)
    )
    out: Counter[str] = Counter()
    for field_tag, count in sorted((before_counts - after_counts).items()):
        out[f"{field_tag} removed"] = count
    return out


def _tag_matches(field_tag: str, requested: str) -> bool:
    if requested == "9XX":
        return re.fullmatch(r"9\d\d", field_tag) is not None
    return field_tag == requested


def _removed_856_url_counts(record: pymarc.Record, contains: str) -> Counter[str]:
    needle = contains.lower().strip()
    out: Counter[str] = Counter()
    if not needle:
        return out
    for field in record.get_fields("856"):
        for url in field.get_subfields("u"):
            if needle in url.lower():
                out[f"856 removed: {url}"] += 1
    return out


def _removed_655_counts(record: pymarc.Record, contains: str) -> Counter[str]:
    needle = contains.lower().strip()
    out: Counter[str] = Counter()
    if not needle:
        return out
    for field in record.get_fields("655"):
        values = field.get_subfields("a")
        if any(needle in value.lower() for value in values):
            label = values[0] if values else contains
            out[f"655 removed: {label}"] += 1
    return out


def _operation_detail_label(request: QuickBatchRequest) -> str:
    if request.kind == "leader":
        return f"Leader {request.position} set to {request.value!r}"
    if request.kind == "008-form":
        return f"008 form of item set to {request.value!r}"
    if request.kind == "040-cleanup":
        return "040 cleanup"
    if request.kind == "856-url":
        return f"856 {request.action}"
    if request.kind == "035-oclc":
        return "035 OCLC cleanup"
    if request.kind == "655-cleanup":
        return "655 cleanup"
    return request.kind


def _set_leader_value(record: pymarc.Record, position: str, value: str) -> None:
    offset = int(position)
    leader = str(record.leader)
    if len(leader) <= offset:
        return
    record.leader = pymarc.Leader(leader[:offset] + value + leader[offset + 1 :])


def _cleanup_040(record: pymarc.Record, agency: str) -> None:
    field = record.get("040")
    if field is None:
        record.add_ordered_field(
            Field(
                tag="040",
                indicators=[" ", " "],
                subfields=[
                    Subfield("e", "rda"),
                    Subfield("d", agency),
                ],
            )
        )
        return
    if "rda" not in field.get_subfields("e"):
        field.subfields.append(Subfield("e", "rda"))
    if agency not in field.get_subfields("d"):
        field.subfields.append(Subfield("d", agency))


def _update_856_urls(record: pymarc.Record, request: QuickBatchRequest) -> None:
    if request.action == "delete-matching":
        transforms.delete_856_fields_matching_url(record, request.url_contains)
        return
    for field in record.get_fields("856"):
        for idx, subfield in enumerate(field.subfields):
            if subfield.code != "u":
                continue
            if (
                request.url_contains
                and request.url_contains.lower() not in subfield.value.lower()
            ):
                continue
            if request.action == "add-proxy" and not subfield.value.startswith(
                request.proxy_prefix
            ):
                field.subfields[idx] = Subfield(
                    "u",
                    request.proxy_prefix + subfield.value,
                )
            elif request.action == "remove-proxy" and subfield.value.startswith(
                request.proxy_prefix
            ):
                field.subfields[idx] = Subfield(
                    "u",
                    subfield.value[len(request.proxy_prefix) :],
                )


def _cleanup_oclc_035(record: pymarc.Record) -> None:
    seen: set[str] = set()
    keep: list[Field] = []
    for field in record.get_fields("035"):
        normalized_subfields = _deduped_oclc_subfields(field, seen)
        if not normalized_subfields and _has_non_oclc_data(field):
            keep.append(field)
            continue
        if not normalized_subfields:
            continue
        field.subfields = normalized_subfields
        keep.append(field)
    record.remove_fields("035")
    for field in keep:
        record.add_ordered_field(field)


def _canonical_oclc_value(value: str) -> str | None:
    bare = transforms.normalize_oclc_035(value)
    if bare is None:
        return None
    digits = re.sub(r"^(?:ocm|ocn|on)0*", "", bare, flags=re.IGNORECASE)
    if not digits:
        return None
    return f"(OCoLC){digits}"


def _deduped_oclc_subfields(field: Field, seen: set[str]) -> list[Subfield]:
    out: list[Subfield] = []
    for subfield in field.subfields:
        canonical_value = (
            _canonical_oclc_value(subfield.value)
            if subfield.code in {"a", "z"}
            else None
        )
        if canonical_value is None:
            out.append(subfield)
        elif canonical_value not in seen:
            seen.add(canonical_value)
            out.append(Subfield(subfield.code, canonical_value))
    return out


def _has_non_oclc_data(field: Field) -> bool:
    for subfield in field.subfields:
        if subfield.code not in {"a", "z"}:
            return True
        if _canonical_oclc_value(subfield.value) is None:
            return True
    return False


def _cleanup_655(record: pymarc.Record, request: QuickBatchRequest) -> None:
    if request.unwanted_text.strip():
        transforms.delete_fields_matching_subfield(
            record,
            "655",
            "a",
            request.unwanted_text.strip(),
        )
    transforms.add_field_if_absent(
        record,
        Field(
            tag="655",
            indicators=[" ", "7"],
            subfields=[
                Subfield("a", request.genre_term.strip()),
                Subfield("2", request.genre_source.strip()),
            ],
        ),
    )
