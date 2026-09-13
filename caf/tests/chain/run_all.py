"""Every chain suite, in one run.

    bench --site <site> execute caf.tests.chain.run_all.run

⚠️ These are CHAIN tests — the joins BETWEEN doctypes. They build and remove their
own data, so the order does not matter, but each one is slower than a per-doctype
suite because it walks a real sequence.

🔴 THREE OF THESE ASSERT BEHAVIOUR THAT IS WRONG, OR IMPOSSIBLE, ON PURPOSE — and
each file says so at the assertion itself:

    LLS3-T44-LINK-KEPT          T-44 — the row claims two sources
    SWP5-T46-OT-FALLS-SILENTLY  T-46 — approved overtime falls in silence
    MPD3-DEAD-END               OD-89 — a rule that admits no legal move

The first two are decisions MG has not taken; the third is a dead end nobody has
solved. They assert **what is true today** so the code and the register agree.
**When any of them is fixed the assertion goes RED, and that red is the signal to
retire it — not a regression. Do not "fix" them by editing the expectation.**
"""

import traceback

import frappe

SUITES = (
    ("guard_order", "caf.tests.chain.test_guard_order",
     "the ORDER the Finger Log guards fire in — what HR is told first"),
    ("late_leave_shapes", "caf.tests.chain.test_late_leave_shapes",
     "a late leave over a draft / Absent / Present day: three outcomes"),
    ("leave_owned_day", "caf.tests.chain.test_leave_owned_day",
     "a Finger Log cancel may not take an approved leave's day with it"),
    ("swap_reresolve", "caf.tests.chain.test_swap_reresolve",
     "a Shift Assignment filed over a past, submitted day"),
    ("joiner_bar", "caf.tests.chain.test_joiner_bar",
     "annual leave under a year — WHICH guard speaks, and what it says"),
    # ── the rungs L3/L4 owed, built 2026-09-13 ─────────────────────────────
    ("swap_reaches_appraisal", "caf.tests.chain.test_swap_reaches_appraisal",
     "a backdated swap reaching a SUBMITTED appraisal — L3 rung 3.8"),
    ("mirror_pair_deadend", "caf.tests.chain.test_mirror_pair_deadend",
     "OD-89 — a rule that is right and admits no legal move, asserted as one"),
    ("roster_holidays", "caf.tests.chain.test_roster_holidays",
     "cancelling a roster confirmation does NOT take its holidays back"),
)


def run():
    results = []
    for label, module, why in SUITES:
        print("\n" + "=" * 78)
        print(f"{label}  —  {why}")
        print("=" * 78)
        try:
            mod = frappe.get_module(module)
            ok = mod.run()
        except Exception:
            print(traceback.format_exc())
            ok = False
        finally:
            frappe.set_user("Administrator")
        results.append((label, bool(ok)))

    print("\n" + "=" * 78)
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    bad = [l for l, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} suites green"
          + (f" — FAILED: {bad}" if bad else ""))
    print("=" * 78)
    return not bad
