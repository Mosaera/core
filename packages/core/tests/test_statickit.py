"""Each helper is pinned against the REAL failure it replaces.

Every case below is taken verbatim from MCB-02's ten runs across two sweeps
(`docs/engineering-history/over-park-anatomy-2026-08-30.md`), where every failure was a bug in the
Proctor's own test infrastructure rather than in the delivered page — the hidden grader passed the
page 100% every time.

This module is copied VERBATIM into the workspace, so these tests exercise byte-for-byte the code
the authored tests import. If a helper is wrong here it is wrong there.
"""

from __future__ import annotations

import pytest
from mosaera_core.statickit import (
    attr_values,
    has_doctype,
    is_local_ref,
    referenced_paths,
    text_of,
    unclosed_tags,
    unresolved_refs,
)

PAGE = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width" />
    <link rel="stylesheet" href="style.css">
    <title>Acme</title>
</head>
<body>
    <header><img src="logo.svg" alt="Acme"></header>
    <h1>Welcome to Acme</h1>
    <nav>
      <a href="#about">About</a>
      <a href="mailto:info@acme.test">Mail us</a>
      <a href="https://example.com/docs">Docs</a>
      <a href="//cdn.example.com/x.js">Protocol relative</a>
      <a href="pricing.html">Pricing</a>
    </nav>
</body>
</html>
"""


# --- the '#about' / 'mailto:' class -----------------------------------------------------------


@pytest.mark.parametrize(
    "ref",
    [
        "#about",
        "mailto:info@acme.test",
        "https://example.com",
        "//cdn.example.com/x.js",
        "tel:+15551234",
        "",
        "   ",
    ],
)
def test_things_that_are_NOT_repository_files(ref: str) -> None:
    """THE defect: `Referenced file '#about' does not exist` refused a correct page twice."""
    assert is_local_ref(ref) is False


@pytest.mark.parametrize(
    "ref", ["style.css", "logo.svg", "pricing.html", "assets/a.png", "/root.css"]
)
def test_things_that_ARE_repository_files(ref: str) -> None:
    assert is_local_ref(ref) is True


def test_only_local_refs_are_collected() -> None:
    assert referenced_paths(PAGE) == ["style.css", "logo.svg", "pricing.html"]


def test_a_reference_inside_a_COMMENT_is_not_a_reference() -> None:
    """Why this parses instead of regexing — a regex cannot tell markup from a mention of it."""
    assert referenced_paths('<!-- <img src="ghost.png"> --><p>hi</p>') == []


def test_query_and_fragment_are_stripped_before_resolving() -> None:
    assert referenced_paths('<link href="style.css?v=2">') == ["style.css"]
    assert referenced_paths('<a href="page.html#top">x</a>') == ["page.html"]


def test_unresolved_refs_needs_an_EXPLICIT_root(tmp_path) -> None:
    """`PosixPath('style.css').exists()` resolved against pytest's cwd, not the site — the
    non-hermetic failure. The root is a required argument so it cannot be forgotten."""
    (tmp_path / "style.css").write_text("body{}")
    (tmp_path / "logo.svg").write_text("<svg/>")
    assert unresolved_refs(tmp_path, PAGE) == ["pricing.html"]
    (tmp_path / "pricing.html").write_text("<p/>")
    assert unresolved_refs(tmp_path, PAGE) == []


# --- the DOCTYPE class ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        "<!doctype html>\n<html></html>",
        "<!DOCTYPE html>\n<html></html>",
        "<!DocType HTML>\n<html></html>",
        "\n\n  <!doctype html public 'x'>",
    ],
)
def test_doctype_is_recognised_in_ANY_case(doc: str) -> None:
    """`assert "<!DOCTYPE html>" in content.lower()` can never hold — it refused a correct page."""
    assert has_doctype(doc) is True


@pytest.mark.parametrize("doc", ["<html></html>", "", "<p>no doctype</p>"])
def test_a_missing_doctype_is_still_reported(doc: str) -> None:
    """The check must keep working, not just stop failing."""
    assert has_doctype(doc) is False


# --- the void-element class -------------------------------------------------------------------


def test_void_elements_are_not_reported_unclosed() -> None:
    """`['html','head','meta','meta','link','body','header','img']` was called unclosed on a
    correct page. meta/link/img close themselves."""
    assert unclosed_tags(PAGE) == []


@pytest.mark.parametrize(
    "void", ["<br>", "<hr>", "<img src='a.png'>", "<input>", "<meta charset='utf-8'>"]
)
def test_every_void_element_individually(void: str) -> None:
    assert unclosed_tags(f"<div>{void}</div>") == []


def test_self_closing_syntax_is_accepted() -> None:
    assert unclosed_tags("<div><br /><img src='a.png' /></div>") == []


def test_a_GENUINELY_unclosed_tag_is_still_caught() -> None:
    """Deny-by-default intact — this is what the check exists for."""
    assert unclosed_tags("<html><body><div><p>x</p></body></html>") == ["div"]


# --- the "used re without importing it" class --------------------------------------------------


def test_text_extraction_without_a_regex() -> None:
    """The Proctor's `re.search(r'<h1>(.*?)</h1>', ...)` raised NameError. It also would not have
    survived an attribute on the tag."""
    assert text_of(PAGE, "h1") == ["Welcome to Acme"]
    assert text_of(PAGE, "title") == ["Acme"]


def test_text_extraction_survives_attributes_and_nesting() -> None:
    assert text_of('<h1 class="big" id="t">Hello <em>there</em></h1>', "h1") == ["Hello there"]


def test_attr_values_reads_what_a_regex_would_miss() -> None:
    assert attr_values(PAGE, "link", "href") == ["style.css"]
    assert attr_values(PAGE, "img", "src") == ["logo.svg"]
    assert attr_values(PAGE, "html", "lang") == ["en"]


def test_a_missing_tag_returns_empty_not_an_error() -> None:
    assert text_of(PAGE, "h7") == []
    assert attr_values(PAGE, "video", "src") == []


# --- the whole page, as the acceptance criteria would actually check it -------------------------


def test_the_real_page_passes_every_check(tmp_path) -> None:
    """The end-to-end point: a CORRECT page must satisfy all of these at once. Every one of the
    seven measured defects failed this exact page."""
    for name in ("style.css", "logo.svg", "pricing.html"):
        (tmp_path / name).write_text("x")
    assert has_doctype(PAGE)
    assert unclosed_tags(PAGE) == []
    assert unresolved_refs(tmp_path, PAGE) == []
    assert text_of(PAGE, "h1") == ["Welcome to Acme"]
    assert attr_values(PAGE, "html", "lang") == ["en"]


def test_optional_end_tags_are_NOT_flagged() -> None:
    """`<ul><li>a<li>b</ul>` is valid HTML. Flagging it would be the over-strict false failure this
    module exists to remove — a stricter checker is not a better one here."""
    assert unclosed_tags("<ul><li>a<li>b</ul>") == []
    assert unclosed_tags("<p>one<p>two") == []
    assert unclosed_tags("<table><tr><td>a<td>b</tr></table>") == []
    assert unclosed_tags("<html><body><p>hi</body></html>") == []


def test_an_absorbed_unclosed_tag_is_not_silently_forgiven() -> None:
    """The first version of `handle_endtag` popped to the match and DISCARDED everything above it,
    so a page missing a `</div>` reported perfectly. Caught by this module's own suite, which is
    the argument for the helpers living here rather than being written per-run."""
    assert unclosed_tags("<html><body><div><p>x</p></body></html>") == ["div"]
    assert unclosed_tags("<div><section><span>x</span></div>") == ["section"]


# --- installation -------------------------------------------------------------------------------


def test_it_installs_only_where_there_is_HTML(tmp_path) -> None:
    """Armed on repo SHAPE. A python-only repo must not gain a static-site helper module."""
    from types import SimpleNamespace

    from mosaera_core.statickit import STATICKIT_REL, install_statickit

    (tmp_path / "app.py").write_text("x = 1")
    assert install_statickit(SimpleNamespace(root=tmp_path)) is None
    assert not (tmp_path / STATICKIT_REL).exists()

    (tmp_path / "index.html").write_text("<!doctype html><html></html>")
    assert install_statickit(SimpleNamespace(root=tmp_path)) == STATICKIT_REL
    assert (tmp_path / STATICKIT_REL).exists()


def test_what_ships_is_BYTE_IDENTICAL_to_what_these_tests_exercise(tmp_path) -> None:
    """The whole argument for the frozen-copy pattern. If the installed file could drift from the
    tested one, the helpers would be as unverified as the code they replace."""
    from pathlib import Path
    from types import SimpleNamespace

    import mosaera_core.statickit as kit

    (tmp_path / "index.html").write_text("<html></html>")
    install = kit.install_statickit(SimpleNamespace(root=tmp_path))
    assert install is not None
    shipped = (tmp_path / install).read_text(encoding="utf-8")
    assert shipped == Path(kit.__file__).read_text(encoding="utf-8")


def test_it_OVERWRITES_a_planted_file(tmp_path) -> None:
    """ADR-0068: the path is predictable and repo content is untrusted, so skip-if-exists would let
    a planted weak module become the helpers every authored test imports."""
    from types import SimpleNamespace

    from mosaera_core.statickit import STATICKIT_REL, install_statickit

    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "tests").mkdir()
    (tmp_path / STATICKIT_REL).write_text("def has_doctype(x):\n    return True\n")
    install_statickit(SimpleNamespace(root=tmp_path))
    assert "def has_doctype(x):\n    return True\n" not in (tmp_path / STATICKIT_REL).read_text()


def test_an_install_failure_never_breaks_the_run(tmp_path) -> None:
    """Best-effort by construction: the Proctor then authors exactly as it does today."""
    from mosaera_core.statickit import install_statickit

    assert install_statickit(object()) is None


def test_it_arms_on_a_GREENFIELD_brief_before_any_html_exists(tmp_path) -> None:
    """The case it was built for. On MCB-02 the Proctor authors BEFORE the coder writes the page,
    so repo shape alone would have installed nothing on the only case with the defect."""
    from types import SimpleNamespace

    from mosaera_core.statickit import STATICKIT_REL, install_statickit

    ws = SimpleNamespace(root=tmp_path)
    assert install_statickit(ws) is None, "empty repo, no task text -> nothing to help with"
    brief = "Build a landing page. Put it in `index.html` with `style.css`."
    assert install_statickit(ws, brief) == STATICKIT_REL
    assert (tmp_path / STATICKIT_REL).exists()


def test_a_python_only_brief_still_installs_nothing(tmp_path) -> None:
    from types import SimpleNamespace

    from mosaera_core.statickit import install_statickit

    assert (
        install_statickit(SimpleNamespace(root=tmp_path), "Fix the off-by-one in bizdays.py")
        is None
    )
