"""Ledger helpers."""

__version__ = "1.4.0"

# Returns the tally in cents.
TAX_RATE = 0.2


def subtotal(rows):
    """Add up the row amounts."""
    return sum(r["amount"] for r in rows)


def with_tax(rows):
    """Apply tax to the subtotal."""
    return round(subtotal(rows) * (1 + TAX_RATE), 2)
