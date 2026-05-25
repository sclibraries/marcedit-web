"""Stage 18 regression tests for literal-safe codegen.

Two halves:

1. Unit tests on :func:`codegen_safety.lit` covering the literal types
   we actually splice (strings with quotes / backslashes / newlines /
   unicode, ints, bools, None) plus the TypeError fallback for
   non-literal values.

2. A small corpus of malicious-shaped MarcEdit tasksfiles run through
   :func:`marcedit_import.convert_tasksfile_text`. The pre-v3 bare
   ``"{tag}"`` interpolation would have happily emitted syntactically
   broken (or worse, code-injecting) Python. After Stage 18, every
   emission parses cleanly via ``ast.parse`` and — when run through
   the Stage 17 sandbox against a real MARC record — does NOT create
   the canary file an attacker's injected payload would touch.
"""

from __future__ import annotations

import ast
import io
import os
from pathlib import Path

import pymarc
import pytest

from marcedit_web.lib import marcedit_import, task_builder
from marcedit_web.lib.codegen_safety import lit
from marcedit_web.lib.sandbox import TaskSpec, run_tasks_subprocess


# ---------------------------------------------------------------------------
# lit() unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "tag-029",
        'has "double" quotes',
        "has 'single' quotes",
        "has\\backslash",
        "line1\nline2",
        "tab\there",
        "unicode é 中",
        '"""triple"""',
        ")\nimport os; os.system('pwn')\n#",
        0,
        -1,
        42,
        True,
        False,
        None,
        3.14,
        b"bytes-here",
        (1, 2, "three"),
    ],
)
def test_lit_roundtrips_through_literal_eval(value):
    """Whatever we put in must come back out under ast.literal_eval.

    ``frozenset(...)`` and ``complex(...)`` survive ``lit()`` but
    ``ast.literal_eval`` rejects them because their canonical source
    form is a constructor call, not a literal expression. Those types
    aren't on our codegen surface anyway — we splice strings,
    indicators, tags, and ints.
    """
    src = lit(value)
    parsed = ast.literal_eval(src)
    assert parsed == value


def test_lit_rejects_mutable_containers():
    """Lists and sets are not literal — fail loudly."""
    with pytest.raises(TypeError):
        lit(["a", "b"])
    with pytest.raises(TypeError):
        lit({"a", "b"})


def test_lit_output_always_parses_as_a_python_expression():
    """The output is a syntactically valid expression on its own."""
    for v in ["foo", "bar\"baz", 42, None, True]:
        ast.parse(lit(v), mode="eval")


def test_lit_rejects_arbitrary_classes():
    """Non-literal types raise rather than silently emitting unsafe text."""

    class Custom:
        pass

    with pytest.raises(TypeError):
        lit(Custom())


def test_lit_rejects_functions():
    with pytest.raises(TypeError):
        lit(lambda: None)


# ---------------------------------------------------------------------------
# Malicious-shaped tasksfile corpus
# ---------------------------------------------------------------------------


def _convert(text: str):
    return marcedit_import.convert_tasksfile_text(
        text,
        name="hostile",
        description_fallback="malicious-corpus",
    )


# Each tuple is (label, tasksfile text). The tasksfiles intentionally
# carry payloads that, under v2's bare `"{var}"` interpolation, would
# either (a) produce un-parseable Python or (b) escape the string literal
# and execute arbitrary code. After Stage 18 every one of these must
# produce an `ast.parse`-clean body whose execution mutates a record but
# does NOT run the injected payload.
MALICIOUS_CASES = [
    # 1. DELETE with embedded double quote in the tag.
    (
        "delete-quote-in-tag",
        'DELETE\t029")\nimport os; open(os.environ["MARCEDIT_CANARY"], "w").close()\n#\t\n',
    ),
    # 2. DELETE-by-subfield with a quote in the "find" column.
    (
        "delete-by-subfield-quote-in-find",
        'DELETE\t029\thas " quote\t\t\n',
    ),
    # 3. ADD with a quote in the tag.
    (
        "add-quote-in-tag",
        'ADD\t029")\nimport os; open(os.environ["MARCEDIT_CANARY"], "w").close()\n#\t\\\\$ahello\t\t\n',
    ),
    # 4. ADD with a newline-bearing tag (raw tab-split makes this
    #    impossible per-line, but malformed exports have done it).
    (
        "add-backslash-in-ind",
        "ADD\t029\t\\\\$ainnocuous\t\t\n",
    ),
    # 5. SUBFIELD_EDIT with a quote in the tag.
    (
        "subfield-edit-quote-in-tag",
        'SUBFIELD_EDIT\t245")\nimport os; open(os.environ["MARCEDIT_CANARY"], "w").close()\n#\ta\tfoo\tbar\n',
    ),
    # 6. SUBFIELD_EDIT with a backslash in the subfield code.
    (
        "subfield-edit-backslash-in-code",
        'SUBFIELD_EDIT\t245\ta\\\tfoo\tbar\n',
    ),
    # 7. ADD with a backslash in the indicator (MarcEdit uses \ for
    #    blank, but a doubled \\ used to interact badly with bare
    #    interpolation).
    (
        "add-backslash-doubled-ind",
        "ADD\t029\t\\\\$ahello\t\t\n",
    ),
    # 8. DELETE-by-subfield with a backslash-newline in the find.
    (
        "delete-by-subfield-backslash-newline",
        'DELETE\t029\tfoo\\nbar\t\t\n',
    ),
    # 9. ADD with a `");` payload in the indicator column (pre-Stage-18
    #    would let this close the bare `"{ind1}"`).
    (
        "add-paren-payload-in-ind",
        'ADD\t029\t");\nimport os; os.system("touch /tmp/pwn")\n#$ahello\t\t\n',
    ),
    # 10. Unknown verb whose argument carries a quote payload — the
    #     `custom` fallback must still emit valid Python.
    (
        "unknown-verb-with-quote",
        'BOGUS\t")\nimport os; os.system("touch /tmp/pwn")\n#\n',
    ),
]


@pytest.mark.parametrize("label,text", MALICIOUS_CASES, ids=[c[0] for c in MALICIOUS_CASES])
def test_malicious_tasksfile_emits_parseable_python(label, text):
    """Every emission must be syntactically valid Python.

    A v2 bare-interpolation regression would land here as a SyntaxError
    out of ``ast.parse`` — that's the canary. We parse as a module
    rather than wrapping in a function: a body that's all comments is
    still a valid module but not a valid function body, and the
    behavior we care about is "the emitted source compiles."
    """
    result = _convert(text)
    ast.parse(result.body or "pass")


def _sample_record_bytes() -> bytes:
    """One tiny MARC record with a 245 and a couple of subfields."""
    r = pymarc.Record()
    r.leader = pymarc.Leader("00000nam a2200000 a 4500")
    r.add_field(pymarc.Field(tag="001", data="canary-001"))
    r.add_field(pymarc.Field(
        tag="245",
        indicators=["1", "0"],
        subfields=[pymarc.Subfield("a", "Title")],
    ))
    out = io.BytesIO()
    pymarc.MARCWriter(out).write(r)
    return out.getvalue()


@pytest.mark.parametrize("label,text", MALICIOUS_CASES, ids=[c[0] for c in MALICIOUS_CASES])
def test_malicious_tasksfile_does_not_execute_canary(label, text, tmp_path):
    """End-to-end: convert → sandbox-run → canary file must not exist.

    Many payloads embed ``open(os.environ["MARCEDIT_CANARY"], "w")`` —
    a v2 bare-interpolation regression would actually run that and
    create the file. After Stage 18 the path either fails to parse,
    or runs as a string-literal no-op.
    """
    canary = tmp_path / "canary"
    result = _convert(text)
    # ``imports`` is a list of full import statements; pass each as a
    # separate entry to the sandbox driver's import-prelude phase.
    task = TaskSpec(name=label, body=result.body, imports=result.imports)
    # Pre-populate MARCEDIT_CANARY in the sandbox env via a shim — the
    # sandbox cleanses the environment otherwise. We bolt it on by
    # rewriting the body's imports list to set os.environ before the
    # payload would read it, so a successful injection would have an
    # unambiguous filesystem signal.
    prelude = (
        f"import os; os.environ['MARCEDIT_CANARY'] = {lit(str(canary))}"
    )
    task = TaskSpec(
        name=label,
        body=result.body or "pass",
        imports=[prelude] + result.imports,
    )
    sandbox_result = run_tasks_subprocess(
        [task],
        _sample_record_bytes(),
        timeout=10.0,
        tmp_dir=tmp_path / "sandbox",
    )
    # The sandbox must not have created the canary — meaning no payload
    # escaped into running code.
    assert not canary.exists(), (
        f"{label}: sandbox executed an injected payload "
        f"(canary {canary} was created). stderr={sandbox_result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Form-builder side: same audit
# ---------------------------------------------------------------------------


def test_task_builder_delete_tag_with_quote_in_tag_emits_safe_code():
    """A tag the form-builder would never produce — but a hand-edited
    JSON marker might — must still emit safe Python."""
    ops = [task_builder.Operation(
        kind="delete-tag",
        params={"tag": 'evil")\nimport os; os.system("rm -rf /")\n#'},
    )]
    rendered = task_builder.render_ops_to_python(ops)
    ast.parse(rendered["body"])


def test_task_builder_add_field_with_quote_in_indicator_emits_safe_code():
    ops = [task_builder.Operation(
        kind="add-field",
        params={
            "tag": "029",
            "ind1": '"',
            "ind2": " ",
            "subfields": [["a", "ok"]],
            "condition": "always",
            "if_absent": False,
        },
    )]
    rendered = task_builder.render_ops_to_python(ops)
    ast.parse(rendered["body"])


def test_task_builder_subfield_replace_with_quote_payload_emits_safe_code():
    ops = [task_builder.Operation(
        kind="subfield-replace",
        params={
            "tag": '245")\nimport os; os.system("pwn")\n#',
            "code": "a",
            "find": "Old",
            "replace": "New",
        },
    )]
    rendered = task_builder.render_ops_to_python(ops)
    ast.parse(rendered["body"])
