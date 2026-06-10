"""Gemini REST client for AI-assisted task draft authoring."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

from marcedit_web.lib import ai_task_draft, task_builder


DEFAULT_MODEL = "gemini-3.5-flash"
API_ROOT = "https://generativelanguage.googleapis.com"
_TIMEOUT_SECONDS = 30


class GeminiTaskDraftError(RuntimeError):
    """Raised when Gemini task drafting cannot produce a reviewable draft."""


def is_enabled() -> bool:
    """Return whether Gemini drafting is configured."""

    return bool(os.environ.get("GEMINI_API_KEY"))


def draft_task_from_notes(notes: str) -> ai_task_draft.DraftReview:
    """Ask Gemini to translate cataloger notes into a validated draft review."""

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiTaskDraftError("GEMINI_API_KEY is required to draft a task")

    url = f"{API_ROOT}/v1beta/models/{DEFAULT_MODEL}:generateContent"
    body = json.dumps(_payload_for(notes)).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise GeminiTaskDraftError(f"Gemini request failed: HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise GeminiTaskDraftError(f"Gemini request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise GeminiTaskDraftError("Gemini response was not valid JSON") from exc

    text = extract_response_text(data)
    try:
        return ai_task_draft.parse_ai_task_draft(text)
    except ai_task_draft.DraftValidationError as exc:
        raise GeminiTaskDraftError(f"Gemini draft was not valid: {exc}") from exc


def extract_response_text(data: dict) -> str:
    """Extract the first text part from a Gemini generateContent response."""

    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        raise GeminiTaskDraftError("Gemini response contained no text")

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text

    raise GeminiTaskDraftError("Gemini response contained no text")


def build_prompt(notes: str) -> str:
    """Build the user prompt that constrains Gemini to safe draft JSON."""

    operations = [
        op for op in task_builder.OPERATIONS_PALETTE if op.get("kind") != "custom"
    ]
    schema = {
        "task_name": "valid-slug",
        "description": "One sentence cataloger-facing task summary.",
        "operations": [
            {
                "kind": "delete-tag",
                "source_text": "Original cataloger note line that produced this op.",
                "explanation": "Why this operation matches the source text.",
                "confidence": "high",
                "regex": {
                    "pattern": "",
                    "meaning": "",
                    "before": "",
                    "after": "",
                },
                "params": {"tag": "029"},
            }
        ],
        "questions": [],
        "manual_notes": [],
        "unsupported_lines": [],
    }
    examples = [
        {
            "kind": "add-field",
            "source_text": (
                "add 877 subfield m Streaming Audio when leader type is i or j"
            ),
            "explanation": "Adds local media type for streaming audio records.",
            "confidence": "high",
            "regex": {},
            "params": {
                "tag": "877",
                "ind1": " ",
                "ind2": " ",
                "subfields": [["m", "Streaming Audio"]],
                "condition": "audios",
                "if_absent": False,
            },
        },
        {
            "kind": "add-field",
            "source_text": (
                "add 655 second indicator 7 subfield a Electronic scores. "
                "subfield 2 local when leader type is c or d"
            ),
            "explanation": "Adds a local genre heading for notated music records.",
            "confidence": "high",
            "regex": {},
            "params": {
                "tag": "655",
                "ind1": " ",
                "ind2": "7",
                "subfields": [["a", "Electronic scores."], ["2", "local"]],
                "condition": "scores",
                "if_absent": False,
            },
        },
    ]

    return (
        "Translate the cataloging notes into a MarcEdit Web task draft.\n"
        "\n"
        "Guardrails:\n"
        "- JSON only. Return one JSON object and no Markdown fences.\n"
        "- No Python. Do not emit code, scripts, or custom operations.\n"
        "- Use only the allowed operation kinds and params listed below.\n"
        "- Put ambiguous or unsupported instructions in unsupported_lines or questions.\n"
        "- Preserve the cataloger's order when mapping supported operations.\n"
        "- Include a top-level description.\n"
        "- For every operation include source_text, explanation, and confidence "
        "(high, medium, or low).\n"
        "- For regex operations include a regex object with pattern, meaning, "
        "before, and after strings; use empty strings for non-regex operations.\n"
        "\n"
        "Required response schema:\n"
        f"{json.dumps(schema, indent=2)}\n"
        "\n"
        "Examples of valid add-field operations:\n"
        f"{json.dumps(examples)}\n"
        "\n"
        "For add-field, subfields must be a list of [code, value] pairs. "
        "It is never an object or string.\n"
        "\n"
        "Allowed operations:\n"
        f"{json.dumps(operations, indent=2)}\n"
        "\n"
        "Cataloger notes:\n"
        f"{notes}"
    )


def _payload_for(notes: str) -> dict[str, Any]:
    return {
        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "You are the AI task draft translator for MarcEdit Web. "
                        "Return reviewable task-builder JSON, not executable code."
                    )
                }
            ]
        },
        "contents": [
            {
                "parts": [
                    {
                        "text": build_prompt(notes),
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "thinkingConfig": {
                "thinkingLevel": "low",
            },
        },
    }
