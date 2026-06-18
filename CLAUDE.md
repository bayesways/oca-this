# oca-agent

Claims pipeline for the OCA WealthCare reimbursement portal. Skills under `.claude/skills/` (`new-claim`, `parse-claim`, `classify-claim`, `submit-claim`, `uhc-bulk-import`) call into the storage CLI in `src/storage/cli.py` and the OCA portal via the claude-in-chrome MCP.

## Working directory

All `uv run python -m src.<...>` invocations must be anchored to the project root discovered with `git rev-parse --show-toplevel`. The storage CLI resolves the data directory relative to its own file, but `uv run` itself fails to find the `src` package if the cwd is elsewhere.

A long-running background process (e.g. the receipt upload HTTP server in `/submit-claim`) often changes the cwd via `cd <receipts_dir> && python3 -m http.server ... &`. After that, every subsequent bare `uv run python -m src.storage.cli ...` will fail with `ModuleNotFoundError: No module named 'src'`.

**Always anchor CLI calls with `uv --directory` in skill steps and in conversation:**

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli <subcommand> ...
```
