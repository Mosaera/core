from checkout import checkout_total


def test_free_shipping_over_threshold() -> None:
    assert checkout_total([{"name": "a", "price": 30.0, "qty": 2}]) == 64.8
