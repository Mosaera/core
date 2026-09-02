import io
import urllib.error

import pytest
from mosaera_connectors import gitlab_client as glc


def test_access_level_and_summary() -> None:
    proj = {
        "path_with_namespace": "mosaera/core",
        "default_branch": "main",
        "permissions": {"project_access": {"access_level": 40}, "group_access": None},
    }
    assert glc.access_level(proj) == 40
    summ = glc.project_summary(proj)
    assert summ == {
        "path": "mosaera/core",
        "access_level": 40,
        "can_push": True,
        "default_branch": "main",
    }


def test_summary_read_only_when_below_developer() -> None:
    assert (
        glc.project_summary({"permissions": {"project_access": {"access_level": 20}}})["can_push"]
        is False
    )


def test_list_merge_requests_encodes_project_and_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    class _Resp(io.BytesIO):
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *a: object) -> None: ...

    def fake_open(req: object, timeout: int = 0) -> _Resp:
        seen["url"] = req.full_url  # type: ignore[attr-defined]
        return _Resp(b'[{"web_url": "https://gl/m/d/-/merge_requests/4"}]')

    monkeypatch.setattr(glc.urllib.request, "urlopen", fake_open)
    data, err = glc.list_merge_requests("https://gl", "tok", "m/d", source_branch="mosaera/item-4")
    assert err is None and data[0]["web_url"].endswith("/4")
    assert "projects/m%2Fd/merge_requests" in seen["url"]
    assert "source_branch=mosaera%2Fitem-4" in seen["url"] and "state=opened" in seen["url"]


def test_get_returns_error_on_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"bad token"))  # type: ignore[arg-type]

    monkeypatch.setattr(glc.urllib.request, "urlopen", boom)
    data, err = glc.get_user("https://gl.example", "tok")
    assert data is None
    assert err is not None and err.startswith("401")


def test_http_status_reads_the_code_out_of_an_error() -> None:
    """A 404 must be distinguishable from a timeout WITHOUT string-matching at the call site:
    callers use it to decide whether a merge request is genuinely gone, and that decision clears
    branch protection."""
    assert glc.http_status("404: Not Found") == 404
    assert glc.http_status("403: insufficient_scope") == 403
    assert glc.http_status(None) is None
    assert glc.http_status("") is None
    # A transport failure carries no status — and must not be mistaken for one.
    assert glc.http_status("<urlopen error [Errno 111] Connection refused>") is None
    assert glc.http_status("timed out") is None
