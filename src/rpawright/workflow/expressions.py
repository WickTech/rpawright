"""Sandboxed ``{{ expr }}`` evaluation for workflow strings.

Security model
--------------
* Only ``{{ expression }}`` is allowed.  Statements (``{% %}``) and comments (``{# #}``) are
  rejected, so a bot cannot use loops/macros/includes.
* The environment is an ``ImmutableSandboxedEnvironment`` with an explicit allowlist of filters
  and tests and **no globals** (no ``range``, ``dict``, ``lipsum``, ``cycler``, ...).
* ``StrictUndefined``: any undefined name or attribute is an ``ExpressionError``.
* ``**``, ``*`` and ``%`` are intercepted at render time and size-capped, because Jinja would
  otherwise constant-fold e.g. ``9**99999999`` while compiling (a DoS for ``validate``).
* **No calls at all**: ``f(...)`` and ``obj.method(...)`` raise ``ExpressionError``.  Methods
  (``'a'.ljust(10**10)``, ``(1).to_bytes(...)``, ``inputs.items()``) can amplify memory, so they
  are unavailable; use the filters instead.  Filters and tests do not go through ``call``.
* Amplification is capped: repeated sequences by deep size, ``join`` output by length, and every
  result (native or rendered text) by a final size limit.  Native results must be plain data
  (text, numbers, bool, None, dates, and lists/dicts of those); ``self`` is not a valid name.
* ``format``/``format_map`` attribute access is blocked and ``fmt`` only ever calls the builtin
  ``format(value, spec)`` / ``strftime`` with a bounded spec, never ``spec.format(...)``.

Single-evaluation invariant (R25)
---------------------------------
Only YAML-authored strings may be passed to :func:`evaluate`, and each exactly once.  The output
of an evaluation (page data, CSV cells, HTTP bodies, inputs, vars) must never be fed back into
:func:`evaluate`, otherwise untrusted data would become template code.  Nothing in this module
re-renders its own output.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError, nodes, pass_eval_context
from jinja2.exceptions import SecurityError
from jinja2.filters import FILTERS as DEFAULT_FILTERS
from jinja2.nodes import EvalContext
from jinja2.runtime import Context, Undefined
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.tests import TESTS as DEFAULT_TESTS

_ENV_PREFIX = "RPAWRIGHT_ENV_"
_MAX_RESULT_BITS = 1000
_MAX_REPEAT_LEN = 100_000
_MAX_SPEC_LEN = 20
_MAX_SPEC_NUMBER = 100
_MAX_DEPTH = 8
_MAX_JOIN_LEN = 100_000
_MAX_RESULT_SIZE = 1_000_000
_STATEMENT_MESSAGE = "only {{ }} expressions are allowed (no {% %} or {# #})"
_FORBIDDEN_TOKENS = frozenset(
    {"block_begin", "comment_begin", "raw_begin", "linestatement_begin", "linecomment_begin"}
)
_ALLOWED_FILTERS = ("default", "length", "lower", "upper", "trim") + (
    "first",
    "last",
    "int",
    "float",
    "string",
    "join",
)
_ALLOWED_TESTS = ("defined", "undefined", "none", "string", "number")


class ExpressionError(Exception):
    """A bad or disallowed expression.  ``where`` is filled in by templating."""

    def __init__(self, message: str, expression: str = "", where: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.expression = expression
        self.where = where

    def __str__(self) -> str:
        if not self.expression:
            return self.message
        shown = self.expression[:80] + ("..." if len(self.expression) > 80 else "")
        return f"{self.message} in {{{{ {shown} }}}}"


class Unavailable:
    """Namespace placeholder whose attribute/item access raises ``ExpressionError``."""

    def __init__(self, kind: str, message: str) -> None:
        self._kind = kind
        self._message = message

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        raise ExpressionError(self._message)

    def __getitem__(self, key: object) -> Any:
        raise ExpressionError(self._message)

    def __str__(self) -> str:
        raise ExpressionError(self._message)

    def __repr__(self) -> str:
        return f"<{self._kind} unavailable>"


SECRET = Unavailable("secret", "secrets arrive with the vault in M3")
ASSET = Unavailable("asset", "assets arrive with assets.yaml in M3")


def env_namespace(environ: Mapping[str, str]) -> dict[str, str]:
    """``env.NAME`` view: only ``RPAWRIGHT_ENV_NAME`` variables, prefix stripped (R3)."""
    return {
        key[len(_ENV_PREFIX) :]: value
        for key, value in environ.items()
        if key.startswith(_ENV_PREFIX) and len(key) > len(_ENV_PREFIX)
    }


# --- filters -------------------------------------------------------------------------------


def _fmt(value: object, spec: str) -> str:
    if not isinstance(spec, str) or len(spec) > _MAX_SPEC_LEN:
        raise ExpressionError(f"fmt spec must be text of at most {_MAX_SPEC_LEN} characters")
    try:
        if isinstance(value, date):  # datetime is a date
            return value.strftime(spec)
        if isinstance(value, int | float):
            if any(int(n) > _MAX_SPEC_NUMBER for n in re.findall(r"\d+", spec)):
                raise ExpressionError(f"fmt width/precision must be <= {_MAX_SPEC_NUMBER}")
            return format(value, spec)
    except ExpressionError:
        raise
    except (ValueError, TypeError) as exc:
        raise ExpressionError(f"invalid fmt spec {spec!r}: {exc}") from exc
    raise ExpressionError("fmt needs a date, datetime, int or float value")


def _prev_month(value: object) -> date:
    if isinstance(value, datetime):
        value = value.date()
    elif isinstance(value, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            raise ExpressionError("prev_month needs a date or YYYY-MM-DD text")
        try:
            value = date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ExpressionError(f"prev_month: {exc}") from exc
    if not isinstance(value, date):
        raise ExpressionError("prev_month needs a date, datetime or YYYY-MM-DD text")
    return (value.replace(day=1) - (date(2000, 1, 2) - date(2000, 1, 1))).replace(day=1)


def _where(rows: object, key: object, value: object) -> list[object]:
    if not isinstance(rows, list | tuple):
        raise ExpressionError("where needs a list of rows")
    wanted = str(value).strip()
    return [
        row
        for row in rows
        if isinstance(row, Mapping) and key in row and str(row[key]).strip() == wanted
    ]


# --- environment ---------------------------------------------------------------------------


def _is_repeatable(value: object) -> bool:
    return isinstance(value, str | bytes | list | tuple)


def _is_int(value: object) -> bool:
    return isinstance(value, int)


def _deep_size(value: object, limit: int, depth: int = 0) -> int:
    """Characters plus scalar leaves of ``value``; returns early once above ``limit``."""
    if isinstance(value, str | bytes):
        return len(value)
    if isinstance(value, list | tuple | set | frozenset | dict):
        if depth >= _MAX_DEPTH:
            return limit + 1
        total = 0
        items = [x for kv in value.items() for x in kv] if isinstance(value, dict) else value
        for item in items:
            total += _deep_size(item, limit - total, depth + 1)
            if total > limit:
                return total
        return max(total, 1)
    return 1


@pass_eval_context
def _join(eval_ctx: EvalContext, value: Any, d: object = "", attribute: Any = None) -> Any:
    original = DEFAULT_FILTERS["join"]
    if attribute is None:
        items = list(value)
        if _deep_size(items, _MAX_JOIN_LEN) + len(items) * len(str(d)) > _MAX_JOIN_LEN:
            raise ExpressionError(f"join output exceeds {_MAX_JOIN_LEN} characters")
        value = items
    result = original(eval_ctx, value, d, attribute)
    if len(result) > _MAX_JOIN_LEN:
        raise ExpressionError(f"join output exceeds {_MAX_JOIN_LEN} characters")
    return result


def _check_result(value: object, budget: list[int], depth: int = 0) -> None:
    """Native results must be plain data of bounded size (R25 / DoS last line of defense)."""
    if isinstance(value, Unavailable):
        raise ExpressionError(value._message)
    if isinstance(value, Undefined):
        str(value)  # StrictUndefined raises its own descriptive error here
        raise ExpressionError("undefined value")  # pragma: no cover - defensive
    if value is None or isinstance(value, bool | int | float | date):
        budget[0] -= 1
    elif isinstance(value, str):
        budget[0] -= max(len(value), 1)
    elif isinstance(value, list | tuple | dict):
        if depth >= _MAX_DEPTH:
            raise ExpressionError("result is nested too deeply")
        budget[0] -= 1
        if isinstance(value, dict):
            for key, item in value.items():
                _check_result(key, budget, depth + 1)
                _check_result(item, budget, depth + 1)
        else:
            for item in value:
                _check_result(item, budget, depth + 1)
    else:
        raise ExpressionError(f"{type(value).__name__} values are not allowed as results")
    if budget[0] < 0:
        raise ExpressionError(f"result exceeds {_MAX_RESULT_SIZE} characters/elements")


class _SafeEnvironment(ImmutableSandboxedEnvironment):
    intercepted_binops = frozenset({"**", "*", "%"})

    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        if attr in ("format", "format_map"):
            return False
        return super().is_safe_attribute(obj, attr, value)

    def wrap_str_format(self, value: Any) -> Any:
        return None  # the unsafe-attribute check in is_safe_attribute blocks ``str.format``

    def call(self, __context: Context, __obj: Any, *args: Any, **kwargs: Any) -> Any:
        raise SecurityError(
            "calling functions or methods is not allowed in expressions; use filters"
        )

    def call_binop(self, context: Context, operator_: str, left: Any, right: Any) -> Any:
        if operator_ == "%" and isinstance(left, str | bytes):
            raise SecurityError("'%' string formatting is not allowed")
        if operator_ == "**" and _is_int(left) and _is_int(right):
            if abs(left) > 1 and right > 0 and (left.bit_length() - 1) * right > _MAX_RESULT_BITS:
                raise SecurityError(f"result of ** exceeds {_MAX_RESULT_BITS} bits")
        elif operator_ == "*":
            for seq, count in ((left, right), (right, left)):
                if _is_repeatable(seq) and _is_int(count):
                    times = max(count, 0)
                    if (
                        len(seq) * times > _MAX_REPEAT_LEN
                        or _deep_size(seq, _MAX_REPEAT_LEN) * times > _MAX_REPEAT_LEN
                    ):
                        raise SecurityError(f"repeated length exceeds {_MAX_REPEAT_LEN}")
            if _is_int(left) and _is_int(right):
                if left.bit_length() + right.bit_length() > _MAX_RESULT_BITS:
                    raise SecurityError(f"result of * exceeds {_MAX_RESULT_BITS} bits")
        result = super().call_binop(context, operator_, left, right)
        if _is_int(result) and result.bit_length() > _MAX_RESULT_BITS:
            raise SecurityError(f"result of {operator_} exceeds {_MAX_RESULT_BITS} bits")
        return result


def make_environment() -> ImmutableSandboxedEnvironment:
    env = _SafeEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
    env.filters.clear()
    env.tests.clear()
    env.globals.clear()
    for name in _ALLOWED_FILTERS:
        env.filters[name] = DEFAULT_FILTERS[name]
    for name in _ALLOWED_TESTS:
        env.tests[name] = DEFAULT_TESTS[name]
    env.filters["join"] = _join
    env.filters["fmt"] = _fmt
    env.filters["prev_month"] = _prev_month
    env.filters["where"] = _where
    return env


_ENV = make_environment()


# --- parsing helpers -----------------------------------------------------------------------


def _token_kinds(env: Environment, text: str) -> list[str]:
    return [tok[1] for tok in env.lex(text)]


def _whole_inner(env: Environment, text: str) -> str | None:
    s = text.strip()
    if not (s.startswith("{{") and s.endswith("}}")) or s.startswith("{{-") or s.endswith("-}}"):
        return None
    try:
        kinds = _token_kinds(env, s)
    except TemplateError:
        return None
    if (
        kinds.count("variable_begin") == 1
        and kinds.count("variable_end") == 1
        and "data" not in kinds
        and not _FORBIDDEN_TOKENS & set(kinds)
    ):
        return s[2:-2]
    return None


def is_whole_expression(text: str) -> bool:
    """True when ``text`` is exactly one ``{{ expr }}`` (surrounding whitespace allowed)."""
    return _whole_inner(_ENV, text) is not None


def _reject_statements(env: Environment, text: str) -> None:
    if _FORBIDDEN_TOKENS & set(_token_kinds(env, text)):
        raise ExpressionError(_STATEMENT_MESSAGE)
    tree = env.parse(text)
    for node in tree.body:
        if not isinstance(node, nodes.Output):
            raise ExpressionError(_STATEMENT_MESSAGE)
    if any(name.name == "self" for name in tree.find_all(nodes.Name)):
        raise ExpressionError("'self' is not available in expressions")


def _describe(exc: Exception, expression: str) -> ExpressionError:
    if isinstance(exc, ExpressionError):
        if not exc.expression:
            exc.expression = expression
        return exc
    if isinstance(exc, TemplateError):
        message = getattr(exc, "message", None) or str(exc)
    else:
        message = str(exc) or type(exc).__name__
        if not isinstance(exc, ArithmeticError | TypeError | ValueError):
            message = f"{type(exc).__name__}: {message}"
    return ExpressionError(message, expression)


def evaluate(text: str, namespace: Mapping[str, object], *, native: bool) -> object:
    """Evaluate one YAML-authored string, once (see the module docstring)."""
    env = _ENV
    expression = text
    try:
        _reject_statements(env, text)
        inner = _whole_inner(env, text)
        if inner is not None:
            expression = inner.strip()
            result = env.compile_expression(inner, undefined_to_none=False)(dict(namespace))
            _check_result(result, [_MAX_RESULT_SIZE])
            return result if native else str(result)
        rendered = env.from_string(text).render(dict(namespace))
        if len(rendered) > _MAX_RESULT_SIZE:
            raise ExpressionError(f"result exceeds {_MAX_RESULT_SIZE} characters/elements")
        return rendered
    except Exception as exc:
        raise _describe(exc, expression) from exc


def check_syntax(text: str) -> str | None:
    """Compile (never run) ``text``; return an error message or ``None``."""
    env = _ENV
    try:
        _reject_statements(env, text)
        inner = _whole_inner(env, text)
        if inner is not None:
            env.compile_expression(inner, undefined_to_none=False)
        else:
            env.from_string(text)
    except Exception as exc:
        return _describe(exc, "").message
    return None
