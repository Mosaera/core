# scripts

Developer utility scripts. Anything here must be safe to run from a clean checkout
and must not require secrets.

- `fresh-machine-check.sh` — drive a clean box to "can run a task" with no browser (#119).
  Report-only; delegates everything past the host tools to `mosaera doctor`, which derives the
  required models from the active bindings rather than a list written here.
