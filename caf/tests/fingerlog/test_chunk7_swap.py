"""Chunk 7.3 — the swap/cover tool. OD-65 · ALT4.

    bench --site <site> execute caf.tests.fingerlog.test_chunk7_swap.run

🔴 THE ASSERTION THAT MATTERS IS SWAP-BOTH
------------------------------------------
The whole tool exists because a trade filed by hand can be **half-done** — one row
filed, the other forgotten, and Mr A works the Saturday while Mr B is still
rostered for it, silently. So the test that earns its place is the one proving
both rows exist, are submitted, and point at each other; and SWAP-ATOMIC, proving
that when the second fails the first does not survive.

SWAP AND COVER ARE DIFFERENT OPERATIONS and the tool must not conflate them: a
cover is one-way, and calling it a swap would let HR believe a debt was settled.

Fixtures are **June 2026 Saturdays**, the month the importer never touched (§F4d),
and the employees are the real alternate-Saturday eight, so the validation is
exercised against the live configuration rather than a mock.
"""

import frappe

from caf.caf import shift_swap

# Group A rests 1st+3rd, group B rests 2nd+4th — HR's split, confirmed 2026-08-12.
A1 = "HR-EMP-00003"        # Too Poh Chin      — 8:30am Alt Sat 1st-3rd
A2 = "HR-EMP-00005"        # Nur Najwa         — 8:30am Alt Sat 1st-3rd
B1 = "HR-EMP-00004"        # Afiza             — 8:30am Alt Sat 2nd-4th
PROD = "HR-EMP-00042"      # Nur Ezzatul       — 8-5 Alt Sat 2nd-4th (other family)
PLAIN = "HR-EMP-00016"     # 8am Schedule      — not an alternating shift at all

D_SAT = "2026-06-13"       # a June Saturday, clear of AWAL MUHARRAM (§F1c)
D_SAT2 = "2026-06-20"

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def cleanup():
    """Scoped to this suite's employees AND its two June dates (§F4).

    ⚠️ The partner links must be cleared FIRST. They are real Link fields, so a
    paired row cannot be deleted while its twin points at it — `LinkExistsError`,
    and `force=True` does not bypass it. That is the cross-link working as
    intended; it just means teardown has to undo the pairing before the rows.
    """
    scope = {"employee": ("in", [A1, A2, B1, PROD, PLAIN]),
             "start_date": ("in", [D_SAT, D_SAT2])}
    for r in frappe.get_all("Shift Assignment", filters=scope, fields=["name"]):
        frappe.db.set_value("Shift Assignment", r.name, "caf_swap_partner", None,
                            update_modified=False)
    frappe.db.commit()

    for r in frappe.get_all("Shift Assignment", filters=scope,
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Shift Assignment", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Shift Assignment", r.name, ignore_permissions=True,
                          force=True)
    frappe.db.commit()


def throws(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return ""
    except Exception as e:
        return str(e)


def run():
    cleanup()
    try:
        # ------------------------------------------------------------ ALT4-PLAN
        p = shift_swap.plan(D_SAT, A1, B1)
        check("ALT4-PLAN", p["kind"] == "Swap"
              and p["a"]["shift_new"] == p["b"]["shift_now"]
              and p["b"]["shift_new"] == p["a"]["shift_now"]
              and p["a"]["day_now"] != p["b"]["day_now"],
              f"opposite mirrors on {D_SAT} = a SWAP: {p['a']['employee_name']} is "
              f"{p['a']['day_now']} on {p['a']['shift_now']} and takes "
              f"{p['a']['shift_new']}; {p['b']['employee_name']} is "
              f"{p['b']['day_now']} and takes {p['b']['shift_new']} — they exchange")

        # ------------------------------------------------------- ALT4-COVER 🔴
        # Two people on the SAME shift. MG's correction: this is the normal case,
        # not an error — but it is a COVER, and only one of them moves.
        c = shift_swap.plan(D_SAT, A1, A2)
        check("ALT4-COVER", c["kind"] == "Cover" and c["a"]["shift_new"]
              and c["b"]["shift_new"] is None and c.get("note"),
              f"the same shift on both sides = a COVER, not a swap: "
              f"{c['a']['employee_name']} moves to {c['a']['shift_new']} and "
              f"{c['b']['employee_name']} does not move. One-way, and the payload "
              f"says so — calling it a swap would imply a debt was settled")

        # ------------------------------------------------------ ALT4-FAMILY 🔴
        err = throws(shift_swap.plan, D_SAT, A1, PROD)
        check("ALT4-FAMILY", "different shift families" in err,
              f"different families are REFUSED: 8:30am vs 8-5 — "
              f"{err[:110] or '🔴 it allowed the trade'}")

        err2 = throws(shift_swap.plan, D_SAT, A1, PLAIN)
        check("ALT4-PLAIN", err2,
              f"and a non-alternating shift cannot be traded with either: "
              f"{err2[:100] or '🔴 allowed'}")

        err3 = throws(shift_swap.plan, D_SAT, A1, A1)
        check("ALT4-SELF", "two different people" in err3,
              f"nor can somebody trade with themselves: {err3[:80]}")

        # ------------------------------------------------------- SWAP-BOTH 🔴
        res = shift_swap.create(D_SAT, A1, B1)
        rows = [frappe.db.get_value("Shift Assignment", n,
                                    ["name", "employee", "shift_type", "docstatus",
                                     "caf_swap_partner", "caf_swap_with",
                                     "caf_swap_kind", "start_date", "end_date"],
                                    as_dict=True) for n in res["created"]]
        paired = (len(rows) == 2
                  and all(r.docstatus == 1 for r in rows)
                  and rows[0].caf_swap_partner == rows[1].name
                  and rows[1].caf_swap_partner == rows[0].name
                  and rows[0].caf_swap_with == rows[1].employee
                  and rows[1].caf_swap_with == rows[0].employee)
        check("SWAP-BOTH", paired,
              f"one action filed BOTH rows, submitted, cross-linked: "
              f"{[(r.employee, r.shift_type) for r in rows]}. This is the whole "
              f"tool — a half-done swap is invisible without it")

        check("SWAP-DATES", all(r.start_date == r.end_date for r in rows),
              f"and both carry an end date (MG's guard): an open-ended assignment "
              f"would silently own every later date")

        # --------------------------------------------------- SWAP-RESOLVES 🔴
        # The point of the trade, checked where it actually shows: the day type.
        from caf.caf.shift_resolution import resolve_day_type
        da, _s = resolve_day_type(A1, D_SAT)
        db, _s = resolve_day_type(B1, D_SAT)
        check("SWAP-RESOLVES", da == p["b"]["day_now"] and db == p["a"]["day_now"],
              f"and the DAY actually changed hands: {A1} was {p['a']['day_now']} "
              f"and is now {da}; {B1} was {p['b']['day_now']} and is now {db}")

        # ------------------------------------------------------- SWAP-PARTNER
        info = shift_swap.partner_of(rows[0].name)
        check("SWAP-PARTNER", info["paired"] and info["kind"] == "Swap"
              and info["partner"] and info["partner"]["employee"] == B1,
              f"cancelling one half can be warned about: partner_of() names "
              f"{info['partner']['employee_name'] if info.get('partner') else '—'} "
              f"and their row — MG's choice was inform, then let HR pick")

        # ------------------------------------------------------ SWAP-HALFDONE
        # Cancel one side only, exactly as HR might from the ordinary form.
        one = frappe.get_doc("Shift Assignment", rows[1].name)
        one.flags.ignore_permissions = True
        one.cancel()
        frappe.db.commit()
        half = shift_swap.half_done_swaps()
        check("SWAP-HALFDONE", any(r["name"] == rows[0].name for r in half["rows"]),
              f"a half-cancelled swap is FINDABLE, not invisible: "
              f"{half['count']} half-done row(s), including {rows[0].name}. "
              f"That is what the partner link buys")

        # -------------------------------------------------------- SWAP-ATOMIC
        # A second row that cannot be filed must not leave the first behind.
        cleanup()
        before = frappe.db.count("Shift Assignment")
        blocker = frappe.new_doc("Shift Assignment")
        blocker.employee = B1
        blocker.company = frappe.db.get_value("Employee", B1, "company")
        blocker.shift_type = frappe.db.get_value("Employee", B1, "default_shift")
        blocker.start_date = blocker.end_date = D_SAT2
        blocker.status = "Active"
        blocker.flags.ignore_permissions = True
        blocker.insert()
        blocker.submit()

        err4 = throws(shift_swap.create, D_SAT2, A1, B1)
        after = frappe.db.count("Shift Assignment")
        check("SWAP-ATOMIC", err4 and after == before + 1,
              f"when the second row cannot be filed the first does not survive: "
              f"assignments {before + 1} ➜ {after} (the blocker only). "
              f"{'refused: ' + err4[:70] if err4 else '🔴 it succeeded'}")
    finally:
        cleanup()
        frappe.db.commit()

    left = frappe.db.count("Shift Assignment",
                           {"employee": ("in", [A1, A2, B1, PROD, PLAIN]),
                            "start_date": ("in", [D_SAT, D_SAT2])})
    check("SWAP-CLEAN", left == 0,
          f"the suite left {left} assignment(s) behind on its two June dates")

    print("\n=== Chunk 7.3 — swap and cover (OD-65) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:15s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
