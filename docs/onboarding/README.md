# Contributor onboarding

Getting set up to *develop* Mosaera. To just **run** it, see
[`../getting-started.md`](../getting-started.md).

## Read first

`README.md` (what/why) · [`../architecture/north-star.md`](../architecture/north-star.md) (the
constitution) · `CONTRIBUTING.md` (workflow) · `AGENTS.md` (security policy). Then skim
[`../adr/README.md`](../adr/README.md) — decisions are recorded there, and the threshold for writing
a new one is at its top.

## For AI agents

`CLAUDE.md` is the execution contract (authority order, the pre-change checklist, the completion
report). `coding-standards.md` is how code is written. Operate in the sandbox, propose only scoped
changes, never touch a CODEOWNERS-protected path without surfacing it, and pass
`make fmt-check lint typecheck test` before saying "done".

## Dev environment (WSL2 Ubuntu — the supported path)

```bash
sudo apt-get install -y make git curl ripgrep
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv → ~/.local/bin
cd /path/to/mosaera
make bootstrap
make fmt-check lint typecheck test
```

Windows-native `uv` works for quick iteration, but WSL2 is what CI and the sandbox target — verify
there before pushing. The full install/config (Docker, Ollama, Postgres, env vars, platform quirks)
lives in [`../getting-started.md`](../getting-started.md).

## Your first change

1. Pick an issue; read the relevant code, tests, ADRs, and threat model.
2. Follow the `CLAUDE.md` startup protocol (plan first for anything non-trivial).
3. Make the change; update the docs it touches — an ADR only if it meets the threshold (see
   [`../adr/README.md`](../adr/README.md)).
4. Run the four gates, then open a small, reviewable MR (Conventional Commits).

## See also

- **Decisions:** [`../adr/README.md`](../adr/README.md) · **Threat surface:** [`../threat-models/`](../threat-models/)
- **Run + operate:** [`../getting-started.md`](../getting-started.md) · [user management](../runbooks/user-management.md)
- **The whole doc map:** [`../README.md`](../README.md)
