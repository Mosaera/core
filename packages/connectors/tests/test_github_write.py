"""GitHub PR create/read + the state mapping (ADR-0114).

The state-mapping tests carry the weight. GitHub reports a merged PR as ``state: closed``
with a separate ``merged: true``; reading ``state`` alone records every merged PR as closed,
so the project never reaches Delivered — precisely the gap this slice exists to close.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest
from mosaera_connectors import github_app as ga
from mosaera_connectors import github_write as gw


class _Resp(io.BytesIO):
    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: Any) -> None:
        return None


def _capture(monkeypatch: pytest.MonkeyPatch, body: Any, status: int = 200) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_open(req: Any, timeout: float | None = None) -> Any:
        seen["method"] = req.method
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)
        seen["data"] = json.loads(req.data) if req.data else None
        if status >= 400:
            body_io = io.BytesIO(json.dumps(body).encode())
            # `{}` for headers, as test_gitlab_write.py does — HTTPError wants a Message.
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, body_io)  # type: ignore[arg-type]
        return _Resp(json.dumps(body).encode())

    # github_write delegates transport to github_app._api — patch where urlopen actually lives.
    monkeypatch.setattr(ga.urllib.request, "urlopen", fake_open)
    return seen


def test_create_pull_request_sends_a_draft_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch, {"html_url": "https://github.com/o/r/pull/7", "number": 7})
    data, err = gw.create_pull_request(
        "https://api.github.com",
        "ghs_tok",
        "o/r",
        head="mosaera/x",
        base="main",
        title="t",
        body="b",
    )
    assert err is None and data["number"] == 7
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.github.com/repos/o/r/pulls"
    assert seen["data"] == {
        "head": "mosaera/x",
        "base": "main",
        "title": "t",
        "body": "b",
        "draft": True,
    }
    # The INSTALLATION token authenticates repository work — never the App JWT.
    assert seen["headers"]["Authorization"] == "Bearer ghs_tok"


def test_a_multi_line_body_survives_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    """GitLab's push-options transport flattens newlines and truncates at 800 chars; REST does
    not, so the delivery report reaches a PR whole."""
    body = "line one\n\nline two\n\n" + ("x" * 2000)
    seen = _capture(monkeypatch, {"html_url": "u", "number": 1})
    gw.create_pull_request(
        "https://api.github.com", "t", "o/r", head="h", base="b", title="t", body=body
    )
    assert seen["data"]["body"] == body


def test_list_pull_requests_qualifies_head_with_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _capture(monkeypatch, [])
    gw.list_pull_requests("https://api.github.com", "t", "acme/widget", head_branch="mosaera/x")
    assert seen["url"] == (
        "https://api.github.com/repos/acme/widget/pulls?head=acme:mosaera/x&state=open"
    )


def test_get_pull_request_reads_by_number(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch, {"number": 7, "state": "open"})
    gw.get_pull_request("https://api.github.com", "t", "o/r", 7)
    assert seen["method"] == "GET"
    assert seen["url"] == "https://api.github.com/repos/o/r/pulls/7"


def test_a_create_failure_is_returned_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, {"message": "Validation Failed"}, status=422)
    data, err = gw.create_pull_request(
        "https://api.github.com", "t", "o/r", head="h", base="b", title="t", body=""
    )
    assert data is None and err is not None and err.startswith("422")


@pytest.mark.parametrize(
    ("pr", "expected"),
    [
        ({"state": "open", "merged": False}, "opened"),
        ({"state": "closed", "merged": False}, "closed"),
        ({"state": "closed", "merged": True}, "merged"),
        # The trap: merged PRs report state=closed. Reading `state` alone loses the merge.
        ({"state": "closed", "merged": True, "merged_at": "2026-08-24T00:00:00Z"}, "merged"),
        ({}, "closed"),
    ],
)
def test_github_state_maps_onto_the_existing_vocabulary(pr: dict, expected: str) -> None:
    assert gw.pull_request_state(pr) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/o/r/pull/7", 7),
        ("https://github.com/o/r/pull/123#issuecomment-1", 123),
        ("https://gitlab.example.com/g/p/-/merge_requests/7", None),
        ("", None),
        ("not a url", None),
    ],
)
def test_pr_number_extraction_does_not_collide_with_gitlab_urls(
    url: str, expected: int | None
) -> None:
    assert gw.pr_number_from_url(url) == expected
