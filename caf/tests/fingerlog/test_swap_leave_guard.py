"""S5 / S6 — no shift assignment over approved leave.  MG's rule, 2026-08-13.

    bench --site <site> execute caf.tests.fingerlog.test_swap_leave_guard.run

WHY THIS RULE EXISTS, AND WHY IT IS CHEAPER THAN THE ALTERNATIVE
----------------------------------------------------------------
A Leave Application's day count is computed once, at approval, and **stored** —
on the document and again in a Leave Ledger Entry. Nothing recomputes it. So an
assignment filed (or cancelled) over approved leave leaves a wrong number
standing, silently.

Simulated on the bench before a line was written, because the scenario space
needed pruning rather than guessing. Four orderings can leave a wrong count:

    (1) swap -> leave            wrong AT FILING, in BOTH directions: one
                                 employee gets a free day, the other is
                                 overcharged one.  NOT this guard's job — it is
                                 E7, fixed at filing time in Chunk 6
    (2) leave -> swap            goes stale. Measured: the swap was accepted and
                                 the leave still read 4.0
    (3) leave -> swap -> cancel  stale, then back
    (4) swap -> leave -> cancel  wrong at filing, then right again by accident

This guard closes (2), (3) and (4) at the only two moments they can begin.
🟢 And one measurement was better news than expected: the ledger matched
`total_leave_days` in all six runs, so the books are internally coherent — a
wrong number consistently applied, not a balance drifting out of true.

FIXTURES
--------
June 2026 (§F4d), **2026-06-08 .. 06-12** — Mon–Fri, deliberately clear of
`2026-06-17` (AWAL MUHARRAM), which cost Chunk R six assertions at once (§F1c),
and clear of every June Saturday the other suites own (06, 13, 20, 27).
"""

import frappe

from caf.caf import shift_swap

ALT_A = "HR-EMP-00009"       # Seow Zi Ying — 8:30am Alt Sat 1st-3rd
ALT_B = "HR-EMP-00010"       # Hazwani      — 8:30am Alt Sat 2nd-4th (her mirror)

L_FROM, L_TO = "2026-06-08", "2026-06-12"     # Mon–Fri
D_MID = "2026-06-10"                          # Wednesday, inside the leave
D_CLEAR = "2026-06-11"                        # also inside — used after cleanup
LTYPE = "Leave Without Pay"                   # is_lwp: no balance needed

RESULTS = []
_made = {"la": [], "sa": []}


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def throws(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return ""
    except Exception as e:
        return str(e)


def make_leave(employee, status="Approved", submit=True):
    doc = frappe.new_doc("Leave Application")
    doc.employee = employee
    doc.leave_type = LTYPE
    doc.from_date, doc.to_date = L_FROM, L_TO
    doc.status = status
    doc.flags.ignore_permissions = True
    doc.insert()
    if submit:
        doc.submit()
    _made["la"].append(doc.name)
    return doc


def cleanup():
    """Scoped by employee AND by this suite's five June days (§F4)."""
    for r in frappe.get_all("Leave Application",
                            filters={"employee": ("in", [ALT_A, ALT_B]),
                                     "from_date": L_FROM, "to_date": L_TO},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Leave Application", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Leave Application", r.name, ignore_permissions=True,
                          force=True)
    _made["la"].clear()

    scope = {"employee": ("in", [ALT_A, ALT_B]),
             "start_date": ("in", [D_MID, D_CLEAR])}
    for r in frappe.get_all("Shift Assignment", filters=scope, fields=["name"]):
        frappe.db.set_value("Shift Assignment", r.name, "caf_swap_partner", None,
                            update_modified=False)
    frappe.db.commit()
    for r in frappe.get_all("Shift Assignment", filters=scope, fields=["name"]):
        doc = frappe.get_doc("Shift Assignment", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            # ⚠️ The guard itself would refuse this cancel while the fixture
            # leave is still live — so leave is purged FIRST, above.
            doc.cancel()
        frappe.delete_doc("Shift Assignment", r.name, ignore_permissions=True,
                          force=True)
    _made["sa"].clear()
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    cleanup()

    base = frappe.db.count("Shift Assignment", {"docstatus": 1})
    leave_base = frappe.db.count("Leave Application")

    try:
        # ------------------------------------------------------------- S5-CLEAR
        # 🔴 THE POSITIVE CONTROL, and it goes first. Without it every refusal
        # below could be passing because the swap is broken for everybody —
        # exactly the W3 trap (§F1).
        res = shift_swap.create(D_CLEAR, ALT_A, ALT_B)
        _made["sa"].extend(res["created"])
        check("S5-CLEAR", res["kind"] == "Swap" and len(res["created"]) == 2,
              f"with NO leave in the way the same trade succeeds: "
              f"{res['kind']}, {len(res['created'])} rows. Every refusal below "
              f"is measured against this")
        cleanup()

        # ------------------------------------------------------------- S5-BLOCK
        make_leave(ALT_A)
        err = throws(shift_swap.create, D_MID, ALT_A, ALT_B)
        after = frappe.db.count("Shift Assignment", {"docstatus": 1})
        check("S5-BLOCK", "approved leave" in err and after == base,
              f"a trade over {ALT_A}'s approved leave is REFUSED, and nothing "
              f"survives: assignments {base} ➜ {after}. "
              f"{err[:100] or '🔴 it was allowed'}")

        # ----------------------------------------------------------- S5-PARTNER
        # The guard must read BOTH employees. It does so structurally — each
        # half is its own document and `before_submit` fires on each — but a
        # future refactor could file B's row without one, so assert it.
        cleanup()
        make_leave(ALT_B)
        err2 = throws(shift_swap.create, D_MID, ALT_A, ALT_B)
        after2 = frappe.db.count("Shift Assignment", {"docstatus": 1})
        check("S5-PARTNER", "approved leave" in err2 and after2 == base,
              f"and when it is the PARTNER who is on leave it is refused too, "
              f"with the first row rolled back: {base} ➜ {after2}. "
              f"{err2[:90] or '🔴 it was allowed'}")

        # ------------------------------------------------------------ S5-SINGLE
        # 🔴 WIDER THAN MG'S WORDING, deliberately. MG said "any swap"; a
        # standalone assignment can move somebody onto a no-Saturday shift and
        # change the day type just as a swap can, so the guard covers it. A rule
        # that fired for one shape and not the other is a rule nobody predicts.
        cleanup()
        make_leave(ALT_A)
        alt_shift = frappe.db.get_value("Employee", ALT_B, "default_shift")
        err3 = throws(shift_swap.create, D_MID, ALT_A, None, alt_shift)
        check("S5-SINGLE", "approved leave" in err3,
              f"a STANDALONE assignment is refused on the same grounds — the "
              f"mechanism is identical: {err3[:95] or '🔴 it was allowed'}")

        # ------------------------------------------------------------- S5-DRAFT
        # Measured on the bench: a draft leave does NOT block, and should not —
        # it is a request, not a fact.
        cleanup()
        make_leave(ALT_A, status="Open", submit=False)
        res2 = shift_swap.create(D_MID, ALT_A, ALT_B)
        _made["sa"].extend(res2["created"])
        check("S5-DRAFT", len(res2["created"]) == 2,
              f"a DRAFT leave does not block: {len(res2['created'])} rows filed. "
              f"The guard keys on APPROVED, which is what MG's wording said")

        # ---------------------------------------------------------- S5-REJECTED
        # 🔴 `docstatus = 1` ALONE would catch a rejected leave and block on it.
        # That is the REJ1 trap Chunk 5b already paid for once: a rejection
        # touches no Attendance and reserves no day, so it must not block.
        cleanup()
        make_leave(ALT_A, status="Rejected")
        res3 = shift_swap.create(D_MID, ALT_A, ALT_B)
        _made["sa"].extend(res3["created"])
        check("S5-REJECTED", len(res3["created"]) == 2,
              f"a submitted-but-REJECTED leave does not block either: "
              f"{len(res3['created'])} rows. `docstatus = 1` alone would have "
              f"blocked it — the guard checks status too")

        # ------------------------------------------------------------ S6-CANCEL
        # Ordering (4): the assignment came FIRST, the leave was approved after,
        # and now somebody tries to unwind the assignment. Cancelling would move
        # the day type back under a leave whose count is already fixed.
        cleanup()
        res4 = shift_swap.create(D_MID, ALT_A, ALT_B)
        _made["sa"].extend(res4["created"])
        make_leave(ALT_A)
        err4 = throws(shift_swap.cancel_both, res4["created"][0])
        still = frappe.db.get_value("Shift Assignment", res4["created"][0],
                                    "docstatus")
        check("S6-CANCEL", "approved leave" in err4 and still == 1,
              f"and the CANCEL is refused once leave has been approved over it — "
              f"the row is still submitted (docstatus {still}). "
              f"{err4[:90] or '🔴 it cancelled'}")

        # ----------------------------------------------------------- S6-INTACT 🔴
        # The refusal must fire BEFORE anything mutates. `before_cancel` also
        # clears `caf_swap_partner`, and a refusal that ran after it would leave
        # a submitted row with its pairing broken — the half-configured state
        # `half_done_swaps()` exists to find. The guard would have manufactured
        # its own alarm.
        partner = frappe.db.get_value("Shift Assignment", res4["created"][0],
                                      "caf_swap_partner")
        half = shift_swap.half_done_swaps()["count"]
        check("S6-INTACT", partner == res4["created"][1] and half == 0,
              f"and the refused cancel left the pairing INTACT: partner still "
              f"{partner or 'CLEARED 🔴'}, half-done swaps {half}. Ordering the "
              f"guard after unlink_pair would have broken the pair it refused "
              f"to cancel")

    finally:
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    left_sa = frappe.db.count("Shift Assignment", {"docstatus": 1})
    left_la = frappe.db.count("Leave Application")
    check("S5-CLEAN", left_sa == base and left_la == leave_base,
          f"assignments {base} ➜ {left_sa}, leave applications "
          f"{leave_base} ➜ {left_la}")

    print("\n=== S5 / S6 — no assignment over approved leave (MG, 2026-08-13) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:14s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
