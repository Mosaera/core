"""In-scope suite (lives under tests/) — the existing behaviour, green on the seed."""

from store.inventory import Inventory


def test_add_accumulates() -> None:
    inv = Inventory()
    inv.add_item("apple", 3)
    inv.add_item("apple", 2)
    assert inv.quantity("apple") == 5


def test_total_counts_all_items() -> None:
    inv = Inventory()
    inv.add_item("apple", 3)
    inv.add_item("banana", 4)
    assert inv.total_count() == 7
