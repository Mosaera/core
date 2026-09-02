"""Hidden acceptance suite for MCB-30 (stale comment).

Ground truth. Reads the delivered SOURCE rather than importing it, because the whole
claim is about text that has no runtime effect -- and asserts the behaviour is intact,
which is the half a careless "just edit the comment" could break.
"""

from __future__ import annotations

import pathlib

from ledger import subtotal, with_tax

SRC = pathlib.Path('ledger.py').read_text(encoding='utf-8')


def test_the_comment_was_corrected() -> None:
    assert '# The sales tax rate applied by with_tax.' in SRC


def test_the_stale_comment_is_gone() -> None:
    assert 'Returns the tally in cents' not in SRC


def test_behaviour_is_unchanged() -> None:
    assert subtotal([{'amount': 10}, {'amount': 5}]) == 15
    assert with_tax([{'amount': 10}]) == 12.0
