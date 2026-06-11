"""Tests for drafting task-builder operations through Gemini."""

from __future__ import annotations

import json
import socket
from urllib import request

import pytest

from marcedit_web.lib import ai_task_draft
from marcedit_web.lib import gemini_task_draft


def _draft_response_text() -> str:
    return json.dumps(
        {
            "task_name": "routledge-eba",
            "description": "Delete 029 fields from Routledge EBA records.",
            "operations": [
                {
                    "kind": "delete-tag",
                    "source_text": "Delete all 029 fields.",
                    "explanation": "Maps directly to deleting MARC tag 029.",
                    "confidence": "high",
                    "params": {"tag": "029"},
                }
            ],
            "questions": ["Confirm whether 856 links should be retained."],
            "manual_notes": [],
            "unsupported_lines": [],
        }
    )


def _gemini_response(text: str) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": text},
                    ],
                },
            }
        ]
    }


def test_is_enabled_requires_gemini_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert gemini_task_draft.is_enabled() is False

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert gemini_task_draft.is_enabled() is True


def test_build_prompt_contains_schema_guardrails_allowed_operations_and_notes():
    notes = "Delete all 029 fields, then strip trailing slash from 245."

    prompt = gemini_task_draft.build_prompt(notes)

    assert "JSON only" in prompt
    assert "No Python" in prompt
    assert '"description"' in prompt
    assert '"source_text"' in prompt
    assert '"explanation"' in prompt
    assert '"confidence"' in prompt
    assert '"regex"' in prompt
    assert "unsupported_lines" in prompt
    assert "replace-field-data-by-regex" in prompt
    assert '"custom"' not in prompt
    assert notes in prompt


def test_build_prompt_includes_valid_add_field_examples():
    prompt = gemini_task_draft.build_prompt(
        "Add Streaming Audio 877 and Electronic scores 655."
    )

    assert "Examples of valid add-field operations" in prompt
    assert '"subfields": [["m", "Streaming Audio"]]' in prompt
    assert '"subfields": [["a", "Electronic scores."], ["2", "local"]]' in prompt
    assert "subfields must be a list of [code, value] pairs" in prompt
    assert "never an object or string" in prompt


def test_draft_task_from_notes_posts_to_gemini_and_parses_review(monkeypatch):
    captured: dict[str, object] = {}
    parsed: dict[str, str] = {}
    real_parse = ai_task_draft.parse_ai_task_draft

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(_gemini_response(_draft_response_text())).encode("utf-8")

    def fake_urlopen(req, timeout):
        captured["request"] = req
        captured["timeout"] = timeout
        return FakeResponse()

    def parse_spy(raw_text):
        parsed["raw_text"] = raw_text
        return real_parse(raw_text)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ai_task_draft, "parse_ai_task_draft", parse_spy)

    review = gemini_task_draft.draft_task_from_notes("Delete all 029 fields.")

    assert parsed["raw_text"] == _draft_response_text()
    assert review.task_name == "routledge-eba"
    assert review.description == "Delete 029 fields from Routledge EBA records."
    assert review.operations[0].kind == "delete-tag"
    assert review.operations[0].source_text == "Delete all 029 fields."
    assert review.operations[0].confidence == "high"
    assert review.questions == ("Confirm whether 856 links should be retained.",)

    req = captured["request"]
    assert req.full_url.endswith(
        f"/v1beta/models/{gemini_task_draft.DEFAULT_MODEL}:generateContent"
    )

    headers = {key.lower(): value for key, value in req.header_items()}
    assert headers["x-goog-api-key"] == "test-key"

    body = json.loads(req.data.decode("utf-8"))
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "low"
    assert "AI task draft translator" in body["system_instruction"]["parts"][0]["text"]
    assert "Delete all 029 fields." in body["contents"][0]["parts"][0]["text"]


def test_draft_task_from_notes_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(gemini_task_draft.GeminiTaskDraftError, match="GEMINI_API_KEY"):
        gemini_task_draft.draft_task_from_notes("Delete all 029 fields.")


def test_draft_task_from_notes_wraps_socket_timeout(monkeypatch):
    def fake_urlopen(req, timeout):
        raise socket.timeout("The read operation timed out")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(request, "urlopen", fake_urlopen)

    with pytest.raises(
        gemini_task_draft.GeminiTaskDraftError,
        match="Gemini request timed out",
    ):
        gemini_task_draft.draft_task_from_notes("Delete all 029 fields.")


def test_missing_candidate_text_raises_clear_error():
    with pytest.raises(gemini_task_draft.GeminiTaskDraftError, match="no text"):
        gemini_task_draft.extract_response_text(
            {"candidates": [{"content": {"parts": []}}]}
        )
