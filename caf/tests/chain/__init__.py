"""CHAIN tests — the joins BETWEEN doctypes, not the rules inside one.

    caf/tests/chain/
        login.py      a password-free desk login, for the browser playbooks
        dataset.py    the base data every climb walks (report/seed/reset/verify)

🔴 WHY THIS PACKAGE EXISTS — T-45, the guard ladder
---------------------------------------------------
Every CAF guard is tested where it lives. **The ORDER they fire in is tested
nowhere** — and HR only ever sees the *first* refusal, so the order decides what
she is told. The OT-approval guard firing before the roster gate was found by
tripping over it in a manual pass, not by a test.

`fingerlog/test_import_to_appraisal` was the first chain test (import ➜ submit ➜
late leave ➜ appraisal). This package is where the rest live.

THE SHAPE MG CHOSE, 2026-09-12 — read it before adding anything here
--------------------------------------------------------------------
📄 `_archive/session_analysis/session_guard_ladder_2026-09-12/`
   `GUARD_LADDER_SHAPE_2026-09-12.md`      — the five climbs
   `PLAYBOOK_VS_CODE_EVALUATED_2026-09-12.md` — how they are driven

⭐ **The climbs are driven through a REAL BROWSER as a playbook**, not written as
assertions first. A playbook is the discovery *and* the HR guide page, in the
second person, verified by having been executed.

🔴 **But a playbook is NOT a regression gate** — it runs only inside a session.
So the order is: **playbook first, then codify HERE only the rungs with a
business consequence** — the guard order, T-44's link, FBR39's window, the leave
ledger. A rung that merely documents a screen stays in the playbook.

🔴 **The DATA is code; only the WALK is a browser.** Building a held day, an
unapproved-OT day and an unconfirmed month through the user interface is the
slowest possible route to them and is not re-runnable after a crash. `dataset.py`
seeds; the browser walks what it seeded.

CONVENTIONS THIS PACKAGE INHERITS (see ../CLAUDE.md — they are not optional)
----------------------------------------------------------------------------
- **Self-cleaning.** Artifacts removed FIRST as well as last, so a run after a
  crash still works.
- **June, not July.** July holds imported Finger Logs. ⚠️ Avoid **2026-06-17**
  (Awal Muharram) — stock refuses a leave whose every day is a holiday, and that
  refusal arrives long before any CAF logic.
- 🔴 **Never touch 2026-08-10..16 or 2026-09-07..10** — the 616 and 352 draft
  windows. 10–16 August is still T-44's only evidence.
- 🔴 **Employees are matched on `attendance_device_id`, never `HR-EMP-xxxxx`**
  (T-32 — the same id is a different person on production).
- **Assert the FACTS a message carries, never its wording** (`test_ot_messages`
  is the shape), so the wording can be improved and cannot be impoverished.
"""
