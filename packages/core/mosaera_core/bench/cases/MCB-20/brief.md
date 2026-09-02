# Add a `--json` output flag to the stats CLI (Python)

You are working in an existing, working Python CLI: a `stats_cli` package invoked
as `python -m stats_cli`. Given numbers as arguments it prints three text lines:

```
$ python -m stats_cli 1 2 3 4
mean: 2.5
max: 4
min: 1
```

Numbers are parsed as floats. With no arguments it prints a usage line to stderr
and exits non-zero.

## Task

Add a `--json` flag that may appear **anywhere** in the argument list. When
present, instead of the three text lines, print a single JSON object via
`json.dumps` with `mean`, `max`, and `min` keys — for example:

```
$ python -m stats_cli --json 1 2 3 4
{"mean": 2.5, "max": 4.0, "min": 1.0}
```

`python -m stats_cli 1 2 3 4 --json` (flag at the end) must behave identically.

## Constraints

- Follow the existing structure and conventions of the package — the argument
  parsing and stats computation are already established; your flag must fit in.
- Keep the existing text output path unchanged when `--json` is absent.
- Standard library only.
