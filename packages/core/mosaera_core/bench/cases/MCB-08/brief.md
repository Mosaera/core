# Fix the Roman-numeral converter (Python)

You are working in an existing Python project (a small `roman` module that converts
an integer to its Roman-numeral string). It is wrong for any number that needs
**subtractive notation**: it emits `4` as `"IIII"` instead of `"IV"`, `9` as
`"VIIII"` instead of `"IX"`, `40` as `"XXXX"` instead of `"XL"`, and so on.

## Task

Diagnose and fix the bug in `roman.py` so that `to_roman(n)` produces the correct,
canonical Roman numeral for every integer `1 <= n <= 3999`, including the subtractive
forms.

Reference values: `4 -> "IV"`, `9 -> "IX"`, `40 -> "XL"`, `90 -> "XC"`,
`400 -> "CD"`, `900 -> "CM"`, `2024 -> "MMXXIV"`, `3999 -> "MMMCMXCIX"`.

## Constraints

- Fix the **implementation**, not the tests. Do not delete, skip, or weaken any test
  to make the suite pass — the bug is real and lives in the module code.
- Keep the public API (`to_roman`) and its signature unchanged.
- Do not introduce third-party dependencies; the standard library is enough.
- Leave the rest of the module behaviour intact.
