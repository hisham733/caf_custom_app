"""Throwaway probes. Everything in here except this file is gitignored.

WHY THIS PACKAGE EXISTS — MG, 2026-09-12, asking for the third time
-------------------------------------------------------------------
`.claude/settings.local.json` had grown to **1,093 allow rules, 1,028 of them
exact one-off command strings**, because every probe was written to the Windows
scratchpad, copied in with `cp`, and run with a slightly different command —
a brand-new approval every time.

Now a probe is:

    1 · Write  apps/caf/caf/scratch/<name>.py          (one allowed path)
    2 · bench --site <site> execute caf.scratch.<name>.run

One path, one command shape, no approval churn.

RULES FOR ANYTHING PUT HERE
---------------------------
- ⚠️ **Disposable.** Nothing here is the record. A finding graduates to
  `GO_LIVE_TODO.md` / `CAF_DESIGN_FRAMEWORK.md`, a reusable tool graduates to
  `caf/scripts/`, an assertion graduates to `caf/tests/`.
- **Read-only by default.** If a probe writes, it says so in its docstring and
  rolls back or cleans up — same contract as `caf/scripts/`.
- 🔴 **Wrap `run()` in try/except and print `traceback.format_exc()` to STDOUT.**
  `bench execute` masks every exception as `NameError: name 'caf' is not
  defined` (quirks §18), and `print_exc()` goes to stderr, which does not come
  back through `docker exec`.
- ⚠️ **`bench execute` prints whatever you return** — return a small summary,
  never the payload.
- **Delete it when the question is answered.** A scratch file nobody deletes
  becomes a script nobody owns.
"""
