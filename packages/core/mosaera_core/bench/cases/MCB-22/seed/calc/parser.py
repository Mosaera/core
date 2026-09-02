"""Recursive-descent parser: tokens -> an expression AST.

Grammar (precedence low to high):
    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/') factor)*
    factor := NUMBER | '(' expr ')'
"""

from __future__ import annotations

from dataclasses import dataclass

from calc.tokens import Token


class ParseError(ValueError):
    """Raised on input that does not form a valid expression."""


@dataclass(frozen=True)
class Num:
    value: int


@dataclass(frozen=True)
class BinOp:
    op: str
    left: object
    right: object


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self) -> object:
        node = self._expr()
        if self._peek() is not None:
            raise ParseError("unexpected trailing input")
        return node

    def _expr(self) -> object:
        node = self._term()
        while (tok := self._peek()) and tok.kind in ("PLUS", "MINUS"):
            op = self._advance().value
            node = BinOp(op, node, self._term())
        return node

    def _term(self) -> object:
        node = self._factor()
        while (tok := self._peek()) and tok.kind in ("STAR", "SLASH"):
            op = self._advance().value
            node = BinOp(op, node, self._factor())
        return node

    def _factor(self) -> object:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input")
        if tok.kind == "NUMBER":
            self._advance()
            return Num(int(tok.value))
        if tok.kind == "LPAREN":
            self._advance()
            node = self._expr()
            if not self._peek() or self._peek().kind != "RPAREN":  # type: ignore[union-attr]
                raise ParseError("expected ')'")
            self._advance()
            return node
        raise ParseError(f"unexpected token {tok.value!r}")


def parse(tokens: list[Token]) -> object:
    return _Parser(tokens).parse()
