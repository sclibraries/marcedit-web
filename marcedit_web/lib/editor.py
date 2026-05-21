"""Editor backing-store for task files.

Sits between the Tasks page and the on-disk task files. Pure file I/O +
AST parsing — no Streamlit dependency — so it can be tested headlessly.

The shape we standardize on for a user task file:

    \"\"\"<docstring>\"\"\"

    from marcedit_web.lib.tasks import task


    @task("<name>", description="<description>")
    def <slug>(record):
        <body>

This is the format `serialize_user_task` emits and `parse_user_task_file`
expects — round-tripping through the editor preserves all three fields.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

logger = logging.getLogger("marcedit_web.editor")

# Valid slug for task names. Lowercase + digits + hyphens, starting with a
# letter or digit. Digit-start is allowed for cataloger conventions like
# `5c-foo`.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def is_valid_slug(name: str) -> bool:
    return bool(name) and bool(_NAME_RE.match(name))


# ---------------------------------------------------------------------------
# Task files
# ---------------------------------------------------------------------------


def task_file_path(tasks_dir: Path, name: str) -> Path:
    """Map a task name to its on-disk filename.

    Python module names can't contain hyphens, so the file uses underscores
    even when the task `name` (the `@task("…")` argument) uses hyphens.
    """
    return tasks_dir / f"{name.replace('-', '_')}.py"


def parse_user_task_file(path: Path) -> dict:
    """Extract `{name, description, body}` from a `tasks/*.py` file.

    Expects exactly one `@task("…", description="…")` decorated function.
    Raises `ValueError` if the file doesn't match — e.g. zero or multiple
    decorated functions, or a non-string-literal name argument.
    """
    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise ValueError(f"{path.name}: syntax error: {exc}") from exc

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        decorated = _find_task_decorator(node)
        if decorated is None:
            continue
        name = _str_constant(decorated.args[0]) if decorated.args else None
        if name is None:
            raise ValueError(
                f"{path.name}: first argument to @task(...) must be a string literal"
            )
        description = ""
        for kw in decorated.keywords:
            if kw.arg == "description":
                val = _str_constant(kw.value)
                if val is not None:
                    description = val
        return {
            "name": name,
            "description": description,
            "body": _extract_function_body(src, node),
        }
    raise ValueError(f"{path.name}: no @task(...) decorated function found")


def _find_task_decorator(func: ast.FunctionDef) -> ast.Call | None:
    """Return the `@task(...)` Call node from a function's decorators, or None."""
    for dec in func.decorator_list:
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Name)
            and dec.func.id == "task"
        ):
            return dec
    return None


def _str_constant(node: ast.AST) -> str | None:
    """Return the string value of an ast.Constant, or None if not a string.

    Python folds adjacent string literals at parse time, so multi-line
    descriptions wrapped in parentheses arrive here as a single Constant —
    we don't need to handle BinOp/JoinedStr explicitly for the format we emit.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_function_body(src: str, func: ast.FunctionDef) -> str:
    """Return the function's body text, dedented to column 0.

    Starts on the line *after* the `def fn(record):` signature so that
    leading `# OP:` comments (or any other annotation comments) belonging
    to the first statement aren't dropped. AST nodes only point at code
    nodes, so `func.body[0].lineno` skips preceding comments — that
    behavior would swallow the first form-builder marker on round-trip.
    """
    if not func.body:
        return ""
    lines = src.splitlines()
    start = func.lineno  # 1-based; this is the `def` line, so +0 in 0-based skips it
    end = func.end_lineno  # 1-based inclusive
    body_lines = lines[start:end]
    indents = [
        len(line) - len(line.lstrip(" "))
        for line in body_lines
        if line.strip()
    ]
    if not indents:
        return ""
    min_indent = min(indents)
    return "\n".join(
        line[min_indent:] if len(line) >= min_indent else line
        for line in body_lines
    )


def serialize_user_task(
    name: str,
    description: str,
    body: str,
    *,
    extra_imports: list[str] | None = None,
) -> str:
    """Render the contents of a `tasks/<slug>.py` file.

    Output is intentionally simple and stable — `parse_user_task_file` round-
    trips back to the same `(name, description, body)` triple.

    `extra_imports` is a list of fully-formed `from … import …` statements to
    place after the standard `from marcedit_web.lib.tasks import task` line.
    The form-builder uses this; raw-code tasks pass None and put their own
    imports inside the body.
    """
    fn_name = name.replace("-", "_")
    if fn_name and fn_name[0].isdigit():
        # Python identifiers can't start with a digit, but task NAMES can
        # (e.g. "5c-eds-cc-core"). Prefix the function with an underscore.
        fn_name = "_" + fn_name
    escaped_desc = description.replace("\\", "\\\\").replace('"', '\\"')
    body_lines = body.splitlines()
    if not body_lines or all(not line.strip() for line in body_lines):
        indented_body = "    pass"
    else:
        indented_body = "\n".join(
            ("    " + line) if line.strip() else ""
            for line in body_lines
        ).rstrip()
    extra_import_block = (
        "\n".join(extra_imports) + "\n" if extra_imports else ""
    )
    return (
        '"""User-added task. Edit via the Tasks page or this file directly."""\n'
        "\n"
        "from marcedit_web.lib.tasks import task\n"
        f"{extra_import_block}"
        "\n"
        "\n"
        f'@task("{name}", description="{escaped_desc}")\n'
        f"def {fn_name}(record):\n"
        f"{indented_body}\n"
    )


def save_user_task(
    tasks_dir: Path,
    name: str,
    description: str,
    body: str,
    *,
    original_name: str | None = None,
    extra_imports: list[str] | None = None,
) -> Path:
    """Write `tasks/<slug>.py`, optionally renaming from `original_name`.

    `extra_imports`, if provided, becomes module-level `from … import …`
    statements after the standard `task` import. The form-builder uses this
    so the operations it generates can reference helpers without polluting
    the function body.

    Raises `ValueError` on invalid name, missing body, or collision with an
    existing file (only when not renaming).
    """
    if not is_valid_slug(name):
        raise ValueError(
            f"invalid task name {name!r}: use lowercase letters, digits, and "
            f"hyphens (e.g. 'strip-oclc-856')"
        )
    new_path = task_file_path(tasks_dir, name)
    is_edit = original_name is not None
    is_rename = is_edit and original_name != name
    if new_path.exists() and not is_edit:
        raise ValueError(
            f"a task file already exists at {new_path.name}; "
            f"pick a different name or open it from the list to edit"
        )
    content = serialize_user_task(
        name, description, body, extra_imports=extra_imports,
    )
    # Pre-flight: compile the rendered file before writing to disk. A
    # syntax error caught here keeps the on-disk file in its previous
    # good state instead of leaving a broken task the loader will skip.
    try:
        compile(content, str(new_path), "exec")
    except SyntaxError as exc:
        raise ValueError(
            f"task code has a syntax error: {exc.msg} (line {exc.lineno})"
        ) from exc
    tasks_dir.mkdir(parents=True, exist_ok=True)
    new_path.write_text(content)
    if is_rename:
        old_path = task_file_path(tasks_dir, original_name)
        if old_path.exists() and old_path != new_path:
            old_path.unlink()
    return new_path


def delete_user_task(tasks_dir: Path, name: str) -> bool:
    """Delete `tasks/<slug>.py`. Returns True if a file was removed."""
    path = task_file_path(tasks_dir, name)
    if not path.exists():
        return False
    path.unlink()
    return True
