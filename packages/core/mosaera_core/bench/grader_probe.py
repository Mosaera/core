"""Would the HIDDEN grader have caught what the authored test missed? (bench diagnostic)

Across the corpus, the dominant Layer-2 refusal is *"the authored test does not catch a mutation
of the change"* — the model wrote a test that passes the delivered code but would not notice if
that code were wrong. A rubber stamp. The open question is whether that is a fixable
**authoring-quality** gap or evidence that mutation is simply not the discriminator.

The hidden grader answers it, because it is the same shape of artifact (an acceptance suite) written
to the same requirement — only by a human who knew the answer. So: run the SAME mutation check on
the SAME changed lines with the grader as the test suite.

- grader CATCHES what the authored test missed → the gap is test-authoring quality. Tractable.
- grader ALSO misses → mutation is not the discriminator, and the approach needs rethinking.
  The more important finding of the two.

**This is a diagnostic and can never be a gate.** The grader is the benchmark's answer key — the
independent judge whose whole value is that the deciding mechanism never sees it. If it ever fed a
verdict we would have one judge in two hats and the false-ship rate would be unmeasurable by
construction. It runs strictly AFTER the real verdict, and it purges the key again on the way out
(F85: leaving it there is what contaminated every Layer-2 safety number measured before 2026-08-09).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from mosaera_core.bench.grade import GRADER_DIR
from mosaera_core.bench.layer2 import _purge_grader
from mosaera_core.mutation import suite_catches_a_mutation


def grader_catches_a_mutation(
    ws: Any,
    sandbox: Any,
    grader_dir: Path,
    source: list[str],
    changed: dict[str, set[int]],
) -> bool | None:
    """``True`` caught / ``False`` survived / ``None`` inconclusive — the grader's answer to the
    question the authored test was asked.

    ``source`` and ``changed`` are the caller's — taken from the real verdict's own
    ``DispositionResult.detail`` rather than recomputed, so the two checks provably ask about the
    same lines. A second origin for "what changed" is how they would quietly diverge.
    """
    if not source or not grader_dir.is_dir():
        return None
    dest = ws.root / GRADER_DIR
    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(grader_dir, dest)
        tests = [
            f"{GRADER_DIR}/{p.relative_to(grader_dir).as_posix()}"
            for p in sorted(grader_dir.rglob("*.py"))
        ]
        if not tests:
            return None
        return suite_catches_a_mutation(
            ws, sandbox, source, tests, changed=changed, comprehensive=True
        )
    except Exception:
        return None
    finally:
        # ALWAYS purge, including on the exception path. The key must not outlive this function —
        # that is the entire F85 lesson, and a diagnostic that reintroduces the leak is worse than
        # no diagnostic at all.
        _purge_grader(ws)
