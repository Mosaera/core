"""ADR-0103: the GitLab REST WRITE client — MR create/edit + branch list.

Mirrors test_gitlab_client's urlopen-monkeypatch style. Asserts method/URL/payload shape
and the (data, error) never-raise contract; no live GitLab.
"""

import io
import json
import urllib.error

import pytest
from mosaera_connectors import gitlab_write as glw


class _Resp(io.BytesIO):
    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a: object) -> None: ...


def _capture(monkeypatch: pytest.MonkeyPatch, body: bytes = b"{}") -> dict:
    seen: dict = {}

    def fake_open(req: object, timeout: int = 0) -> _Resp:
        seen["method"] = req.get_method()  # type: ignore[attr-defined]
        seen["url"] = req.full_url  # type: ignore[attr-defined]
        seen["data"] = json.loads(req.data) if req.data else None  # type: ignore[attr-defined]
        return _Resp(body)

    monkeypatch.setattr(glw.urllib.request, "urlopen", fake_open)
    return seen


def test_create_merge_request_posts_faithful_multiline_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _capture(monkeypatch, b'{"iid": 7, "web_url": "https://gl/mr/7"}')
    body = "line one\n\nline two\n- a\n- b"  # newlines the push-option path would flatten
    data, err = glw.create_merge_request(
        "https://gl",
        "apitok",
        "grp/proj",
        source_branch="mosaera/item-1",
        target_branch="main",
        title="mosaera: thing",
        description=body,
        squash=True,
        remove_source_branch=False,
        labels=["mosaera", "auto"],
    )
    assert err is None and data["iid"] == 7
    assert seen["method"] == "POST"
    assert "projects/grp%2Fproj/merge_requests" in seen["url"]
    # The FULL body with newlines reaches GitLab — the whole point of ADR-0103.
    assert seen["data"]["description"] == body
    assert seen["data"]["squash"] is True
    assert seen["data"]["target_branch"] == "main"
    assert seen["data"]["labels"] == "mosaera,auto"


def test_update_merge_request_puts_only_supplied_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    glw.update_merge_request("https://gl", "apitok", "g/p", 4, title="new", squash=True)
    assert seen["method"] == "PUT"
    assert seen["url"].endswith("/merge_requests/4")
    assert seen["data"] == {"title": "new", "squash": True}  # description/target omitted


def test_update_merge_request_carries_the_lifecycle_verb(monkeypatch: pytest.MonkeyPatch) -> None:
    """`state_event` is how an MR is closed or reopened — the half of the lifecycle the product
    lacked entirely. Asserted HERE, on the real payload, because the API-level tests stub this
    connector out and would pass whether or not the field ever reached GitLab."""
    for action in ("close", "reopen"):
        seen = _capture(monkeypatch)
        glw.update_merge_request("https://gl", "apitok", "g/p", 4, state_event=action)
        assert seen["method"] == "PUT"
        assert seen["data"] == {"state_event": action}  # nothing else is sent


def test_list_branches_gets_with_paging(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch, b'[{"name": "main"}]')
    data, err = glw.list_branches("https://gl", "apitok", "g/p")
    assert err is None and data[0]["name"] == "main"
    assert seen["method"] == "GET"
    assert "repository/branches?per_page=100" in seen["url"]


def test_errors_are_returned_not_raised_and_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b"insufficient_scope"))  # type: ignore[arg-type]

    monkeypatch.setattr(glw.urllib.request, "urlopen", boom)
    data, err = glw.create_merge_request(
        "https://gl",
        "t",
        "g/p",
        source_branch="b",
        target_branch="main",
        title="x",
        description="y",
    )
    assert data is None and err is not None and err.startswith("403")


# --- merge: the only call that changes a real repository's target branch (ADR-0102 amendment) ---


def test_merge_puts_to_the_merge_subresource(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch, b'{"state": "merged", "sha": "abc"}')
    data, err = glw.merge_merge_request("https://gl", "apitok", "grp/proj", 7)
    assert err is None and data["state"] == "merged"
    assert seen["method"] == "PUT"
    assert seen["url"].endswith("projects/grp%2Fproj/merge_requests/7/merge")


def test_a_plain_merge_does_not_ask_for_auto_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two actions are one endpoint, so the flag is the ONLY thing separating 'merge now' from
    'merge later'. Sending it by accident would defer a merge the operator asked for now."""
    seen = _capture(monkeypatch)
    glw.merge_merge_request("https://gl", "apitok", "grp/proj", 7)
    assert "merge_when_pipeline_succeeds" not in (seen["data"] or {})


def test_auto_merge_sends_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    glw.merge_merge_request("https://gl", "apitok", "grp/proj", 7, when_pipeline_succeeds=True)
    assert seen["data"]["merge_when_pipeline_succeeds"] is True


def test_the_head_sha_is_sent_so_a_moved_branch_fails_instead_of_merging_other_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0108's rule on the one action that cannot be undone from this UI: the operator approved a
    specific head, and if the branch moved between the readiness read and the click, GitLab must
    REFUSE rather than merge code nobody was shown."""
    seen = _capture(monkeypatch)
    glw.merge_merge_request("https://gl", "apitok", "grp/proj", 7, sha="deadbeef")
    assert seen["data"]["sha"] == "deadbeef"


def _http_error(monkeypatch: pytest.MonkeyPatch, code: int, body: bytes) -> None:
    def fake_open(req: object, timeout: int = 0) -> None:
        raise urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(body))  # type: ignore[arg-type]

    monkeypatch.setattr(glw.urllib.request, "urlopen", fake_open)


def test_a_refused_merge_returns_the_reason_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every refusal here is actionable — conflicts, a red pipeline, a token without the rights.
    The caller maps them to named messages, so this must carry the code and the detail through."""
    for code, body in (
        (405, b'{"message": "Branch cannot be merged"}'),
        (409, b'{"message": "SHA does not match HEAD of source branch"}'),
        (401, b'{"message": "401 Unauthorized"}'),
        (404, b'{"message": "404 Not found"}'),
    ):
        _http_error(monkeypatch, code, body)
        data, err = glw.merge_merge_request("https://gl", "apitok", "grp/proj", 7)
        assert data is None
        assert err is not None and err.startswith(f"{code}:")
