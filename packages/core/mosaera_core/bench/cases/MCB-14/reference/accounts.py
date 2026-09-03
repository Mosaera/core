"""Create and update user records with input validation."""

from __future__ import annotations

from typing import Any


def _validate(name: str, age: int) -> None:
    """Shared validation for a user record; raise ``ValueError`` if invalid."""
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    if not isinstance(age, int) or isinstance(age, bool) or age < 0 or age > 150:
        raise ValueError("age must be an int in 0..150")


def create_user(name: str, age: int) -> dict[str, Any]:
    """Validate the inputs and return a new-user record."""
    _validate(name, age)
    return {"action": "create", "name": name, "age": age}


def update_user(name: str, age: int) -> dict[str, Any]:
    """Validate the inputs and return an updated-user record."""
    _validate(name, age)
    return {"action": "update", "name": name, "age": age}
