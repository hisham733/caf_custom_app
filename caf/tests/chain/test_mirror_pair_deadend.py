"""OD-89 — HR cannot change a mirror pair's lunch at all. A DEAD END, recorded.

    bench --site <site> execute caf.tests.chain.test_mirror_pair_deadend.run

🔴 WHY A TEST FOR SOMETHING THAT CANNOT BE DONE
------------------------------------------------
Two alternating-Saturday shifts are a **mirror pair**: same start, same end, same
lunch — the only thing that differs is *which* Saturdays each half works. A guard
enforces that, on **every save**, and it is right to: a pair whose halves disagree
about the contracted day would pay two people differently for the same roster.

⭐ **But it leaves HR no way to change the lunch on either half.** Saving A with
the new value throws, because B still has the old one. Saving B throws, because A
still has the old one. **There is no legal intermediate state, so the pair is
frozen** — that is OD-89, and the rule is correct while the outcome is impossible.

MG, 2026-09-13: *"dont understand"* — so, concretely:

    both halves have a 60-minute lunch. HR wants 45.
      save the A half with 45  ->  REFUSED, "B still has 60"
      save the B half with 45  ->  REFUSED, "A still has 60"
      …and there is no third move.

**This suite asserts the dead end rather than routing around it.** A rule that is
correct and produces an impossible outcome should be visible where somebody will
trip over it — not only in a register entry nobody greps. ⭐ **When OD-89 is
solved** — most likely by propagating the change to the mirror inside the same
transaction — **this suite goes red, and that red is the signal to retire it.**

⚠️ It writes to a real `Shift Type` and puts the value back, asserting the restore.
Both attempts are expected to throw, so in practice nothing is written at all.
"""

import traceback

import frappe
from frappe.utils import strip_html

RESULTS = []

FIELD = "caf_lunch_minutes"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<26}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _pair():
    """A mirror pair that actually points both ways."""
    for r in frappe.get_all("Shift Type",
                            filters={"caf_alt_sat": 1,
                                     "caf_sat_mirror": ("is", "set")},
                            fields=["name", "caf_sat_mirror"], order_by="name"):
        back = frappe.db.get_value("Shift Type", r.caf_sat_mirror,
                                   "caf_sat_mirror")
        if back == r.name:
            return r.name, r.caf_sat_mirror
    return None, None


def _try_set(shift, value):
    doc = frappe.get_doc("Shift Type", shift)
    doc.set(FIELD, value)
    doc.flags.ignore_permissions = True
    try:
        doc.save(ignore_permissions=True)
        return ""
    except Exception as e:
        frappe.db.rollback()
        return strip_html(str(e)).strip()


def run():
    frappe.set_user("Administrator")
    a, b = _pair()
    if not a:
        print("SKIPPED — no mutually-pointing mirror pair on this site, so the "
              "dead end cannot be reached. A skip, not a pass.")
        return True

    was_a = frappe.db.get_value("Shift Type", a, FIELD)
    was_b = frappe.db.get_value("Shift Type", b, FIELD)
    target = (was_a or 60) - 15

    try:
        check("MPD0-PAIR-MATCHES", was_a == was_b,
              f"the pair starts matched — {a} and {b} both have {FIELD}={was_a}. "
              f"That is the state the guard exists to protect, and it is also the "
              f"only state either half can be in")

        msg_a = _try_set(a, target)
        check("MPD1-FIRST-HALF-REFUSED", bool(msg_a) and b in msg_a,
              f"changing {a} to {target} is REFUSED, naming the other half — "
              f"{msg_a[:140]!r}")

        msg_b = _try_set(b, target)
        check("MPD2-SECOND-HALF-REFUSED", bool(msg_b) and a in msg_b,
              f"…and changing {b} instead is refused for the mirror-image reason — "
              f"{msg_b[:140]!r}")

        check("MPD3-DEAD-END", bool(msg_a) and bool(msg_b),
              f"🔴 **OD-89, ASSERTED AS A DEAD END.** Both directions throw, so "
              f"there is no order of operations that gets HR from a 60-minute "
              f"lunch to a {target}-minute one on this pair. The RULE is right — "
              f"halves that disagree would pay two people differently for the same "
              f"roster — and the OUTCOME is impossible. ⭐ **When this is solved "
              f"(propagate to the mirror in the same transaction) this assertion "
              f"goes RED, and that red is the signal to retire it**")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        now_a = frappe.db.get_value("Shift Type", a, FIELD)
        now_b = frappe.db.get_value("Shift Type", b, FIELD)
        check("MPD-RESTORE", now_a == was_a and now_b == was_b,
              f"both halves are untouched — {a}={now_a} (was {was_a}), "
              f"{b}={now_b} (was {was_b}). ⚠️ Every attempt was expected to throw, "
              f"so nothing should have been written; this asserts it rather than "
              f"assuming it")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
