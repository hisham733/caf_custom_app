"""Stock Leave Types that contradict CAF's rules — reported, then neutralised.

    bench --site <site> execute caf.scripts.leave_type_hygiene.run
    bench --site <site> execute caf.scripts.leave_type_hygiene.run --kwargs "{'apply':1}"
    bench --site <site> execute caf.scripts.leave_type_hygiene.verify

⚠️ **Not test-server-only.** ERPNext seeds these Leave Types on every site, so
production carries the same rows.

WHY THIS EXISTS
---------------
MG, 2026-09-04: *"disable [Casual Leave]"*. It is the one Leave Type on the site
carrying **`is_carry_forward = 1`**, which contradicts §6.15's *"no carry-over at
any length of service"* — the rule the whole entitlement formula rests on.

**It is unused today and that is exactly why it is worth doing now.** Measured
2026-09-04: 0 allocations, 0 applications, 0 Leave Policy rows, 0 Attendance
rows. So neutralising it costs nothing and removes a loaded gun — the first
person to allocate it would create carry-forward that no CAF rule expects and
nothing reports.

🔴 **There is no `disabled` field on Leave Type in this version** — the meta
carries nothing matching `disab`/`active`. So "disable" is implemented as
**turning off the offending behaviour**, not hiding the record:

    is_carry_forward  1 -> 0

⚠️ **Deletion was considered and rejected.** `Casual Leave` is a stock record;
deleting it risks a stock report or fixture expecting it, and buys nothing that
the flag does not. If MG wants it gone entirely that is a separate, deliberate
act — `frappe.delete_doc("Leave Type", "Casual Leave")` — and it should be done
only after checking prod for references.

⚠️ `db.set_value` writes no Version (OD-26), so each change leaves a Comment.
"""

import frappe

# (leave type, field, wanted value, why)
RULES = [
    ("Casual Leave", "is_carry_forward", 0,
     "§6.15 — CAF carries nothing over at any length of service. This is the "
     "only Leave Type on the site that would, and it is unused (0 allocations, "
     "0 applications, 0 policy rows), so the flag is a trap rather than a "
     "practice. MG, 2026-09-04: 'disable'."),
]


def _state():
    out = []
    for lt, field, want, why in RULES:
        if not frappe.db.exists("Leave Type", lt):
            out.append((lt, field, None, want, why, "ABSENT"))
            continue
        now = frappe.db.get_value("Leave Type", lt, field)
        usage = {
            "allocations": frappe.db.count("Leave Allocation", {"leave_type": lt}),
            "applications": frappe.db.count("Leave Application", {"leave_type": lt}),
            "policy rows": frappe.db.sql(
                "SELECT COUNT(*) FROM `tabLeave Policy Detail` WHERE leave_type=%s",
                (lt,))[0][0],
        }
        out.append((lt, field, now, want, why, usage))
    return out


def run(apply=0):
    apply = int(apply or 0)
    frappe.set_user("Administrator")
    acted = []

    for lt, field, now, want, why, usage in _state():
        print(f"\n{'=' * 74}\n{lt}.{field}")
        print(f"  {why}")
        if usage == "ABSENT":
            print("  ⚪ not on this site — nothing to do")
            continue
        print(f"  in use: {usage}")
        print(f"  NOW  {now}   WANT  {want}")
        if int(now or 0) == int(want):
            print("  ✅ already correct")
            continue
        if any(usage.values()):
            print(f"  🔴 STOP — it is IN USE. Changing carry-forward on a type "
                  f"somebody holds would silently change their balance. "
                  f"Decide the data first.")
            continue
        if not apply:
            continue
        frappe.db.set_value("Leave Type", lt, field, want, update_modified=False)
        frappe.get_doc("Leave Type", lt).add_comment(
            "Comment",
            f"CAF set {field} = {want} (2026-09-04). {why}")
        acted.append(f"{lt}.{field}")

    if not apply:
        print("\n(report only — pass apply=1 to write)")
        return {"would_change": len([1 for r in _state()
                                     if r[5] != "ABSENT"
                                     and int(r[2] or 0) != int(r[3])])}
    frappe.db.commit()
    frappe.clear_cache()
    print(f"\nDONE — {len(acted)} change(s): {acted}")
    return {"changed": acted}


def verify():
    """Both directions: the flag is off, and nothing started using the type."""
    fails = 0
    for lt, field, now, want, _why, usage in _state():
        if usage == "ABSENT":
            print(f"LTH-{lt} SKIP  not on this site")
            continue
        ok = int(now or 0) == int(want)
        unused = not any(usage.values())
        print(f"LTH-{lt} {'PASS' if ok else 'FAIL'}  {field}={now} (want {want}); "
              f"still unused: {unused} {usage}")
        fails += 0 if ok else 1

    others = frappe.get_all("Leave Type", filters={"is_carry_forward": 1},
                            pluck="name")
    ok2 = not others
    print(f"LTH-NONE-CARRY {'PASS' if ok2 else 'FAIL'}  Leave Types still carrying "
          f"forward: {others or 'none'} — §6.15 says the answer is none")
    fails += 0 if ok2 else 1
    print(f"\n{'clean' if not fails else str(fails) + ' problem(s)'}")
