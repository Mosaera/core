# Task

Add a `remove_item(name, qty)` method to `store/inventory.py`.

- Removing a valid amount reduces that item's quantity.
- Removing **more** units than are in stock must **never** leave a negative
  quantity — raise `ValueError` in that case.

Keep the existing `add_item` / `quantity` / `total_count` behaviour unchanged.
