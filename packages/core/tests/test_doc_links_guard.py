"""The link guard must not report success over content it never read (F64).

`check_doc_links.py` had **no guard-test at all**, which is how F64 survived: prose containing a
stray triple backtick — *"Quincy's ```clarify fence"* — shifted backtick parity, so
`_INLINE_CODE_RE` paired across unrelated text, blanked arbitrary regions, and the links inside were
never examined. The guard printed *"all relative Markdown links resolve"* over a genuinely broken
ADR link for an unknown period.

That is the repo's own rule broken inside a guard — *"zero executed checks is never a pass"*
(docs/architecture/control-register.md) — and the same shape as `#58` (a suite green by vacancy).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "check_doc_links.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("check_doc_links", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run() -> tuple[int, str]:
    # Fixed argv, both elements derived from this file's own location — no input.
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout + proc.stderr


@contextmanager
def _temporarily(path: Path, new_text: str) -> Iterator[None]:
    backup = path.read_text(encoding="utf-8")
    try:
        path.write_text(new_text, encoding="utf-8")
        yield
    finally:
        path.write_text(backup, encoding="utf-8")


def test_the_guard_passes_on_the_current_tree() -> None:
    code, out = _run()
    assert code == 0, out


def test_balanced_backticks_are_not_flagged() -> None:
    mod = _load()
    assert mod.unbalanced_backtick("a `code` span and `another`\n") is None  # type: ignore[attr-defined]
    assert mod.unbalanced_backtick("```\nfenced ` odd inside is fine\n```\n") is None  # type: ignore[attr-defined]


def test_an_odd_backtick_outside_a_fence_is_reported_with_its_line() -> None:
    mod = _load()
    text = "intro\n\nprose with a stray ``` marker\n\nmore prose\n"
    assert mod.unbalanced_backtick(text) == 3  # type: ignore[attr-defined]


def test_f64_reproduced_end_to_end() -> None:
    """The exact 2026-08-06 scenario: a stray triple backtick followed by a broken link.

    Before this check the guard reported *success* here — the link sat in the region the
    inline-code regex had silently blanked.
    """
    adr = _ROOT / "docs" / "adr" / "ADR-0080-intake-clarification.md"
    text = adr.read_text(encoding="utf-8")
    broken = (
        text.replace("the fenced `clarify` block", "the ```clarify fence", 1)
        + "\n\nSee [ADR-0076](ADR-0076-security-scanning-and-severity.md).\n"
    )
    assert broken != text, "the ADR-0080 prose is not in the expected shape"
    with _temporarily(adr, broken):
        code, out = _run()
    assert code == 1, "the guard reported success over content it could not read"
    assert "coverage in these files is UNKNOWN" in out
    assert "ADR-0080" in out
