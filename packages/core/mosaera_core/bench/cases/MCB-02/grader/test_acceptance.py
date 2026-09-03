"""Hidden acceptance suite for MCB-02 (the static landing page).

Ground truth — never shown to Mosaera, injected into the delivered workspace only
at grade time. It PARSES the delivered HTML with the stdlib html.parser (no
browser, no network) and asserts the required structure/content/asset-resolution
deterministically — same delivered bytes always yield the same pass/fail.

Runs with the delivered workspace as cwd; it locates index.html under the tree.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

_SKIP = {"_mcb_grader", ".git", ".venv", "node_modules", "__pycache__"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.anchor_hrefs: list[str] = []
        self.img_srcs: list[str] = []
        self.css_hrefs: list[str] = []
        self.tags: set[str] = set()
        self.h1_text = ""
        self.open_tags: list[str] = []
        self.unclosed = False
        self._in_h1 = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        self.tags.add(tag)
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "a" and d.get("href", "").startswith("#"):
            self.anchor_hrefs.append(d["href"])
        if tag == "img" and d.get("src"):
            self.img_srcs.append(d["src"])
        if tag == "link" and "stylesheet" in d.get("rel", "") and d.get("href"):
            self.css_hrefs.append(d["href"])
        if tag == "h1":
            self._in_h1 += 1
        if tag not in _VOID:
            self.open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._in_h1:
            self._in_h1 -= 1
        if tag in _VOID:
            return
        if tag in self.open_tags:
            while self.open_tags and self.open_tags.pop() != tag:
                pass

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self.h1_text += data


def _find_index() -> Path:
    root = Path.cwd()
    direct = root / "index.html"
    if direct.is_file():
        return direct
    for p in sorted(root.rglob("index.html")):
        if not any(part in _SKIP for part in p.relative_to(root).parts):
            return p
    pytest.fail("no index.html was delivered")


@pytest.fixture(scope="module")
def page() -> _Page:
    index = _find_index()
    parser = _Page()
    parser.feed(index.read_text(encoding="utf-8", errors="replace"))
    parser.site_root = index.parent  # type: ignore[attr-defined]
    return parser


def _is_local(ref: str) -> bool:
    return bool(ref) and not ref.startswith(("http://", "https://", "//", "#", "data:", "mailto:"))


def test_index_exists_and_is_well_formed(page: _Page) -> None:
    assert not page.open_tags, f"unclosed tags: {page.open_tags}"
    assert "html" in page.tags and "body" in page.tags


def test_has_nonempty_h1(page: _Page) -> None:
    assert "h1" in page.tags and page.h1_text.strip(), "an <h1> with real text is required"


def test_nav_anchors_resolve_to_sections(page: _Page) -> None:
    assert "nav" in page.tags, "a <nav> is required"
    targets = [h[1:] for h in page.anchor_hrefs]  # strip '#'
    assert len(targets) >= 3, f"expected >=3 in-page nav links, got {page.anchor_hrefs}"
    missing = [t for t in targets if t not in page.ids]
    assert not missing, f"nav links point at ids that do not exist: {missing}"


def test_required_sections_present(page: _Page) -> None:
    assert {"about", "features", "contact"} <= page.ids


def test_has_footer(page: _Page) -> None:
    assert "footer" in page.tags


def test_local_assets_exist(page: _Page) -> None:
    root: Path = page.site_root  # type: ignore[attr-defined]
    for ref in [*page.img_srcs, *page.css_hrefs]:
        if _is_local(ref):
            assert (root / ref).is_file(), f"referenced local asset is missing: {ref}"


def test_stylesheet_linked_and_present(page: _Page) -> None:
    root: Path = page.site_root  # type: ignore[attr-defined]
    local_css = [h for h in page.css_hrefs if _is_local(h)]
    assert local_css, "a local <link rel=stylesheet> is required"
    assert any((root / h).is_file() for h in local_css), "the linked stylesheet is missing"
