"""Hidden acceptance suite for MCB-05 (refactor checkout_total).

Ground truth — never shown to the agent, injected at grade time. Two kinds of
check:

- **behavioural** — the refactor must not change any output; these pass on the
  original code too (a refactor preserves behaviour), and
- **structural** — ``checkout_total`` must actually be decomposed into a short
  orchestrator that delegates to >= 3 module-level helpers. This FAILS on the
  original one-block function, so a run that changes nothing cannot pass.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import checkout
import pytest
from checkout import checkout_total

# --- behavioural: outputs are unchanged by the refactor ---


def test_empty_cart_is_zero() -> None:
    assert checkout_total([]) == 0.0


def test_single_item_shipping_and_tax() -> None:
    assert checkout_total([{"name": "a", "price": 20.0, "qty": 1}]) == 26.6


def test_bulk_line_discount() -> None:
    assert checkout_total([{"name": "a", "price": 5.0, "qty": 10}]) == 53.6


def test_free_shipping_over_threshold() -> None:
    assert checkout_total([{"name": "a", "price": 30.0, "qty": 2}]) == 64.8


def test_member_discount() -> None:
    assert checkout_total([{"name": "a", "price": 30.0, "qty": 2}], member=True) == 61.56


def test_invalid_qty_raises() -> None:
    with pytest.raises(ValueError):
        checkout_total([{"name": "a", "price": 5.0, "qty": 0}])


# --- structural: the function was genuinely decomposed ---


def _checkout_total_ast() -> ast.FunctionDef:
    src = textwrap.dedent(inspect.getsource(checkout_total))
    node = ast.parse(src).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def test_checkout_total_is_a_short_orchestrator() -> None:
    fn = _checkout_total_ast()
    assert len(fn.body) <= 6, (
        f"checkout_total should be a short orchestrator, but its body has "
        f"{len(fn.body)} statements — extract the work into helpers"
    )


def test_checkout_total_delegates_to_helpers() -> None:
    fn = _checkout_total_ast()
    module_fns = {name for name, _ in inspect.getmembers(checkout, inspect.isfunction)}
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in module_fns
        and node.func.id != "checkout_total"
    }
    assert len(called) >= 3, (
        f"checkout_total should delegate to >= 3 module-level helpers; "
        f"found delegation to {sorted(called)}"
    )
