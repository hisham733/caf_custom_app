"""Move an employee permanently from one Shift Type to another.

    bench --site <site> execute caf.scripts.shift_reassign.run
    bench --site <site> execute caf.scripts.shift_reassign.apply
    bench --site <site> execute caf.scripts.shift_reassign.verify

⚠️ **Not test-server-only.** This is the routine HR act — *"Mr A moves to the
other half of the pair from now on"* — and it is the same two writes on
production as here.

WHY THIS EXISTS
---------------
MG, 2026-09-07: *"8-5 Alt Sat 1st-3rd — move Noor Arifah Binti Ibrahim into this
shift_type."*

It exists as a script rather than as two clicks because **a permanent shift move
is two fields, not one**, and doing only the obvious one is silent:

    Employee.default_shift   the shift itself
    Employee.holiday_list    🔴 FDR6 — every stock function (leave-day counting,
                             `is_holiday`) reads the EMPLOYEE's list and knows
                             nothing about shifts. Leave `holiday_list` behind
                             and the person works the new Saturdays while their
                             leave is still counted against the old ones.

🔴 IDENTIFIED BY DEVICE ID, NOT BY `HR-EMP-xxxxx` — T-32
---------------------------------------------------------
`HR-EMP-00096` means *"the 96th employee record created on THIS site"*. The test
server was populated by a bulk import whose row order was not production's, so
**the same id is a different person on each server**. `attendance_device_id` is
the Ingress user id, identical on both by construction, and 88 of 89 active
employees carry one.

This script is the first written after that rule was adopted, so it demonstrates
the shape: **resolve by device id, refuse if the name does not also match.**
Both must agree or nothing is written — a device id typo that happens to hit a
real employee is exactly the failure the name check catches.

⚠️ A `Shift Assignment` BEATS `default_shift` for the dates it covers, so this
changes the routine placement and leaves any dated exception alone. `run()`
lists them so nobody is surprised.
"""

import frappe

# (device id, expected name, from shift, to shift, why)
MOVES = [
    ("1059", "Noor Arifah Binti Ibrahim",
     "8-5 Alt Sat 2nd-4th", "8-5 Alt Sat 1st-3rd",
     "MG, 2026-09-07. The production pair were both on `2nd-4th`, which "
     "reproduced what Ingress showed — off together on 24 of 32 Saturdays — but "
     "leaves `1st-3rd` empty and the pair covering nothing. Moving her makes the "
     "two halves actually alternate, so one of them is always at work."),
]


def _resolve(device_id, expected_name):
    """Device id -> employee, and the name must agree. Returns (name, problem)."""
    hits = frappe.get_all("Employee",
                          filters={"attendance_device_id": device_id},
                          fields=["name", "employee_name", "status",
                                  "default_shift", "holiday_list"])
    if not hits:
        return None, f"no employee carries attendance_device_id {device_id!r}"
    if len(hits) > 1:
        return None, (f"{len(hits)} employees carry device id {device_id!r}: "
                      f"{[h.name for h in hits]} — ambiguous, refusing")
    e = hits[0]
    got = " ".join((e.employee_name or "").split())
    want = " ".join(expected_name.split())
    if got.lower() != want.lower():
        return None, (f"device {device_id} is {got!r}, not {want!r} — the id and "
                      f"the name disagree, so one of them is wrong")
    return e, None


def _plan():
    out = []
    for device_id, name, frm, to, why in MOVES:
        e, problem = _resolve(device_id, name)
        want_list = frappe.db.get_value("Shift Type", to, "holiday_list")
        if not frappe.db.exists("Shift Type", to):
            problem = problem or f"target shift {to!r} does not exist"
        out.append({
            "device": device_id, "expected": name, "from": frm, "to": to,
            "why": why, "employee": e, "problem": problem,
            "want_list": want_list,
        })
    return out


def run():
    print(f"\n{'=' * 76}\nPERMANENT SHIFT MOVES\n{'=' * 76}")
    todo = 0
    for p in _plan():
        print(f"\ndevice {p['device']}  {p['expected']}")
        if p["problem"]:
            print(f"  🔴 REFUSED — {p['problem']}")
            continue
        e = p["employee"]
        done = e.default_shift == p["to"] and e.holiday_list == p["want_list"]
        print(f"  resolves to  {e.name} [{e.status}]")
        print(f"  shift        {e.default_shift}  →  {p['to']}")
        print(f"  holiday list {e.holiday_list}  →  {p['want_list']}")
        if e.default_shift != p["from"] and e.default_shift != p["to"]:
            print(f"  ⚠️ expected to find them on {p['from']!r} — they are on "
                  f"{e.default_shift!r}. Somebody has moved them already")
        print(f"  why          {p['why']}")

        # Dated exceptions survive this and beat default_shift while they run.
        sa = frappe.get_all("Shift Assignment",
                            filters={"employee": e.name, "docstatus": 1},
                            fields=["name", "shift_type", "start_date", "end_date"])
        print(f"  dated Shift Assignments that still override this: "
              f"{len(sa)}{' — ' + str(sa) if sa else ''}")

        if done:
            print("  ✅ already there")
        else:
            todo += 1

    print(f"\n{'-' * 76}\n{todo} move(s) pending. Run `apply` to write them.")
    return {"pending": todo}


def apply():
    frappe.set_user("Administrator")
    changed, skipped = [], []

    for p in _plan():
        if p["problem"]:
            skipped.append((p["device"], p["problem"]))
            continue
        e = p["employee"]
        if e.default_shift == p["to"] and e.holiday_list == p["want_list"]:
            skipped.append((p["device"], "already there"))
            continue

        frappe.db.set_value("Employee", e.name, {
            "default_shift": p["to"],
            "holiday_list": p["want_list"],
        })
        frappe.get_doc("Employee", e.name).add_comment(
            "Comment",
            f"Shift moved {e.default_shift} → {p['to']} and holiday list "
            f"{e.holiday_list} → {p['want_list']} (FDR6 — the employee's list is "
            f"what stock reads). {p['why']}")
        changed.append((e.name, e.employee_name, e.default_shift, p["to"]))

    frappe.db.commit()
    print(f"\nMOVED {len(changed)}:")
    for c in changed:
        print(f"    {c[0]} {c[1][:34]:34s} {c[2]} → {c[3]}")
    print(f"SKIPPED {len(skipped)}:")
    for s in skipped:
        print(f"    device {s[0]}: {s[1]}")
    return {"changed": changed, "skipped": skipped}


def verify():
    """The move landed, the list came with it, and the pair is no longer lopsided."""
    fails = 0
    for p in _plan():
        if p["problem"]:
            print(f"SR-{p['device']} FAIL  {p['problem']}")
            fails += 1
            continue
        e = frappe.db.get_value("Employee", p["employee"].name,
                                ["employee_name", "default_shift", "holiday_list"],
                                as_dict=True)
        ok = e.default_shift == p["to"] and e.holiday_list == p["want_list"]
        print(f"SR-{p['device']} {'PASS' if ok else 'FAIL'}  {e.employee_name[:30]:30s} "
              f"shift={e.default_shift} list={e.holiday_list}")
        fails += 0 if ok else 1

    # 🔴 The point of the move: a pair with everybody on one side covers nothing.
    for a, b in (("8-5 Alt Sat 1st-3rd", "8-5 Alt Sat 2nd-4th"),
                 ("8:30am Alt Sat 1st-3rd", "8:30am Alt Sat 2nd-4th")):
        na = frappe.db.count("Employee", {"default_shift": a, "status": "Active"})
        nb = frappe.db.count("Employee", {"default_shift": b, "status": "Active"})
        ok = not (na == 0 and nb > 0) and not (nb == 0 and na > 0)
        print(f"SR-PAIR-{a[:12]} {'PASS' if ok else 'FAIL'}  {a}={na} {b}={nb} "
              f"— a pair with everybody on one side alternates with nobody")
        fails += 0 if ok else 1

    print(f"\n{'clean' if not fails else str(fails) + ' problem(s)'}")
    return fails
