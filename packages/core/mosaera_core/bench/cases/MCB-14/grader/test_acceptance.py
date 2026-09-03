"""Hidden acceptance suite for MCB-14 (extract duplicated validation).

Ground truth — never shown to the agent, injected at grade time. Two kinds of
check:

- **behavioural** — the refactor must not change any output; these pass on the
  original copy-pasted code too (a refactor preserves behaviour), and
- **structural** — the shared validation must be extracted into ONE module-level
  helper (a function other than ``create_user`` / ``update_user``) that BOTH public
  functions call. On the seed the validation is inline in each function with no such
  helper, so this FAILS — a run that changes nothing cannot pass.
"""

from __future__ import annotations

import ast
import inspect

import accounts
import pytest
from accounts import create_user, update_user

# --- behavioural: outputs are unchanged by the refactor ---


def test_create_user_record() -> None:
    assert create_user("alice", 30) == {"action": "create", "name": "alice", "age": 30}


def test_update_user_record() -> None:
    assert update_user("bob", 40) == {"action": "update", "name": "bob", "age": 40}


@pytest.mark.parametrize("fn", [create_user, update_user])
@pytest.mark.parametrize(
    ("name", "age"),
    [
        ("", 30),  # empty name
        ("alice", -1),  # age below range
        ("alice", 200),  # age above range
        ("alice", "30"),  # non-int age
    ],
)
def test_invalid_inputs_raise(fn: object, name: object, age: object) -> None:
    with pytest.raises(ValueError):
        fn(name, age)  # type: ignore[operator]


# --- structural: the duplicated validation was extracted into one shared helper ---


def _module_functions() -> dict[str, ast.FunctionDef]:
    mod = ast.parse(inspect.getsource(accounts))
    return {n.name: n for n in mod.body if isinstance(n, ast.FunctionDef)}


def _names_called_in(fn: ast.FunctionDef) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_validation_extracted_into_shared_helper() -> None:
    funcs = _module_functions()
    assert "create_user" in funcs and "update_user" in funcs, (
        "accounts.py must still define create_user and update_user at module level"
    )
    helpers = set(funcs) - {"create_user", "update_user"}
    assert helpers, (
        "expected a module-level helper function (other than create_user / "
        "update_user) holding the extracted validation, but found none — the "
        "validation is still duplicated inline"
    )
    called_by_create = _names_called_in(funcs["create_user"])
    called_by_update = _names_called_in(funcs["update_user"])
    shared = helpers & called_by_create & called_by_update
    assert shared, (
        "both create_user and update_user must call the SAME extracted helper; "
        f"create_user calls {sorted(helpers & called_by_create)}, update_user calls "
        f"{sorted(helpers & called_by_update)}"
    )
