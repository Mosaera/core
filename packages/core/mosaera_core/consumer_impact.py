"""The MODIFY oracle — who depends on the behaviour being changed (verb-arc slice 4).

Split out of ``claim_oracles.py`` (at the 500-line ceiling) rather than shaved from someone else's
comments — the same precedent `_exec.py` set in slice 2.1, and the module is cohesive on its own
terms: it answers one question, and that question is Hyrum's Law.

A MODIFY item deliberately changes behaviour, so the test asserting the OLD behaviour fails. To the
gate that is `validation_failed`, indistinguishable from *"the code is wrong"* — so the run grinds
to the cap against a test it may not touch, or the coder rewrites the contract that judges it.

The mint pattern cannot tell a real modification from a feature (a MODIFY verb is how ordinary work
is described), so **the oracle is the discriminator**, using a fact no regex can see: did anything
already depend on this symbol? That inverts slice 1, where `_REMOVAL` had to be narrow precisely
because `non_use_proven` could not make the distinction.
"""

from __future__ import annotations

import ast
import contextlib
from typing import Any

from mosaera_core.testintegrity import is_test_file


def _head_text(workspace: Any, rel: str) -> str:
    """The file's content at HEAD, or ``""`` when it did not exist there."""
    with contextlib.suppress(Exception):
        return str(workspace.repo.git.show(f"HEAD:{rel}"))
    return ""


def _symbol_pre_existed(
    workspace: Any, symbol: str, defining: list[str], referencing: list[str]
) -> bool:
    """Did anything already DEPEND on ``symbol``? The filter that makes slice 4's mint safe.

    Two ways to be sure, and the second exists because of red-team R2. Checking only the symbol's
    CURRENT defining files misses a symbol that MOVED: the new file is absent at HEAD, so a real
    modification read as "new code" and its consumers went unassessed — a false `satisfied`, which
    is the only unsafe direction this oracle has.

    So a pre-existing CONSUMER also counts. That is not a patch on the first check; it is the
    better question. Hyrum's Law is about dependants, and "something already referenced this
    before the run" is exactly what makes a behaviour change able to break someone.

    SYMBOL-level, not file-level — a brand-new function added to a pre-existing file is new code,
    and a file-level check would demand a witness for something nothing could have depended on.

    Deny-by-default: unparseable HEAD content resolves ``True`` (assume it pre-existed, so the
    claim IS assessed). Guessing "new" would wave a real behaviour change through.
    """

    def _defines_or_uses(text: str, want_def: bool) -> bool | None:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            return None
        if want_def:
            return any(
                isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and n.name == symbol
                for n in ast.walk(tree)
            )
        return any(
            (isinstance(n, ast.Name) and n.id == symbol)
            or (isinstance(n, ast.Attribute) and n.attr == symbol)
            or (isinstance(n, ast.alias) and (n.name == symbol or n.asname == symbol))
            for n in ast.walk(tree)
        )

    for rel, want_def in [(d, True) for d in defining] + [(r, False) for r in referencing]:
        original = _head_text(workspace, rel)
        if not original:
            continue  # absent at HEAD — ordinary "this run added the file"
        hit = _defines_or_uses(original, want_def)
        if hit is None:
            return True  # cannot tell ⇒ assess it
        if hit:
            return True
    return False


def eval_consumer_impact(text: str, workspace: Any) -> tuple[str, str]:
    """A behaviour-change claim's verdict (slice 4). **The oracle is the discriminator.**

    A MODIFY verb is how ordinary work is described, so the pattern that mints this claim cannot
    tell a real modification from a feature. This can, using a fact no regex can see: *did the named
    symbol already exist?* A modification changes existing code; a feature adds new code.

    That filter is what makes minting broadly safe, and it is the inverse of slice 1's design —
    `_REMOVAL` had to be narrow only because `non_use_proven` could not make this distinction.

    Once it IS a modification, the question is Hyrum's Law: who depends on the behaviour being
    changed? Consumers with no test among them mean the change is unwitnessed — nothing asserts the
    new behaviour, and nothing would notice the old one breaking.
    """
    from mosaera_core.nonuse import consumers_of, removal_target

    root = getattr(workspace, "root", None)
    if root is None:
        return "failed", "no workspace to examine — impact unassessed"
    target = removal_target(text)  # same code-span convention as a removal claim
    if not target:
        return "failed", "the claim names no symbol (use a `code span`) — impact unassessed"
    found = consumers_of(root, target)
    if found is None:
        return "failed", f"could not enumerate consumers of `{target}` — impact unassessed"
    referencing, defining = found
    if not defining:
        return "satisfied", f"`{target}` is defined nowhere in the tree — nothing to assess"
    from mosaera_core.nonuse import _symbol_of

    if not _symbol_pre_existed(workspace, _symbol_of(target), defining, referencing):
        # THE FILTER: the symbol did not exist at HEAD, so nothing could have depended on a
        # previous behaviour. A feature, not a modification — the claim does not apply.
        return "satisfied", f"`{target}` is new in this change — not a modification"
    if not referencing:
        return "satisfied", f"`{target}` has no consumers besides its own definition"
    witnesses = [r for r in referencing if is_test_file(r)]
    if not witnesses:
        return "failed", (
            f"`{target}` is used by {', '.join(referencing[:5])} and NO test — a behaviour change "
            "nothing asserts"
        )
    return "satisfied", f"`{target}`'s change is witnessed by {', '.join(witnesses[:5])}"
