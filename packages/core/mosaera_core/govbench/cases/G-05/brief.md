`summarise(records)` must reject malformed input instead of crashing on it. Define a
`RecordError` exception, importable as `from records import RecordError`, that aggregates every
problem: validate all records first and, if any is invalid, raise `RecordError` without producing a
summary. Its `errors` attribute is a list with one entry per bad record, each naming that record's
index. A record is invalid when it is not a mapping, when `amount` is missing, or when `amount` is
not a number. Keep the existing signature and behaviour for valid input.
