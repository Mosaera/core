"""The runtime over-strict discriminator (P2 Stage B) — one-sided, both directions pinned.

A false flag points the Proctor's repair at a legitimate test-first bar — the unsafe direction —
so every undecidable case must flag nothing. But a discriminator that flags nothing at all is a
dead diagnostic, so the true-positive path is pinned with equal weight.
"""

from __future__ import annotations

from mosaera_core.authored_overstrict import new_behaviour_tokens, runtime_overstrict

# MCB-21's shape: the task ADDS `tag`/`find`; `list` already works and its format is spec-loose.
_CLAIMS = [
    {"text": "`python -m journal tag <id> <label>` attaches the tag", "material": True},
    {"text": "`python -m journal find <label>` prints matching entries", "material": True},
    {"text": "It already supports `add` and `list`", "material": False},  # premise
]

_SRC = """
def _run(args):
    import subprocess, sys
    return subprocess.run([sys.executable, "-m", "journal", *args], capture_output=True, text=True)

def _make_tagged(label):
    out = _run(["add", "x"]); _run(["tag", out.stdout.strip(), label])

def test_find_prints_matching():
    _make_tagged("work")
    assert "x" in _run(["find", "work"]).stdout

def test_list_format_exact():
    _run(["add", "Buy milk"])
    assert _run(["list"]).stdout == "1 [ ] Buy milk\\n"

def test_tag_missing_id_nonzero():
    assert _run(["tag", "999", "w"]).returncode != 0
"""
_SOURCES = {"tests/test_tags.py": _SRC}


def test_an_old_behaviour_pin_that_fails_the_seed_is_flagged() -> None:
    """THE DIAGNOSTIC. `test_list_format_exact` mentions no new-behaviour token and fails on the
    seed, where `list` already works — provably over-strict."""
    flagged = runtime_overstrict(
        _SOURCES,
        [
            "tests/test_tags.py::test_list_format_exact",
            "tests/test_tags.py::test_find_prints_matching",
        ],
        _CLAIMS,
    )
    assert flagged == ["tests/test_tags.py::test_list_format_exact"]


def test_a_legit_red_new_behaviour_test_is_never_flagged() -> None:
    """THE SAFETY DIRECTION. Every seed failure here exercises `tag`/`find` — the test-first
    contract working as designed. Flagging any would point the repair at a legitimate bar."""
    assert (
        runtime_overstrict(
            _SOURCES,
            [
                "tests/test_tags.py::test_find_prints_matching",
                "tests/test_tags.py::test_tag_missing_id_nonzero",
            ],
            _CLAIMS,
        )
        == []
    )


def test_a_helper_carrying_the_token_unflags_its_caller() -> None:
    """One-hop reachability: `test_find_prints_matching` could delegate everything to
    `_make_tagged` — the token in the helper must count for the caller."""
    src = _SRC.replace('assert "x" in _run(["find", "work"]).stdout', "assert _probe()").replace(
        "def _make_tagged(label):",
        'def _probe():\n    return bool(_run(["find", "w"]).stdout)\n\ndef _make_tagged(label):',
    )
    assert (
        runtime_overstrict(
            {"tests/test_tags.py": src}, ["tests/test_tags.py::test_find_prints_matching"], _CLAIMS
        )
        == []
    )


def test_no_tokens_flags_nothing() -> None:
    """Deny-by-default: with no vocabulary of the new behaviour there is no claim about any test."""
    assert runtime_overstrict(_SOURCES, ["tests/test_tags.py::test_list_format_exact"], []) == []
    prose_only = [{"text": "Make it nicer", "material": True}]
    assert (
        runtime_overstrict(_SOURCES, ["tests/test_tags.py::test_list_format_exact"], prose_only)
        == []
    )


def test_premise_spans_do_not_count_as_new_behaviour() -> None:
    """`list` appears in a PREMISE claim's span; counting it would unflag the exact class this
    module exists to catch. (`list` is also a stop-word — assert via a non-stop premise token.)"""
    claims = [
        {"text": "`render_board` draws the grid", "material": False},  # premise
        {"text": "`move_piece` must validate turns", "material": True},
    ]
    src = "def test_render_pins_format():\n    assert render_board() == 'X|O'\n"
    flagged = runtime_overstrict(
        {"tests/t.py": src.replace("render_board()", "__import__('g').render_board()")},
        ["tests/t.py::test_render_pins_format"],
        claims,
    )
    assert flagged == ["tests/t.py::test_render_pins_format"]


def test_unresolvable_ids_and_unparseable_files_flag_nothing() -> None:
    assert runtime_overstrict(_SOURCES, ["tests/other.py::test_x"], _CLAIMS) == []
    assert runtime_overstrict({"tests/bad.py": "def ("}, ["tests/bad.py::test_x"], _CLAIMS) == []
    assert runtime_overstrict(_SOURCES, None, _CLAIMS) == []


def test_token_extraction_drops_stop_words_and_premises() -> None:
    toks = new_behaviour_tokens(_CLAIMS)
    assert "tag" in toks and "find" in toks and "journal" in toks
    assert "list" not in toks  # premise-only AND a stop-word — both walls hold


def test_harness_vocabulary_cannot_unflag_everything() -> None:
    """THE LESSON THE FIRST FIXTURE TAUGHT. `_run(["-m", "journal", ...])` puts `journal` into
    every test's reachable source via the helper hop, so without the ubiquity filter nothing was
    ever flagged. A token present in EVERY authored test discriminates nothing and is dropped;
    `tag`/`find` — absent from the format-pin test — still do the work."""
    from mosaera_core.authored_overstrict import new_behaviour_tokens

    assert "journal" in new_behaviour_tokens(_CLAIMS), "the raw set keeps it"
    flagged = runtime_overstrict(_SOURCES, ["tests/test_tags.py::test_list_format_exact"], _CLAIMS)
    assert flagged == ["tests/test_tags.py::test_list_format_exact"], (
        "the ubiquity filter must drop harness vocabulary, or the diagnostic is dead"
    )
