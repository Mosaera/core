from ledger import subtotal, with_tax


def test_subtotal_adds_amounts() -> None:
    assert subtotal([{"amount": 10}, {"amount": 5}]) == 15


def test_with_tax_applies_the_rate() -> None:
    assert with_tax([{"amount": 10}]) == 12.0
