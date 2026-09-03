"""Parser: tokens -> an AST (with variables and a statement sequence).

Grammar:
    program := statement (';' statement)*
    statement := IDENT '=' expr | expr
    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/') factor)*
    factor := NUMBER | IDENT | '(' expr ')'

``parse`` (a single expression) is kept for backward compatibility with the seed's
tests; ``parse_program`` is the new statement-sequence entry point.
"""

from __future__ import annotations

from dataclasses import dataclass

from calc.tokens import Token


class ParseError(ValueError):
    """Raised on input that does not form a valid program."""


@dataclass(frozen=True)
class Num:
    value: int


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class BinOp:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Assign:
    name: str
    expr: object


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self, ahead: int = 0) -> Token | None:
        idx = self.pos + ahead
        return self.tokens[idx] if idx < len(self.tokens) else None

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self) -> object:
        node = self._expr()
        if self._peek() is not None:
            raise ParseError("unexpected trailing input")
        return node

    def parse_program(self) -> list[object]:
        statements: list[object] = [self._statement()]
        while self._peek() is not None:
            if self._peek().kind != "SEMI":  # type: ignore[union-attr]
                raise ParseError("expected ';' between statements")
            self._advance()
            if self._peek() is None:  # trailing ';'
                break
            statements.append(self._statement())
        return statements

    def _statement(self) -> object:
        tok, nxt = self._peek(), self._peek(1)
        if tok and tok.kind == "IDENT" and nxt and nxt.kind == "EQUALS":
            name = self._advance().value
            self._advance()  # '='
            return Assign(name, self._expr())
        return self._expr()

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
        if tok.kind == "IDENT":
            self._advance()
            return Var(tok.value)
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


def parse_program(tokens: list[Token]) -> list[object]:
    if not tokens:
        raise ParseError("empty program")
    return _Parser(tokens).parse_program()
