import pytest

from accounts import create_user, update_user


def test_create_user_record() -> None:
    assert create_user("alice", 30) == {"action": "create", "name": "alice", "age": 30}


def test_update_user_rejects_bad_age() -> None:
    with pytest.raises(ValueError):
        update_user("bob", 200)
