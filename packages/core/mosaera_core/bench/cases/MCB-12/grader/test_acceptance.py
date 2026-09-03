"""Hidden acceptance suite for MCB-12 (add `:param` support to the Router).

Ground truth — never shown to the agent, injected at grade time. Exercises the
public `Router.add`/`match` as a black box; broader than the seed's visible tests,
covering static routes, single and multi param capture, segment-count strictness,
and the None-on-no-match contract.
"""

from __future__ import annotations

from router import Router


def _router() -> tuple[Router, object, object, object]:
    r = Router()
    h1 = lambda: "static"  # noqa: E731
    h2 = lambda: "one-param"  # noqa: E731
    h3 = lambda: "two-params"  # noqa: E731
    r.add("/users", h1)
    r.add("/users/:id", h2)
    r.add("/users/:id/posts/:pid", h3)
    return r, h1, h2, h3


def test_static_route_matches_exactly() -> None:
    r, h1, _h2, _h3 = _router()
    result = r.match("/users")
    assert result is not None
    handler, params = result
    assert handler is h1
    assert params == {}


def test_single_param_captured() -> None:
    r, _h1, h2, _h3 = _router()
    result = r.match("/users/42")
    assert result is not None
    handler, params = result
    assert handler is h2
    assert params == {"id": "42"}


def test_multiple_params_captured() -> None:
    r, _h1, _h2, h3 = _router()
    result = r.match("/users/42/posts/7")
    assert result is not None
    handler, params = result
    assert handler is h3
    assert params == {"id": "42", "pid": "7"}


def test_unknown_path_returns_none() -> None:
    r, _h1, _h2, _h3 = _router()
    assert r.match("/nope") is None


def test_too_many_segments_does_not_match() -> None:
    r, _h1, _h2, _h3 = _router()
    # "/users/:id" must not match a longer path — segment counts differ.
    assert r.match("/users/42/extra") is None


def test_param_value_is_the_literal_segment() -> None:
    r, _h1, h2, _h3 = _router()
    result = r.match("/users/alice")
    assert result is not None
    handler, params = result
    assert handler is h2
    assert params == {"id": "alice"}
