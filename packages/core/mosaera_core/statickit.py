"""Correct helpers for asserting things about a static site, so a test author need not write them.

**Why this exists.** On a deliverable with no natural test harness the Proctor must author
verification INFRASTRUCTURE — a parser, a link checker, a validator — and that infrastructure is
unreviewed, untested code written by a weak model. Measured on MCB-02 across ten runs of two sweeps
(`docs/engineering-history/over-park-anatomy-2026-08-30.md`), every single failure was a bug in the
Proctor's own helpers rather than in the delivered page:

    NameError: name 're' is not defined                  # used re without importing it
    Referenced file '#about' does not exist              # treated a fragment as a file path
    Referenced asset 'mailto:info@...' does not exist    # treated a mail link as a file path
    assert len(open_tags) == 0                           # hand-rolled parser counts <meta> unclosed
    assert "<!DOCTYPE html>" in content.lower()          # UNSATISFIABLE by construction
    PosixPath('style.css').exists()                      # relative to cwd, not the site root
    assert current_files == {3 named files}              # a README the task never forbade

Seven distinct defects, one case, zero of them about the HTML. The page was correct every time — the
hidden grader passed it 100% on all of them.

**This module is copied VERBATIM into the workspace** (the frozen-copy pattern `refactor_scaffold`
already uses), so the code exercised by our own suite is byte-for-byte the code the authored tests
import. A helper that is wrong here is wrong there, and our tests are the ones that catch it.

Deliberately stdlib-only (`html.parser`, `pathlib`, `urllib.parse`): the sandbox runs the test phase
with `--network none` and no extra packages are installed.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

# Elements with no closing tag. A hand-rolled matcher that does not know these reports a correct
# page as malformed — the MCB-02 failure where `['html','head','meta','meta','link','body',
# 'header','img']` was called "unclosed".
VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

# A reference that does not name a file in this repo. `#about` is a fragment on the current page;
# `mailto:` and `tel:` are not fetched at all; `http(s)` and protocol-relative are remote. Asserting
# any of these exists on disk fails a correct page.
_NON_FILE_SCHEMES = frozenset({"http", "https", "mailto", "tel", "data", "javascript", "ftp"})

# Elements whose END TAG the HTML spec lets you omit. `<ul><li>a<li>b</ul>` is valid, so reporting
# those as unclosed would be exactly the over-strict false failure this module exists to remove.
OPTIONAL_END = frozenset(
    {
        "p",
        "li",
        "dt",
        "dd",
        "option",
        "optgroup",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "td",
        "th",
        "rt",
        "rp",
        "colgroup",
        "caption",
        "html",
        "head",
        "body",
    }
)


def is_local_ref(ref: str) -> bool:
    """True when ``ref`` names a file that should exist in the repository.

    False for a fragment, a non-fetching scheme, a remote URL, and the empty string. This single
    predicate is the whole of the `#about` / `mailto:` class of false failure.
    """
    ref = (ref or "").strip()
    if not ref or ref.startswith("#") or ref.startswith("//"):
        return False
    scheme = urlparse(ref).scheme.lower()
    return not (scheme and scheme in _NON_FILE_SCHEMES)


class _RefCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.refs.append(value)


def referenced_paths(html: str) -> list[str]:
    """Every ``href``/``src`` in ``html`` that names a repository file, fragments and URLs excluded.

    Parsed, not regexed: an attribute inside a comment or a script string is not a reference, and a
    regex cannot tell the difference.
    """
    parser = _RefCollector()
    parser.feed(html)
    parser.close()
    out: list[str] = []
    for ref in parser.refs:
        if not is_local_ref(ref):
            continue
        path = ref.split("#", 1)[0].split("?", 1)[0]
        if path and path not in out:
            out.append(path)
    return out


def unresolved_refs(root: str | Path, html: str) -> list[str]:
    """Referenced repository files that do NOT exist under ``root``.

    ``root`` is REQUIRED and is the site root, never the process's working directory — a relative
    `Path("style.css")` resolves against wherever pytest happened to be started, which is the
    non-hermetic failure this signature exists to prevent.
    """
    base = Path(root)
    return [ref for ref in referenced_paths(html) if not (base / ref.lstrip("/")).exists()]


def has_doctype(html: str) -> bool:
    """True when the document declares an HTML doctype, in ANY case.

    `<!doctype html>` and `<!DOCTYPE html>` are equally valid. Case-folding one side and comparing
    against a literal that carries capitals can never hold — that assertion refused a correct page.
    """
    for line in html.lstrip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.lower().startswith("<!doctype html")
    return False


class _Wellformed(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.orphaned: list[str] = []
        self.unmatched_close: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: object) -> None:
        return  # `<br />` opens and closes at once

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_ELEMENTS:
            return
        if tag in self.stack:
            # Pop to the match. Anything ABOVE it was never closed -- absorbing it silently (the
            # first version of this function did) reports a page with a missing </div> as perfect.
            while self.stack:
                top = self.stack.pop()
                if top == tag:
                    break
                if top not in OPTIONAL_END:
                    self.orphaned.append(top)
        else:
            self.unmatched_close.append(tag)


def unclosed_tags(html: str) -> list[str]:
    """Non-void elements left open, outermost first. ``[]`` means the document nests correctly.

    Void elements are excluded by construction, so `<meta>` and `<img>` never appear here.
    """
    parser = _Wellformed()
    parser.feed(html)
    parser.close()
    left_open = [t for t in parser.stack if t not in OPTIONAL_END]
    return parser.orphaned + left_open


class _TextExtractor(HTMLParser):
    def __init__(self, want: str) -> None:
        super().__init__(convert_charrefs=True)
        self.want = want
        self.depth = 0
        self.chunks: list[str] = []
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == self.want:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == self.want and self.depth:
            self.depth -= 1
            if not self.depth:
                self.found.append("".join(self.chunks).strip())
                self.chunks = []

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.chunks.append(data)


def text_of(html: str, tag: str) -> list[str]:
    """The text inside every ``<tag>``, in document order. Saves authoring a regex — and the regex
    the Proctor wrote for exactly this used `re` without importing it."""
    parser = _TextExtractor(tag.lower())
    parser.feed(html)
    parser.close()
    return parser.found


def attr_values(html: str, tag: str, attr: str) -> list[str]:
    """Every value of ``attr`` on every ``<tag>``, in document order."""
    collected: list[str] = []

    class _A(HTMLParser):
        def handle_starttag(self, t: str, attrs: list[tuple[str, str | None]]) -> None:
            if t == tag.lower():
                for name, value in attrs:
                    if name == attr.lower() and value is not None:
                        collected.append(value)

    parser = _A(convert_charrefs=True)
    parser.feed(html)
    parser.close()
    return collected


# --- installation into the run's workspace ------------------------------------------------------

#: Where the authored tests import it from.
STATICKIT_REL = "tests/_statickit.py"


def install_statickit(workspace: object, task: str = "") -> str | None:
    """Copy THIS module verbatim into the workspace as ``tests/_statickit.py``; ``None`` if it did
    not apply or could not be written.

    Armed when the workspace ALREADY holds HTML **or** the TRUSTED TASK names an ``.html``
    deliverable. Repo shape alone is not enough and the reason is the case this exists for: on a
    greenfield static site there is no HTML at authoring time, because the coder has not written it
    yet -- the Proctor authors first. Arming on shape only would have installed nothing on MCB-02.

    The task is read, never the PM's plan/design paraphrase (the ADR-0066 contract). A lossy
    restatement must not be able to decide what the authored tests may import.

    Overwrites rather than skipping if present, for the ADR-0068 reason `refactor_scaffold` gives:
    the path is predictable and repo content is untrusted, so skip-if-exists would let a planted
    weak file become the helpers every authored test imports.

    Best-effort by construction. A helper module that fails to install must never break a run --
    the Proctor then authors exactly as it does today.

    **Call this BEFORE the authored-test snapshot.** Installed after it, the file appears in
    `after` but not `before`, so `authored_test_files` counts it as one of the Proctor's acceptance
    tests. It carries no `test_` function, so the assertion floor then reads the authored suite as
    asserting nothing and the oracle cannot vouch -- measured as 3/3 `oracle_unverified` with an
    empty `authored_tests` on a case that had been delivering 4/5. It is ENVIRONMENT, not output.
    """
    from pathlib import Path as _Path

    try:
        root = _Path(workspace.root)  # type: ignore[attr-defined]
        names_html = ".html" in (task or "").lower()
        if not names_html and not any(root.rglob("*.html")):
            return None
        source = _Path(__file__).read_text(encoding="utf-8")
        target = root / STATICKIT_REL
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        return STATICKIT_REL
    except Exception:
        return None


# The authoring guidance that points the Proctor at these helpers. Lives beside them so the
# prompt and the functions it names cannot drift apart, and because `_proctor_authoring` sits
# at its size ceiling -- the same reason `faithfulness_block` was extracted from it.
STATICKIT_BLOCK = """

## Helpers are provided — do NOT write your own HTML parsing
`tests/_statickit.py` is installed and TESTED. Import from it rather than hand-rolling a parser, a
link checker or a regex; every one of those written by hand here has been wrong:

    from _statickit import has_doctype, unclosed_tags, unresolved_refs, text_of, attr_values

- `has_doctype(html)` — true for `<!doctype html>` in ANY case.
- `unclosed_tags(html)` — non-void elements left open. `<meta>`/`<img>`/`<br>` never appear, and
  legally-omitted end tags (`<li>`, `<p>`, `<td>`) are not flagged. `[]` means correctly nested.
- `unresolved_refs(root, html)` — referenced files that do not exist. `#anchors`, `mailto:`, `tel:`
  and remote URLs are NOT files and are excluded; pass the site root explicitly (never a bare
  relative path, which resolves against pytest's working directory).
- `text_of(html, "h1")` / `attr_values(html, "html", "lang")` — read content without a regex.

Do not assert an EXACT set of files in the repository: a README the task never forbade is not a
defect. Assert that the files the task NAMES exist.
"""


def statickit_adopted(final: object) -> bool:
    """Did the Proctor actually IMPORT the helpers it was handed?

    Recorded rather than assumed. Three prompt-level levers measured NULL in this arc, and being
    told to use a module is exactly that shape -- so the question gets an answer on every card
    instead of an argument later about whether anyone tried it.
    """
    try:
        get = final.get  # type: ignore[attr-defined]
    except AttributeError:
        return False
    authored = get("authored_tests") or []
    if any("_statickit" in str(path) for path in authored):
        return True
    return "_statickit" in str(get("authored_assertion_digest") or "")
