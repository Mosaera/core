# bizdays

A tiny helper that counts business days (Mon–Fri) between two dates, inclusive.

```python
from datetime import date
from bizdays import business_days

business_days(date(2024, 1, 1), date(2024, 1, 5))  # -> 5  (Mon..Fri)
```

Run the tests with `python -m pytest`.
