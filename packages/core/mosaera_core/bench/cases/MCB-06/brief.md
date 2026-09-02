# Harden the config loader (Python)

You are working in an existing Python project with a `config_loader` module whose
`load_config(path)` reads a JSON config file and returns a dict with `name` and
`port`. It works on valid input but **crashes with raw tracebacks** on bad input —
a missing file, malformed JSON, a missing required key, or a wrong-typed value.

## Task

Make `load_config` robust. Define a `ConfigError` exception in the module and raise
it — with a clear, human-readable message — for every failure mode instead of
leaking a raw `FileNotFoundError` / `JSONDecodeError` / `KeyError` / `TypeError`:

- the file does not exist,
- the file is not valid JSON,
- a required key (`name`, `port`) is missing,
- a value has the wrong type (`name` must be a string, `port` an integer).

A valid config must still load and return `{"name": ..., "port": ...}` unchanged.

## Constraints

- Keep the `load_config(path)` signature.
- `ConfigError` must be importable as `from config_loader import ConfigError`.
- Standard library only.
