#!/usr/bin/env python3
"""Generate or check the ticket backlog in ROADMAP.md."""

import argparse
import re
import sys
from pathlib import Path


START_MARKER = "<!-- backlog:start -->"
END_MARKER = "<!-- backlog:end -->"
VALID_STATUSES = {
    "Todo",
    "Ready",
    "In-Progress",
    "In-Review",
    "Completed",
    "Blocked",
    "Obsolete",
}
STATUS_LINE = re.compile(r"^\s*(?:\*\*)?Status:(?:\*\*)?\s*(.*?)\s*$")
METADATA_LINES = {
    name: re.compile(
        r"^\s*(?:\*\*)?" + name + r":(?:\*\*)?\s*(.*?)\s*$"
    )
    for name in ("Title", "Milestone", "Size")
}
MILESTONE_LINE = re.compile(r"^\s*\d+\.\s+\*\*(.+?)\s+—\s+(.+?)\*\*\s*$")


def _first_word(value):
    words = value.strip().split()
    return words[0] if words else ""


def _status(lines):
    for index, line in enumerate(lines):
        match = STATUS_LINE.match(line)
        if match:
            return _first_word(match.group(1))
        if line.strip() == "## Status":
            for value_line in lines[index + 1 :]:
                if value_line.strip():
                    return _first_word(value_line)
            return ""
    return ""


def _ticket(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    values = {"Title": "", "Milestone": "", "Size": ""}
    for line in lines:
        for name, pattern in METADATA_LINES.items():
            if not values[name]:
                match = pattern.match(line)
                if match:
                    values[name] = match.group(1).strip()

    if not values["Title"]:
        for line in lines:
            if line.startswith("# "):
                values["Title"] = line[2:].strip()
                break

    milestone = _first_word(values["Milestone"])
    size = _first_word(values["Size"])
    return {
        "key": path.stem,
        "filename": path.name,
        "title": values["Title"],
        "status": _status(lines),
        "milestone": milestone,
        "size": size,
    }


def _milestones(roadmap):
    milestones = []
    for line in roadmap.splitlines():
        match = MILESTONE_LINE.match(line)
        if match:
            milestones.append((match.group(1).split()[0], match.group(2)))
    return milestones


def _table(heading, tickets, newline):
    lines = [
        heading,
        "",
        "| Ticket | Title | Status | Size |",
        "| --- | --- | --- | --- |",
    ]
    for ticket in tickets:
        filename = ticket["filename"]
        lines.append(
            "| [{0}](.tickets/{1}) | {2} | {3} | {4} |".format(
                ticket["key"],
                filename,
                ticket["title"],
                ticket["status"],
                ticket["size"],
            )
        )
    return newline.join(lines)


def _generated_block(roadmap, tickets):
    newline = "\r\n" if "\r\n" in roadmap else "\n"
    open_tickets = [
        ticket
        for ticket in tickets
        if ticket["status"] not in {"Completed", "Obsolete"}
    ]
    sections = []
    for code, name in _milestones(roadmap):
        selected = [
            ticket for ticket in open_tickets if ticket["milestone"] == code
        ]
        sections.append(_table("### {0} — {1}".format(code, name), selected, newline))

    unassigned = [ticket for ticket in open_tickets if not ticket["milestone"]]
    if unassigned:
        sections.append(_table("### Unassigned", unassigned, newline))
    return (newline * 2).join(sections)


def _replace_block(roadmap, generated):
    if roadmap.count(START_MARKER) != 1 or roadmap.count(END_MARKER) != 1:
        raise ValueError("ROADMAP.md must contain one pair of backlog markers")

    start = roadmap.index(START_MARKER)
    end = roadmap.index(END_MARKER)
    if end <= start:
        raise ValueError("ROADMAP.md backlog markers are out of order")

    body_start = start + len(START_MARKER)
    if roadmap[body_start : body_start + 2] == "\r\n":
        body_start += 2
    elif roadmap[body_start : body_start + 1] == "\n":
        body_start += 1
    body_end = roadmap.rfind("\n", 0, end) + 1
    if body_end < body_start:
        raise ValueError("ROADMAP.md backlog markers are out of order")

    newline = "\r\n" if "\r\n" in roadmap else "\n"
    return roadmap[:body_start] + generated + newline + roadmap[body_end:]


def _problems(tickets, milestones):
    known_milestones = {code for code, _ in milestones}
    problems = []
    for ticket in tickets:
        filename = ticket["filename"]
        status = ticket["status"]
        if not status:
            problems.append("{0}: missing status".format(filename))
        elif status not in VALID_STATUSES:
            problems.append(
                "{0}: unknown status {1}".format(filename, status)
            )

        if status not in {"Completed", "Obsolete"}:
            milestone = ticket["milestone"]
            if not milestone:
                problems.append(
                    "{0}: open ticket has no milestone".format(filename)
                )
            elif milestone not in known_milestones:
                problems.append(
                    "{0}: unknown milestone {1}".format(filename, milestone)
                )
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("roadmap", type=Path)
    args = parser.parse_args(argv)

    try:
        roadmap = args.roadmap.read_bytes().decode("utf-8")
        tickets = [
            _ticket(path)
            for path in sorted((args.roadmap.parent / ".tickets").glob("*.md"))
        ]
        milestones = _milestones(roadmap)
        generated = _generated_block(roadmap, tickets)
        updated = _replace_block(roadmap, generated)

        if args.check:
            problems = _problems(tickets, milestones)
            if updated != roadmap:
                problems.append("{0}: generated block is stale".format(args.roadmap))
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1 if problems else 0

        args.roadmap.write_bytes(updated.encode("utf-8"))
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
