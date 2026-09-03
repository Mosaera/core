from router import Router


def test_static_route_matches() -> None:
    r = Router()
    handler = object()
    r.add("/users", handler)
    result = r.match("/users")
    assert result is not None
    assert result[0] is handler
    assert result[1] == {}


def test_unknown_path_returns_none() -> None:
    r = Router()
    r.add("/users", object())
    assert r.match("/accounts") is None
