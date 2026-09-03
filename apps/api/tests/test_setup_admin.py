"""Creating the first administrator from the terminal — the step that replaces the setup token."""

from __future__ import annotations

from typing import Any, cast

from mosaera_api.auth import verify_password
from mosaera_api.setup.admin import admin_exists, create_admin
from mosaera_memory import MemoryStore


class _Store:
    """The slice `create_admin` touches. Duck-typed so this runs in the offline suite: what is
    under test is the ORDER of the checks and the words on each refusal, neither of which needs
    Postgres."""

    def __init__(self, users: int = 0, raises: Exception | None = None) -> None:
        self._users, self._raises = users, raises
        self.created: list[tuple[str, str, bool]] = []

    def count_users(self) -> int:
        return self._users

    def create_user(
        self,
        username: str,
        password_hash: str,
        is_admin: bool = False,
        require_first: bool = False,
    ) -> dict:
        if self._raises is not None:
            raise self._raises
        self.created.append((username, password_hash, is_admin))
        return {"id": 1, "username": username, "is_admin": is_admin}


def _s(store: _Store) -> MemoryStore:
    return cast(MemoryStore, store)


def test_it_creates_an_admin_and_never_stores_the_password() -> None:
    store = _Store()
    out = create_admin(_s(store), "alex", "a fine long passphrase")
    assert out.ok and "alex" in out.message
    username, stored, is_admin = store.created[0]
    assert (username, is_admin) == ("alex", True)
    assert stored != "a fine long passphrase" and stored.startswith("scrypt$")
    assert verify_password("a fine long passphrase", stored)


def test_it_refuses_when_the_instance_is_already_claimed() -> None:
    # The race ADR-0040 closed, closed here by construction: no second "first" admin.
    store = _Store(users=1)
    out = create_admin(_s(store), "alex", "a fine long passphrase")
    assert not out.ok and "already has an account" in out.message
    assert store.created == []


def test_it_states_the_credential_rule_rather_than_just_refusing() -> None:
    out = create_admin(_s(_Store()), "a", "a fine long passphrase")
    assert not out.ok and "3-64" in out.message
    short = create_admin(_s(_Store()), "alex", "short")
    assert not short.ok and "15 characters" in short.message


def test_each_store_refusal_keeps_its_own_cause() -> None:
    # "could not create the account" would leave the operator guessing at the one moment they
    # cannot get past.
    taken = create_admin(
        _s(_Store(raises=ValueError("username_taken"))), "alex", "a fine long passphrase"
    )
    assert "taken" in taken.message
    limit = create_admin(
        _s(_Store(raises=ValueError("user_limit"))), "alex", "a fine long passphrase"
    )
    assert "account limit" in limit.message


def test_a_dead_database_is_named_not_swallowed() -> None:
    out = create_admin(
        _s(_Store(raises=RuntimeError("connection refused"))), "alex", "a fine long passphrase"
    )
    assert not out.ok and "could not reach the database" in out.message


def test_a_store_that_raises_is_treated_as_claimed_not_as_empty() -> None:
    """Fail closed. A database we cannot read is not one we may assume is empty — assuming empty is
    exactly how a wizard offers to create a second 'first' administrator."""

    class _Dead:
        def count_users(self) -> int:
            raise RuntimeError("connection reset")

    assert admin_exists(cast(MemoryStore, cast(Any, _Dead()))) is True
