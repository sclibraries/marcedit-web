from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from marcedit_web.lib import native_tasks


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "native_tasks"


def _load_temporary_manifest(tmp_path, monkeypatch, manifest):
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(native_tasks, "_CONTRACT_PATH", contract_path)
    return native_tasks.load_contract_manifest()


def test_checked_in_contract_matches_every_golden_definition():
    native_tasks.verify_contract_manifest(GOLDEN_DIR)


def test_fingerprint_is_sha256_of_canonical_manifest_bytes():
    manifest = native_tasks.load_contract_manifest()
    expected = hashlib.sha256(
        native_tasks.canonical_manifest_json(manifest).encode("utf-8")
    ).hexdigest()

    assert native_tasks.current_compiler_fingerprint() == expected
    assert len(expected) == 64


def test_runtime_fingerprint_does_not_compile_or_read_golden_fixtures(monkeypatch):
    manifest = native_tasks.load_contract_manifest()
    expected = hashlib.sha256(
        native_tasks.canonical_manifest_json(manifest).encode("utf-8")
    ).hexdigest()
    contract_path = native_tasks._CONTRACT_PATH.resolve()
    original_read_text = Path.read_text
    paths_read = []

    def fail(*args, **kwargs):
        raise AssertionError("runtime fingerprint touched the golden compiler path")

    def guarded_read_text(path, *args, **kwargs):
        resolved = path.resolve()
        if resolved != contract_path:
            raise AssertionError(
                f"runtime fingerprint read unexpected path: {resolved}"
            )
        paths_read.append(resolved)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(native_tasks, "compile_definition", fail)
    monkeypatch.setattr(native_tasks, "build_contract_manifest", fail)
    monkeypatch.setattr(native_tasks, "verify_contract_manifest", fail)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    assert native_tasks.current_compiler_fingerprint() == expected
    assert paths_read == [contract_path]


def test_output_change_requires_manifest_change(monkeypatch):
    original = native_tasks.compile_definition

    def changed(definition):
        compiled = original(definition)
        return native_tasks.CompiledNativeTask(
            body=compiled.body + "\n# changed",
            imports=compiled.imports,
        )

    monkeypatch.setattr(native_tasks, "compile_definition", changed)

    with pytest.raises(native_tasks.CompilerContractError, match="body_sha256"):
        native_tasks.verify_contract_manifest(GOLDEN_DIR)


@pytest.mark.parametrize(
    "field",
    ["native_schema_version", "compiler_contract_version"],
)
def test_boolean_contract_versions_are_rejected(tmp_path, monkeypatch, field):
    manifest = native_tasks.load_contract_manifest()
    manifest[field] = True

    with pytest.raises(native_tasks.CompilerContractError, match=field):
        _load_temporary_manifest(tmp_path, monkeypatch, manifest)


def test_unknown_top_level_contract_fields_are_rejected(tmp_path, monkeypatch):
    manifest = native_tasks.load_contract_manifest()
    manifest["unknown"] = "value"

    with pytest.raises(native_tasks.CompilerContractError, match="unknown"):
        _load_temporary_manifest(tmp_path, monkeypatch, manifest)


def test_unknown_snapshot_fields_are_rejected(tmp_path, monkeypatch):
    manifest = native_tasks.load_contract_manifest()
    manifest["golden_snapshots"]["build-field.json"]["unknown"] = "value"

    with pytest.raises(
        native_tasks.CompilerContractError,
        match=r"build-field\.json.*unknown",
    ):
        _load_temporary_manifest(tmp_path, monkeypatch, manifest)
