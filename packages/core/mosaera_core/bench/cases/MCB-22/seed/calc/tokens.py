"""Tokenizer: source text -> a flat list of tokens."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Token:
    kind: str  # NUMBER | PLUS | MINUS | STAR | SLASH | LPAREN | RPAREN
    value: str


class TokenizeError(ValueError):
    """Raised on a character the tokenizer does not recognise."""


_SINGLE = {"+": "PLUS", "-": "MINUS", "*": "STAR", "/": "SLASH", "(": "LPAREN", ")": "RPAREN"}


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit():
            j = i
            while j < n and source[j].isdigit():
                j += 1
            tokens.append(Token("NUMBER", source[i:j]))
            i = j
            continue
        if c in _SINGLE:
            tokens.append(Token(_SINGLE[c], c))
            i += 1
            continue
        raise TokenizeError(f"unexpected character {c!r}")
    return tokens
