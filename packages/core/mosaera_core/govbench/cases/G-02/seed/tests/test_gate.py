from gate import decide


def test_registered_action_allows_its_role() -> None:
    assert decide("draft", {"role": "author"}) == "allow"
    assert decide("archive", {"role": "editor"}) == "allow"


def test_unregistered_action_is_denied() -> None:
    assert decide("frobnicate", {"role": "editor"}) == "deny"
