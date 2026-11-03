import time
from datetime import date, datetime

import pytest

from rpawright.workflow.expressions import (
    ASSET,
    SECRET,
    ExpressionError,
    check_syntax,
    env_namespace,
    evaluate,
    is_whole_expression,
    make_environment,
)

NS: dict[str, object] = {
    "n": 5,
    "rows": [{"Month": "2026-10", "Number": "INV-1"}],
    "today": date(2026, 1, 15),
}


def ev(text: str, **extra: object) -> object:
    return evaluate(text, {**NS, **extra}, native=True)


def test_whole_expression_returns_native_object() -> None:
    assert evaluate("{{ rows }}", NS, native=True) == NS["rows"]
    assert evaluate("  {{ n }} ", NS, native=True) == 5


def test_mixed_text_and_two_expressions_render_string() -> None:
    assert evaluate("INV-{{ n }}", NS, native=True) == "INV-5"
    assert evaluate("{{ n }}{{ n }}", NS, native=True) == "55"


def test_native_false_always_returns_text() -> None:
    assert evaluate("{{ n }}", NS, native=False) == "5"
    assert evaluate("no braces", NS, native=True) == "no braces"
    assert evaluate("line\n", NS, native=False) == "line\n"


def test_undefined_name_is_a_clear_error() -> None:
    with pytest.raises(ExpressionError, match="'missing' is undefined") as info:
        evaluate("{{ missing }}", NS, native=True)
    assert str(info.value) == "'missing' is undefined in {{ missing }}"


def test_undefined_name_in_text_mode_includes_the_expression() -> None:
    with pytest.raises(ExpressionError, match=r"'nope' is undefined in .*nope"):
        evaluate("a {{ nope }} b", NS, native=True)
    with pytest.raises(ExpressionError, match="in .*nope"):
        evaluate("{{ nope }}", NS, native=False)


def test_undefined_attribute_is_a_clear_error() -> None:
    with pytest.raises(ExpressionError, match="no attribute 'x'.* in {{ cfg.x }}"):
        evaluate("{{ cfg.x }}", {"cfg": {"a": 1}}, native=True)


def test_native_result_never_leaks_an_undefined_object() -> None:
    with pytest.raises(ExpressionError):
        evaluate("{{ [missing] }}", NS, native=True)
    with pytest.raises(ExpressionError):
        evaluate("{{ {'k': missing} }}", NS, native=True)


def test_error_text_truncates_long_expressions() -> None:
    err = ExpressionError("boom", "x" * 200)
    assert str(err) == "boom in {{ " + "x" * 80 + "... }}"
    assert str(ExpressionError("boom")) == "boom"


@pytest.mark.parametrize(
    "expr",
    [
        "{{ ''.__class__ }}",
        "{{ ().__class__.__mro__ }}",
        "{{ lipsum.__globals__ }}",
        "{{ cycler.__init__.__globals__ }}",
        "{{ inputs.__class__ }}",
        "{{ inputs.__init__.__globals__ }}",
        "{{ vars.__class__ }}",
        "{{ env.__class__ }}",
        "{{ secret.__class__ }}",
        "{{ asset.__class__ }}",
        "{{ inputs['__class__'] }}",
        "{{ cycler }}",
        "{{ lipsum }}",
        "{{ range(3) }}",
        "{{ dict }}",
        "{{ namespace }}",
        "{{ joiner }}",
        "{{ ''.format }}",
        "{{ '{0.__class__}'.format('') }}",
        "{{ '{0.__class__}'.format(1) }}",
        "{{ n | attr('__class__') }}",
        "{{ rows | map(attribute='Month') }}",
        "{{ n | format('x') }}",
        "{{ rows.append(1) }}",
        "{{ rows | join(',', attribute='__class__') }}",
        "{% for i in rows %}x{% endfor %}",
        "{# note #}x",
        "{{ 9**99999999 }}",
        "{{ 'a' * 10**9 }}",
        "{{ 'a' * 100000 * 100000 }}",
        "{{ [0] * 10**9 }}",
        "{{ 10**(10**10) }}",
        "{{ '%999999999d' % 1 }}",
        "{{ 7 | fmt('{0.__class__}') }}",
        "{{ 7 | fmt('999999999d') }}",
        "{{ 7 | fmt('.999f') }}",
    ],
)
def test_sandbox_escapes_fail_with_expression_error(expr: str) -> None:
    start = time.monotonic()
    with pytest.raises(ExpressionError):
        evaluate(expr, {**NS, "inputs": {"a": 1}, "vars": {}, "env": {}}, native=True)
    assert time.monotonic() - start < 2.0  # compile-time folding must not hang


@pytest.mark.parametrize("expr", ["{{ 9**99999999 }}", "x{{ 'a' * 10**9 }}"])
def test_dos_in_text_mode_fails_fast_too(expr: str) -> None:
    start = time.monotonic()
    with pytest.raises(ExpressionError):
        evaluate(expr, NS, native=False)
    assert time.monotonic() - start < 2.0


def test_small_arithmetic_and_repetition_still_work() -> None:
    assert ev("{{ 2**10 }}") == 1024
    assert ev("{{ n * 3 }}") == 15
    assert ev("{{ 'ab' * 3 }}") == "ababab"
    assert ev("{{ [0] * 3 }}") == [0, 0, 0]
    assert ev("{{ 1.5 * 2 }}") == 3.0
    assert ev("{{ 2 ** 0.5 > 1 }}") is True


def test_binop_caps_are_exact() -> None:
    assert len(str(ev("{{ 'a' * 100000 }}"))) == 100_000
    with pytest.raises(ExpressionError):
        ev("{{ 'a' * 100001 }}")
    assert ev("{{ 2**999 > 0 }}") is True  # exactly 1000 bits
    with pytest.raises(ExpressionError):
        ev("{{ 2**1000 }}")


def test_secret_and_asset_raise_milestone_message() -> None:
    with pytest.raises(ExpressionError, match="secrets arrive with the vault in M3"):
        evaluate("{{ secret.vendor_pass }}", {"secret": SECRET}, native=True)
    with pytest.raises(ExpressionError, match="M3"):
        evaluate("{{ asset['x'] }}", {"asset": ASSET}, native=True)
    with pytest.raises(ExpressionError, match="assets arrive with assets.yaml in M3"):
        evaluate("{{ asset.logo }}", {"asset": ASSET}, native=True)
    with pytest.raises(ExpressionError, match="M3"):
        evaluate("x {{ secret }}", {"secret": SECRET}, native=True)


def test_env_namespace_exposes_only_prefixed_variables() -> None:
    environ = {
        "RPAWRIGHT_ENV_REGION": "eu",
        "RPAWRIGHT_ENV_": "empty-name",
        "RPAWRIGHT_VAULT_KEY": "sekrit",
        "HOME": "/home/x",
    }
    env = env_namespace(environ)
    assert env == {"REGION": "eu"}
    ns = {"env": env}
    assert evaluate("{{ env.REGION }}", ns, native=True) == "eu"
    for expr in ("{{ env.RPAWRIGHT_VAULT_KEY }}", "{{ env.VAULT_KEY }}", "{{ env.HOME }}"):
        with pytest.raises(ExpressionError):
            evaluate(expr, ns, native=True)
    # the vault key value must not be reachable by iterating the namespace either
    assert "sekrit" not in str(evaluate("{{ env }}", ns, native=False))


def test_is_whole_expression() -> None:
    assert is_whole_expression(" {{ a > 1 }} ") and not is_whole_expression("{{ a }} x")
    assert not is_whole_expression("{{ a }}{{ b }}") and not is_whole_expression("true")
    assert is_whole_expression("{{ '}}' }}")
    assert not is_whole_expression("{{- a }}") and not is_whole_expression("{{ a -}}")


def test_check_syntax() -> None:
    assert check_syntax("plain") is None and check_syntax("{{ n | length }}") is None
    assert check_syntax("{{ 1 + }}") is not None
    assert "nope" in (check_syntax("{{ n | nope }}") or "")
    assert "only {{ }}" in (check_syntax("{% if n %}x{% endif %}") or "")
    assert "only {{ }}" in (check_syntax("a {# hidden #} b") or "")
    assert "nope" in (check_syntax("a {{ n | nope }} b") or "")
    # Ruling C1: validate must return promptly (render-time rejection is covered above).
    start = time.monotonic()
    check_syntax("{{ 9**99999999 }}")
    assert time.monotonic() - start < 2.0


def test_filters() -> None:
    assert ev("{{ today | prev_month | fmt('%Y-%m') }}") == "2025-12"
    assert ev("{{ d | prev_month }}", d=date(2026, 3, 31)) == date(2026, 2, 1)
    assert ev("{{ d | prev_month }}", d=datetime(2026, 1, 9, 5)) == date(2025, 12, 1)
    assert ev("{{ '2026-03-31' | prev_month }}") == date(2026, 2, 1)
    with pytest.raises(ExpressionError):
        ev("{{ 'March' | prev_month }}")
    with pytest.raises(ExpressionError):
        ev("{{ 5 | prev_month }}")
    assert ev("{{ rows | where('Month', '2026-10') }}") == NS["rows"]
    assert ev("{{ rows | where('Month', '2026-09') }}") == []
    assert ev("{{ rows | where('Nope', 1) }}") == []
    assert ev("{{ [{'k': 7}] | where('k', ' 7 ') | length }}") == 1
    with pytest.raises(ExpressionError):
        ev("{{ 5 | where('k', 1) }}")
    assert ev("{{ missing | default('d') }}") == "d"
    assert ev("{{ ' A ' | trim | lower }}-{{ 'b' | upper }}") == "a-B"
    assert ev("{{ 7 | fmt('03d') }}") == "007"
    assert ev("{{ 1.5 | fmt('.2f') }}") == "1.50"
    assert ev("{{ [1, 2] | join(',') }}{{ rows | length }}") == "1,21"
    assert ev("{{ [3, 4] | first }}{{ [3, 4] | last }}") == "34"
    assert ev("{{ '7' | int }}") == 7 and ev("{{ '1.5' | float }}") == 1.5
    assert ev("{{ 7 | string }}") == "7"
    with pytest.raises(ExpressionError):
        ev("{{ 'x' | fmt('d') }}")


def test_allowlisted_tests_only() -> None:
    assert ev("{{ missing is undefined }}") is True
    assert ev("{{ n is defined and n is number }}") is True
    with pytest.raises(ExpressionError):
        ev("{{ n is even }}")
    with pytest.raises(ExpressionError):
        ev("{{ n is callable }}")


def test_environment_surface_is_the_allowlist() -> None:
    env = make_environment()
    assert set(env.filters) == {
        "fmt", "where", "prev_month", "default", "length", "lower", "upper",
        "trim", "first", "last", "int", "float", "string", "join",
    }  # fmt: skip
    assert set(env.tests) == {"defined", "undefined", "none", "string", "number"}
    assert not env.globals
    assert env.autoescape is False
    assert env.intercepted_binops == frozenset({"**", "*", "%"})
