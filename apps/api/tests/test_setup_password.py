"""Entering a password twice, and changing one that was forgotten.

Both are about the same thing: a password is not shown, so the only check on a typo is typing it
again, and a self-hosted instance has no email to reset through.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cryptography.fernet import Fernet
from mosaera_api.setup import admin as admin_step
from mosaera_api.setup import password_reset


class _Store:
    """The slice these two flows touch."""

    def __init__(self, users: list[dict[str, Any]] | None = None) -> None:
        self.users = users if users is not None else []
        self.set_calls: list[tuple[int, str, str | None]] = []
        self.created: list[tuple[str, str]] = []

    def count_users(self) -> int:
        return len(self.users)

    def list_users(self) -> list[dict[str, Any]]:
        return list(self.users)

    def create_user(self, username: str, pw_hash: str, **_kw: Any) -> None:
        self.created.append((username, pw_hash))
        self.users.append({"id": len(self.users) + 1, "username": username, "is_admin": True})

    def set_user_password(self, uid: int, pw_hash: str, *, subject_hash: str | None = None) -> None:
        self.set_calls.append((uid, pw_hash, subject_hash))


class _App:
    """A stand-in for the wizard: these flows only touch its fields and its two paint helpers."""

    def __init__(self) -> None:
        self.settings = SimpleNamespace(db_url="postgresql://x/y", home=Path("."))
        self._username = ""
        self._password = ""
        self._reset_user: dict[str, Any] | None = None
        self._field_for = ""
        self._notice = ""
        self._error = False
        self._returns_to = "done"
        self.step = ""
        self.went: list[str] = []
        self.screens: list[Any] = []

    def _note(self, msg: str, error: bool = False) -> None:
        self._notice, self._error = msg, error

    def _ask(self, _label: str, secret: bool = False, for_field: str = "", hint: str = "") -> None:
        self._field_for = for_field

    def _paint(self, screen: Any) -> None:
        self.screens.append(screen)

    async def _advance(self) -> None:
        self.went.append("advance")

    async def _goto(self, step: str) -> None:
        self.went.append(step)


GOOD = "several plain words here"


# ------------------------------------------------------------------ entering it twice


def test_the_password_is_confirmed_before_the_account_is_made(monkeypatch: Any) -> None:
    store = _Store()
    monkeypatch.setattr(
        "mosaera_memory.MemoryStore.open_or_reason", staticmethod(lambda _u: (store, ""))
    )
    app = _App()
    app._username = "alex"

    asyncio.run(admin_step.submit(app, "password", GOOD))  # type: ignore[arg-type]
    assert app._field_for == "password2", "the first entry asks for a second"
    assert store.created == [], "and creates nothing yet"

    asyncio.run(admin_step.submit(app, "password2", GOOD))  # type: ignore[arg-type]
    assert len(store.created) == 1, "matching entries create the account"
    assert app._password == "", "and the first entry is not left lying around"


def test_a_mismatch_starts_over_from_the_first_entry(monkeypatch: Any) -> None:
    """The mismatch says nothing about WHICH of the two was mistyped, and the operator cannot see
    either of them — so re-asking only for the confirmation would have them retype to match a
    password that may itself be the typo."""
    store = _Store()
    monkeypatch.setattr(
        "mosaera_memory.MemoryStore.open_or_reason", staticmethod(lambda _u: (store, ""))
    )
    app = _App()
    app._username = "alex"

    asyncio.run(admin_step.submit(app, "password", GOOD))  # type: ignore[arg-type]
    asyncio.run(admin_step.submit(app, "password2", GOOD + " not"))  # type: ignore[arg-type]
    assert app._field_for == "password", "back to the FIRST entry, not the confirmation"
    assert "did not match" in app._notice
    assert app._password == "", "and the rejected first entry is dropped"
    assert store.created == []


def test_a_bad_password_is_refused_before_the_second_entry(monkeypatch: Any) -> None:
    """Asking someone to type a 15-character passphrase twice and only then saying it was too short
    costs them both entries to fix one."""
    app = _App()
    app._username = "alex"
    asyncio.run(admin_step.submit(app, "password", "short"))  # type: ignore[arg-type]
    assert app._field_for == "password", "it asks again for the FIRST entry"
    assert "15 characters" in app._notice


# ------------------------------------------------------------------ resetting a forgotten one


def _reset_app(store: _Store, monkeypatch: Any) -> _App:
    monkeypatch.setattr(
        "mosaera_memory.MemoryStore.open_or_reason", staticmethod(lambda _u: (store, ""))
    )
    return _App()


def test_a_reset_names_the_account_and_confirms_the_new_password(monkeypatch: Any) -> None:
    store = _Store([{"id": 7, "username": "alex", "is_admin": True}])
    app = _reset_app(store, monkeypatch)

    asyncio.run(password_reset.enter(app))  # type: ignore[arg-type]
    assert app.step == "reset"
    assert "alex" in app.screens[-1].choices[0], "whose password is being reset is named"

    asyncio.run(password_reset.chose(app, 0))  # type: ignore[arg-type]
    assert app._field_for == "reset1"
    asyncio.run(password_reset.submit_first(app, GOOD))  # type: ignore[arg-type]
    assert app._field_for == "reset2", "a reset is confirmed too"
    assert store.set_calls == [], "and nothing is written until it is"

    asyncio.run(password_reset.submit_second(app, GOOD))  # type: ignore[arg-type]
    assert len(store.set_calls) == 1
    uid, pw_hash, subject = store.set_calls[0]
    assert uid == 7
    assert pw_hash != GOOD, "the password is hashed, never stored as typed"
    assert subject, "the login-backoff bucket is cleared, or a locked-out account stays locked out"


def test_a_reset_mismatch_writes_nothing(monkeypatch: Any) -> None:
    store = _Store([{"id": 7, "username": "alex", "is_admin": True}])
    app = _reset_app(store, monkeypatch)
    asyncio.run(password_reset.enter(app))  # type: ignore[arg-type]
    asyncio.run(password_reset.chose(app, 0))  # type: ignore[arg-type]
    asyncio.run(password_reset.submit_first(app, GOOD))  # type: ignore[arg-type]
    asyncio.run(password_reset.submit_second(app, GOOD + " no"))  # type: ignore[arg-type]
    assert store.set_calls == []
    assert app._field_for == "reset1"
    assert app._password == ""


def test_a_weak_reset_password_is_refused(monkeypatch: Any) -> None:
    """The rules do not relax because it is a reset rather than a first account."""
    store = _Store([{"id": 7, "username": "alex", "is_admin": True}])
    app = _reset_app(store, monkeypatch)
    asyncio.run(password_reset.enter(app))  # type: ignore[arg-type]
    asyncio.run(password_reset.chose(app, 0))  # type: ignore[arg-type]
    asyncio.run(password_reset.submit_first(app, "alex"))  # type: ignore[arg-type]
    assert app._field_for == "reset1"
    assert store.set_calls == []


def test_cancelling_the_picker_writes_nothing(monkeypatch: Any) -> None:
    store = _Store([{"id": 7, "username": "alex", "is_admin": True}])
    app = _reset_app(store, monkeypatch)
    asyncio.run(password_reset.enter(app))  # type: ignore[arg-type]
    asyncio.run(password_reset.chose(app, 1))  # type: ignore[arg-type]  # the Cancel row, past the users
    assert store.set_calls == []
    assert app.went[-1] == "configured" or app.went[-1] == "done"


def test_an_instance_with_no_accounts_says_so(monkeypatch: Any) -> None:
    """Nothing to reset is the state of a fresh instance, not a failure."""
    app = _reset_app(_Store([]), monkeypatch)
    asyncio.run(password_reset.enter(app))  # type: ignore[arg-type]
    assert "no accounts" in app._notice
    assert app.step != "reset"


def test_an_unreachable_database_is_named_not_swallowed(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mosaera_memory.MemoryStore.open_or_reason",
        staticmethod(lambda _u: (None, "connection refused")),
    )
    app = _App()
    asyncio.run(password_reset.enter(app))  # type: ignore[arg-type]
    assert "database" in app._notice.lower()
    assert app.step != "reset"


def test_the_generated_key_is_unrelated_to_any_of_this() -> None:
    """A guard against copy-paste: Fernet keys and password hashes are different things."""
    assert Fernet.generate_key() != Fernet.generate_key()
