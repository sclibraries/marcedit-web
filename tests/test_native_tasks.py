from __future__ import annotations

import copy
import json
import textwrap
from pathlib import Path

import pytest
from pymarc import Field, Record

from marcedit_web.lib import native_tasks


FIXTURES = Path(__file__).parent / "fixtures" / "native_tasks"


def _definition(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _run_compiled(definition: dict, record: Record) -> None:
    compiled = native_tasks.compile_definition(definition)
    source = "\n".join(
        [
            *compiled.imports,
            "",
            "def apply(record):",
            textwrap.indent(compiled.body, "    "),
        ]
    )
    namespace: dict = {}
    exec(source, namespace)
    namespace["apply"](record)


def test_definition_round_trip_preserves_step_order_and_values():
    definition = _definition("delete-and-sort.json")
    exported = native_tasks.export_definition(definition)

    assert exported.endswith(b"\n")
    assert native_tasks.load_definition_json(exported.decode("utf-8")) == definition
    assert [step["id"] for step in definition["steps"]] == [
        "delete-029",
        "sort-fields",
    ]


def test_canonical_json_sorts_keys_but_preserves_arrays():
    definition = _definition("delete-and-sort.json")
    reversed_keys = dict(reversed(list(definition.items())))

    assert native_tasks.canonical_definition_json(reversed_keys) == (
        native_tasks.canonical_definition_json(definition)
    )
    assert json.loads(native_tasks.canonical_definition_json(definition))[
        "steps"
    ] == definition["steps"]


def test_unknown_schema_version_fails_with_encountered_and_supported_values():
    definition = _definition("delete-and-sort.json")
    definition["schema_version"] = 2

    with pytest.raises(
        native_tasks.UnsupportedSchemaVersion,
        match=r"encountered 2; supported version is 1",
    ):
        native_tasks.validate_definition(definition)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda d: d["steps"].append(copy.deepcopy(d["steps"][0])), "step IDs"),
        (lambda d: d["steps"][0].update(action="custom"), "not valid"),
        (lambda d: d["steps"][0].update(code="record.clear\\(\\)"), "code"),
        (lambda d: d.update(review_state="needs_confirmation"), "review_state"),
    ],
)
def test_nonportable_or_ambiguous_definitions_fail_closed(mutation, message):
    definition = _definition("delete-and-sort.json")
    mutation(definition)

    with pytest.raises(native_tasks.NativeDefinitionError, match=message):
        native_tasks.validate_definition(definition)


def test_delete_and_sort_compile_in_source_order():
    compiled = native_tasks.compile_definition(_definition("delete-and-sort.json"))
    assert compiled.body.index("delete_tags(record, '029')") < compiled.body.index(
        "sort_fields(record)"
    )
    assert compiled.imports == (
        "from marcedit_web.lib.transforms import delete_tags, sort_fields",
    )


def test_structured_build_field_compiles_without_source_text():
    compiled = native_tasks.compile_definition(_definition("build-field.json"))
    assert "_t_003 = control_value(record, '003')" in compiled.body
    assert "_t_001 = control_value(record, '001')" in compiled.body
    assert "'B({003}){001}-SC'" in compiled.body
    assert "marcedit-task" not in compiled.body
    assert "8c7d6e7a" not in compiled.body


def test_structured_text_braces_remain_literal_when_compiled_and_run():
    definition = _definition("build-field.json")
    definition["steps"][0]["subfields"] = [
        {
            "code": "a",
            "segments": [
                {"type": "text", "value": "literal {001} and {name}: "},
                {"type": "control_field", "tag": "003"},
            ],
        }
    ]
    record = Record()
    record.add_field(Field(tag="001", data="must-not-substitute"))
    record.add_field(Field(tag="003", data="explicit-value"))

    _run_compiled(definition, record)

    assert record["876"].get_subfields("a") == [
        "literal {001} and {name}: explicit-value"
    ]


def test_structured_control_segments_substitute_when_compiled_and_run():
    record = Record()
    record.add_field(Field(tag="001", data="12345"))
    record.add_field(Field(tag="003", data="CtY"))

    _run_compiled(_definition("build-field.json"), record)

    assert record["876"].get_subfields("a") == ["B(CtY)12345-SC"]


def test_compile_definition_rejects_renderer_todo_output(monkeypatch):
    def render_todo(_ops):
        return {"body": "# TODO: unsupported operation", "imports": []}

    monkeypatch.setattr(
        native_tasks.task_builder,
        "render_ops_to_python",
        render_todo,
    )

    with pytest.raises(
        native_tasks.NativeDefinitionError,
        match="produced unsupported code",
    ):
        native_tasks.compile_definition(_definition("delete-and-sort.json"))
