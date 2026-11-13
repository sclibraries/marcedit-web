"""Tests for the deterministic ROADMAP backlog generator."""

import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backlog.py"


def _write_fixture(tmp_path, roadmap, tickets):
    ticket_dir = tmp_path / ".tickets"
    ticket_dir.mkdir()
    for filename, content in tickets.items():
        (ticket_dir / filename).write_text(content, encoding="utf-8")
    roadmap_path = tmp_path / "ROADMAP.md"
    roadmap_path.write_text(roadmap, encoding="utf-8")
    return roadmap_path


def _run(mode, roadmap_path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), mode, str(roadmap_path)],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("status_text", "expected_status"),
    [
        ("Status: Todo", "Todo"),
        ("**Status:** Todo", "Todo"),
        ("## Status\n\nTodo", "Todo"),
        ("Status: In-Progress (triage notes)", "In-Progress"),
    ],
)
def test_status_syntaxes_render_the_normalized_status(
    tmp_path, status_text, expected_status
):
    roadmap = "1. **M1 — Workflow**\n<!-- backlog:start -->\n<!-- backlog:end -->\n"
    roadmap_path = _write_fixture(
        tmp_path,
        roadmap,
        {
            "TASK-001-example.md": (
                "Title: Example ticket\n"
                + status_text
                + "\nMilestone: M1\nSize: M\n"
            )
        },
    )

    result = _run("--write", roadmap_path)

    assert result.returncode == 0, result.stderr
    assert (
        "[TASK-001-example](.tickets/TASK-001-example.md)"
        f" | Example ticket | {expected_status} | M |"
    ) in roadmap_path.read_text(encoding="utf-8")


def test_write_orders_milestones_and_filenames_and_keeps_only_open_tickets(
    tmp_path,
):
    prefix = (
        "# Roadmap\r\n1. **M2 — Later priority**\r\n"
        "2. **M3 — Empty milestone**\r\n3. **M1 — First priority**\r\n"
        "<!-- backlog:start -->\r\n"
    )
    suffix = "<!-- backlog:end -->\r\nHand-written note.\r\n"
    roadmap_path = tmp_path / "ROADMAP.md"
    roadmap_path.write_bytes((prefix + "stale\r\n" + suffix).encode("utf-8"))
    ticket_dir = tmp_path / ".tickets"
    ticket_dir.mkdir()
    tickets = {
        "TASK-046-zeta.md": "Title: Zeta\nStatus: Ready\nMilestone: M2\nSize: M\n",
        "TASK-046-alpha.md": "Title: Alpha\nStatus: Blocked\nMilestone: M2\nSize: S\n",
        "TASK-900-first.md": "Title: First\nStatus: Todo\nMilestone: M1\nSize: L\n",
        "TASK-899-unassigned.md": "Title: Unassigned\nStatus: Blocked\n",
        "TASK-901-completed.md": "Title: Done\nStatus: Completed\nMilestone: M2\n",
        "TASK-902-obsolete.md": "Title: Old\nStatus: Obsolete\nMilestone: M1\n",
    }
    for filename, content in tickets.items():
        (ticket_dir / filename).write_text(content, encoding="utf-8")

    result = _run("--write", roadmap_path)
    updated = roadmap_path.read_bytes()
    start = updated.index(b"<!-- backlog:start -->") + len(b"<!-- backlog:start -->")
    end = updated.index(b"<!-- backlog:end -->")
    block = updated[start:end].decode("utf-8")

    assert result.returncode == 0, result.stderr
    assert updated[: len(prefix.encode("utf-8"))] == prefix.encode("utf-8")
    assert updated[end:] == suffix.encode("utf-8")
    assert block.index("### M2 — Later priority") < block.index("### M1 — First priority")
    assert block.index("### M2 — Later priority") < block.index("### M3 — Empty milestone")
    assert block.index("### M3 — Empty milestone") < block.index("### M1 — First priority")
    assert block.index("### M1 — First priority") < block.index("### Unassigned")
    assert block.index("TASK-046-alpha.md") < block.index("TASK-046-zeta.md")
    assert block.index("TASK-046-alpha.md") < block.index("TASK-900-first.md")
    assert "| Alpha | Blocked | S |" in block
    assert "| Zeta | Ready | M |" in block
    assert "| First | Todo | L |" in block
    assert "| Unassigned | Blocked |  |" in block
    assert "TASK-901-completed.md" not in block
    assert "TASK-902-obsolete.md" not in block
    assert block.count("| [TASK-046-") == 2
    assert block.count("| Ticket | Title | Status | Size |") == 4


@pytest.mark.parametrize(
    ("filename", "ticket", "problem"),
    [
        (
            "TASK-001-no-milestone.md",
            "Title: No milestone\nStatus: Todo\n",
            "has no milestone",
        ),
        (
            "TASK-002-unknown-milestone.md",
            "Title: Unknown milestone\nStatus: Todo\nMilestone: M9\n",
            "unknown milestone M9",
        ),
        (
            "TASK-003-unknown-status.md",
            "Title: Unknown status\nStatus: Queued\nMilestone: M1\n",
            "unknown status Queued",
        ),
        (
            "TASK-004-missing-status.md",
            "Title: Missing status\nMilestone: M1\n",
            "missing status",
        ),
    ],
)
def test_check_reports_ticket_validation_errors(
    tmp_path, filename, ticket, problem
):
    roadmap = (
        "1. **M1 — Workflow**\n<!-- backlog:start -->\n"
        "stale generated block\n<!-- backlog:end -->\n"
    )
    roadmap_path = _write_fixture(tmp_path, roadmap, {filename: ticket})

    result = _run("--check", roadmap_path)

    assert result.returncode != 0
    assert problem in result.stderr
    assert "generated block is stale" in result.stderr


def test_check_passes_immediately_after_write(tmp_path):
    roadmap = "1. **M1 — Workflow**\n<!-- backlog:start -->\n<!-- backlog:end -->\n"
    roadmap_path = _write_fixture(
        tmp_path,
        roadmap,
        {
            "TASK-001-valid.md": (
                "# Valid ticket\n**Status:** In-Review\n"
                "**Milestone:** M1\n**Size:** S\n"
            )
        },
    )

    written = _run("--write", roadmap_path)
    checked = _run("--check", roadmap_path)

    assert written.returncode == 0, written.stderr
    assert (
        "| [TASK-001-valid](.tickets/TASK-001-valid.md) | Valid ticket "
        "| In-Review | S |"
    ) in roadmap_path.read_text(encoding="utf-8")
    assert checked.returncode == 0, checked.stderr


def test_write_without_markers_fails_without_modifying_roadmap(tmp_path):
    roadmap_path = tmp_path / "ROADMAP.md"
    original = b"Hand-written roadmap content\r\n"
    roadmap_path.write_bytes(original)

    result = _run("--write", roadmap_path)

    assert result.returncode != 0
    assert "backlog markers" in result.stderr
    assert roadmap_path.read_bytes() == original
