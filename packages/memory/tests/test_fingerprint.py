"""Offline unit tests for the coverage-ledger fingerprints (issue #32).

Pure functions — no DB, no core. The load-bearing property is that ``region_fingerprint`` survives
LINE CHURN (position shifts, reindentation, blank/comment edits) but flips on a real code change,
while ``source_hash`` flips on ANY change (the rot signal)."""

from __future__ import annotations

from mosaera_memory._fingerprint import region_fingerprint, region_key, source_hash

_BASE = "def add(a, b):\n    # sum\n    return a + b"


def test_region_key_is_posix_file_and_qualname() -> None:
    assert region_key("pkg/mod.py", "Cls.method") == "pkg/mod.py::Cls.method"
    # Windows separators normalize to POSIX so the key is stable cross-platform.
    assert region_key("pkg\\mod.py", "func") == "pkg/mod.py::func"


def test_fingerprint_survives_reindentation() -> None:
    # Same body moved into a class (indented one more level) → same fingerprint (dedented).
    nested = "    def add(a, b):\n        # sum\n        return a + b"
    assert region_fingerprint(_BASE) == region_fingerprint(nested)


def test_fingerprint_survives_blank_and_comment_churn() -> None:
    churned = "def add(a, b):\n\n    # add the two arguments together\n    return a + b\n"
    assert region_fingerprint(_BASE) == region_fingerprint(churned)


def test_fingerprint_survives_trailing_whitespace() -> None:
    trailing = "def add(a, b):   \n    # sum\n    return a + b\t"
    assert region_fingerprint(_BASE) == region_fingerprint(trailing)


def test_fingerprint_flips_on_real_code_change() -> None:
    changed = "def add(a, b):\n    # sum\n    return a - b"  # + → -
    assert region_fingerprint(_BASE) != region_fingerprint(changed)


def test_source_hash_is_exact() -> None:
    # Any change — even a comment — flips the raw hash (rot detection is conservative).
    comment_only = "def add(a, b):\n    # SUM\n    return a + b"
    assert source_hash(_BASE) != source_hash(comment_only)
    assert source_hash(_BASE) == source_hash(_BASE)
    # ...but that same comment-only edit does NOT flip the fingerprint (it's cosmetic).
    assert region_fingerprint(_BASE) == region_fingerprint(comment_only)


def test_hashes_are_hex_sha256() -> None:
    fp, sh = region_fingerprint(_BASE), source_hash(_BASE)
    assert len(fp) == 64 and len(sh) == 64
    assert all(c in "0123456789abcdef" for c in fp + sh)
