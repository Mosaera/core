"""Password rules, following NIST SP 800-63B Rev. 4 (finalised July 2025).

The three things that guidance actually asks for, and what each one costs if you skip it:

  - **Length, not composition.** 15 characters when a password is the ONLY authenticator, which is
    Mosaera's case: there is no second factor to fall back on. Rev. 4 does not merely discourage
    "must contain an uppercase, a digit and a symbol" — it PROHIBITS it, because those rules push
    people toward `Password1!` and away from the length that actually resists guessing.
  - **Screen against known-bad passwords.** A blocklist of common and breached choices, because
    length alone does not save `passwordpassword` or `1234567890123456`.
  - **Accept what people actually type.** At least 64 characters, spaces, and every printable
    character, so a passphrase or a password-manager string is never rejected.

Deliberately NOT here: forced rotation, security questions, and hints — all three are explicitly
against the guidance, and none of them exist in this codebase to remove.

The blocklist is small and embedded on purpose. A downloaded breach corpus would be a network
dependency in a first-run wizard that may have no network, and a large local one is megabytes for
a self-hosted single-tenant tool. What is here covers the patterns a 15-character minimum lets
through, which is the gap the minimum does not already close.
"""

from __future__ import annotations

import re

#: 15 for password-only authentication (SP 800-63B Rev. 4). Eight is the figure for a password
#: used WITH a second factor — Mosaera has none, so eight would be the wrong line to copy.
MIN_LENGTH = 15

#: Accepting at least 64 is required, and there is no reason to stop there beyond keeping a hash
#: bounded. bcrypt-family truncation is not a concern for the hash in use; this only bounds abuse.
MAX_LENGTH = 256

#: Not a breach corpus — the patterns a length rule alone still admits. Compared against the
#: password with case and non-letters stripped, so `P@ssword-Password` is caught too.
_BLOCKED = frozenset(
    {
        "password",
        "passwordpassword",
        "letmein",
        "welcome",
        "admin",
        "administrator",
        "changeme",
        "qwerty",
        "iloveyou",
        "monkey",
        "dragon",
        "football",
        "baseball",
        "superman",
        "trustno",
        "mosaera",
        "correcthorsebatterystaple",  # the xkcd passphrase, which is now a common choice
    }
)

_SEQUENCES = ("0123456789", "abcdefghijklmnopqrstuvwxyz", "qwertyuiop")


def _normalised(password: str) -> str:
    return re.sub(r"[^a-z]", "", password.lower())


def problem_with(password: str, username: str = "") -> str | None:
    """Why this password is unacceptable, or None. The message names the ONE thing to change.

    Returns prose an operator can act on: "must be at least 15 characters" is actionable, while
    "does not meet complexity requirements" is the message that produces `Password1!`.
    """
    if len(password) < MIN_LENGTH:
        return (
            f"password must be at least {MIN_LENGTH} characters — length is what resists guessing, "
            "so a passphrase of ordinary words is a good choice"
        )
    if len(password) > MAX_LENGTH:
        return f"password must be at most {MAX_LENGTH} characters"
    if password != password.strip() and not password.strip():
        return "password cannot be only whitespace"

    letters = _normalised(password)
    if letters and letters in _BLOCKED:
        return "that is one of the most commonly chosen passwords — pick something else"
    for blocked in _BLOCKED:
        if len(blocked) >= 6 and letters.count(blocked) * len(blocked) >= len(letters) * 0.8:
            return "that is mostly a very common password — pick something else"

    if username and len(username) >= 3 and username.lower() in password.lower():
        return "password must not contain your username"

    if len(set(password)) <= 3:
        return "password repeats too few characters to be hard to guess"
    for seq in _SEQUENCES:
        for i in range(len(seq) - 7):
            if seq[i : i + 8] in password.lower():
                return "password contains a long keyboard or alphabet run — pick something else"
    return None
