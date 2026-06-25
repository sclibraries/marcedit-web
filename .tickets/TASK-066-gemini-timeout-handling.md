# TASK-066 — Handle Gemini socket timeouts

**Status:** Completed

## Title

Wrap Gemini socket timeouts as review-panel errors instead of Streamlit
tracebacks.

## Scope

- Catch timeout exceptions raised directly by `urllib.request.urlopen`.
- Convert them into `GeminiTaskDraftError` with a clear retryable message.
- Keep existing HTTP, URL, JSON, and validation error behavior unchanged.

## Success Criteria

1. A `socket.timeout` from Gemini becomes `GeminiTaskDraftError`.
2. The error message tells the user the Gemini request timed out.
3. Focused Gemini tests pass.
