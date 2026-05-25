"""One literal-safe renderer for every interpolation site in our codegen.

The v2 codebase interpolated user-supplied tags / indicators / subfield
codes / find strings into Python source using bare f-string slots:
``f'delete_tags(record, "{tag}")'``. Most sites used ``{x!r}`` (which is
safe), but enough sites used the bare form that a MarcEdit tasksfile
with a ``"`` or ``\\n`` in the wrong column could escape the string
literal and inject arbitrary Python.

:func:`lit` is the single canonical "safe to splice into Python source"
helper. It wraps ``ast.Constant(value=...)`` through ``ast.unparse``
so the output is a guaranteed-valid Python expression that
round-trips through ``ast.literal_eval``.

Call sites pass user-supplied values through :func:`lit` *before*
interpolating, instead of relying on per-site ``!r``::

    code = f'delete_tags(record, {lit(tag)})'  # safe
    code = f'delete_tags(record, "{tag}")'      # NEVER — pre-v3 pattern

For non-string values (ints, bools, None) :func:`lit` does the right
thing as well, so the helper covers every codegen literal in the
project.
"""

from __future__ import annotations

import ast
from typing import Any

# Only these types may be spliced into generated Python source via
# :func:`lit`. ``ast.Constant.value`` accepts the same set plus tuples
# / frozensets of the same — but ``ast.unparse`` will happily call
# ``repr()`` on arbitrary objects and emit nonsense, so we gate the
# input up front rather than trusting the AST to reject.
_ATOMIC_LITERAL_TYPES = (str, int, float, bool, bytes, complex, type(None))


def _is_literal(value: Any) -> bool:
    if isinstance(value, _ATOMIC_LITERAL_TYPES):
        return True
    if isinstance(value, (tuple, frozenset)):
        return all(_is_literal(v) for v in value)
    return False


def lit(value: Any) -> str:
    """Return a Python source expression literal for ``value``.

    Acceptable types: ``str``, ``int``, ``float``, ``bool``, ``None``,
    ``bytes``, ``complex``, plus tuples/frozensets thereof. Anything
    else raises ``TypeError`` — better to catch misuse at the call site
    than emit text that fails at compile time downstream.
    """
    if not _is_literal(value):
        raise TypeError(
            f"lit() does not accept {type(value).__name__}; "
            "only literal-type values may be spliced into generated code."
        )
    return ast.unparse(ast.Constant(value=value))
