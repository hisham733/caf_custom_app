"""Chunk 7.5 — the Shift & Saturday roster.  OD-72 · OD-71's detector.

    bench --site <site> execute caf.tests.fingerlog.test_chunk7_roster.run

🔴 THE TWO ASSERTIONS THAT EARN THEIR PLACE
-------------------------------------------
**C75-LIVE.** The grid must resolve every cell through `resolve_day_type()`, not
read `Finger Log.day_type`. Measured 2026-08-12, three of July's 32 alt-Saturday
cells had a stored day_type that disagreed with live resolution — so a grid built
on the stored value would show HR a roster the system does not actually believe,
and would keep showing it after the trade that fixed it.

**C75-DETECT.** OD-71. HR asked for a weekly prompt; MG chose a detector. The
whole claim is that the system can find an unrecorded holiday by itself, so the
test builds the 14-February shape — a working day almost nobody punched — and
asserts it is found. ⚠️ And **C75-QUIET** is its other half: a detector that
fires on ordinary days is worse than none, because HR stops reading it.

POPULATION IS A RULE, NOT A LIST (MG's Q2)
------------------------------------------
Rows are *whoever is on a shift with `caf_alt_sat = 1`* — including someone an
assignment put there for a few days. `C75-POP` proves the derivation; a hardcoded
list of eight names would have rotted the first time HR moved anybody.

Fixtures are **June 2026** (§F4d), on **2026-06-24 / 06-26 / 06-27**, which are
clear of `test_alt_saturday` (06-06) and `test_chunk7_swap` (06-13, 06-20).
"""

import frappe

from caf.caf.overrides import shift_type_dashboard
from caf.caf.page.shift_roster import shift_roster
from caf.caf.shift_resolution import resolve_day_type
from caf.caf.shift_swap import create as file_trade

# Deliberately NOT the employees the other alt-Saturday suites use (00003 /
# 00004 / 00005 / 00042), so a failure here is about this screen.
ALT_A = "HR-EMP-00009"       # Seow Zi Ying   — 8:30am Alt Sat 1st-3rd
ALT_B = "HR-EMP-00010"       # Hazwani        — 8:30am Alt Sat 2nd-4th
PLAIN = "HR-EMP-00020"       # Chan Wai Khong — 8am Schedule, not alternating

EMP_USER = "seriramulu@caffood.com"          # role Employee
HR_USER = "hr.user.test@caffood.com"         # role HR User — read, not manage
HRM = "hr.manager.test@caffood.com"          # role HR Manager

MONTH = "2026-06"
D_SAT = "2026-06-27"         # free June Saturday
D_SINGLE = "2026-06-26"      # Friday — the standalone case, no Saturday meaning
D_QUIET = "2026-06-24"       # Wednesday — the detector fixture lands here
# 🔴 OD-69(b)'s fixture. A PAST Saturday, because the detector deliberately
# ignores future days. Shared with test_chunk7_swap, which is safe only because
# the suites run sequentially and each cleans up in its own `finally` — if this
# suite is ever run concurrently, give it a date of its own.
D_GROUP = "2026-06-20"

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def as_user(user, fn, *a, **kw):
    """PROTOCOL §C1b — restore in a `finally`. A suite that exits still switched
    leaves every later suite in the process running as somebody else."""
    frappe.set_user(user)
    try:
        return fn(*a, **kw)
    except Exception as e:
        return ("ERROR", type(e).__name__, str(e))
    finally:
        frappe.set_user("Administrator")


def refused(res):
    return isinstance(res, tuple) and res and res[0] == "ERROR"


def quiet_day_employees(n=8):
    """Whoever the detector fixture will use — derived, so cleanup and creation
    can never disagree about the list (§F4)."""
    return [e.name for e in frappe.get_all(
        "Employee", filters={"default_shift": "8am Schedule", "status": "Active"},
        fields=["name"], order_by="name", limit_page_length=n)]


def rest_groups_on(day):
    """Which alt-Sat groups rest on `day`, derived — never hardcoded.

    §F4d's lesson generalised: moving a fixture date turned every hardcoded
    expected value into a lie at once. The groups are read from the live
    configuration, so this survives HR moving anybody.
    """
    alt = [s.name for s in shift_roster.alt_shifts()]
    emps = frappe.get_all("Employee",
                          filters={"default_shift": ("in", alt), "status": "Active"},
                          fields=["name", "employee_name", "default_shift"])
    groups = {}
    for e in emps:
        day_type, shift = resolve_day_type(e.name, day)
        if day_type == "Restday" and shift in alt:
            groups.setdefault(shift, []).append(e)
    return groups


def make_worked_log(emp, day):
    """A PUNCHED log on a day the roster calls rest — the OD-69(b) shape."""
    doc = frappe.new_doc("Finger Log")
    doc.employee = emp
    doc.employee_name = frappe.db.get_value("Employee", emp, "employee_name")
    doc.work_date = day
    doc.time_in, doc.out = "08:30:00", "17:30:00"
    doc.set("break", "12:00:00")
    doc.resume = "13:00:00"
    doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    if doc.docstatus == 0 and not doc.get("caf_not_full_day"):
        doc.submit()
    return doc


def make_quiet_log(emp):
    """A rostered working day with NO punch — the 14-February shape.

    ⚠️ `00:00:00`, not NULL. The importer writes the sentinel and this project
    has twice concluded the wrong thing from `IS NULL = 0` (§F2).
    """
    doc = frappe.new_doc("Finger Log")
    doc.employee = emp
    doc.employee_name = frappe.db.get_value("Employee", emp, "employee_name")
    doc.work_date = D_QUIET
    for f in ("time_in", "break", "resume", "out"):
        doc.set(f, "00:00:00")
    doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    if doc.docstatus == 0 and not doc.get("caf_not_full_day"):
        doc.submit()
    return doc


def cleanup():
    """Scoped by employee AND by this suite's three June dates (§F4).

    Partner links first: they are real Links, so a paired row cannot be deleted
    while its twin points at it, and `force=True` does not bypass that.
    """
    dates = [D_SAT, D_SINGLE]
    scope = {"employee": ("in", [ALT_A, ALT_B, PLAIN]), "start_date": ("in", dates)}

    for r in frappe.get_all("Shift Assignment", filters=scope, fields=["name"]):
        frappe.db.set_value("Shift Assignment", r.name, "caf_swap_partner", None,
                            update_modified=False)
    frappe.db.commit()

    for r in frappe.get_all("Shift Assignment", filters=scope, fields=["name", "docstatus"]):
        doc = frappe.get_doc("Shift Assignment", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Shift Assignment", r.name, ignore_permissions=True, force=True)

    alt_emps = [e.name for e in frappe.get_all(
        "Employee",
        filters={"default_shift": ("in", [s.name for s in shift_roster.alt_shifts()])},
        fields=["name"])]
    for r in frappe.get_all("Finger Log",
                            filters={"work_date": ("in", [D_QUIET, D_GROUP]),
                                     "employee": ("in", quiet_day_employees() + alt_emps)},
                            fields=["name", "docstatus"]):
        # ⚠️ The quiet logs each produce an Attendance, and it is SUBMITTED — a
        # submitted document cannot be deleted, and `force=True` does not
        # bypass that. Cancel, then delete. Found by this suite's first run.
        for att in frappe.get_all("Attendance",
                                  filters={"caf_finger_log": r.name},
                                  fields=["name", "docstatus"]):
            adoc = frappe.get_doc("Attendance", att.name)
            adoc.flags.ignore_permissions = True
            adoc.flags.ignore_links = True
            if adoc.docstatus == 1:
                adoc.cancel()
            frappe.delete_doc("Attendance", att.name, ignore_permissions=True, force=True)
        doc = frappe.get_doc("Finger Log", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Finger Log", r.name, ignore_permissions=True, force=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    cleanup()

    # A cleanliness guard before anything is measured. Chunk 3's CLEAN assertion
    # encoded the very bug it should have caught (§F4b), so this asserts the
    # fixture DATES are empty — never that the employees have no data at all.
    pre_quiet = frappe.db.count("Finger Log", {"work_date": D_QUIET})
    check("C75-FIX", pre_quiet == 0,
          f"the detector's fixture date {D_QUIET} starts empty: {pre_quiet} log(s). "
          f"A leftover here would make C75-DETECT pass or fail for the wrong reason")

    try:
        # ------------------------------------------------------------ C75-SHAPE
        data = shift_roster.get_roster(MONTH)
        sats = data["saturdays"]
        check("C75-SHAPE", sats == ["2026-06-06", "2026-06-13", "2026-06-20", "2026-06-27"]
              and len(data["rows"]) >= 8,
              f"June 2026 has {len(sats)} Saturdays and the grid drew "
              f"{len(data['rows'])} rows from `caf_alt_sat`")

        # ------------------------------------------------------------- C75-MIRROR
        # ALT3's property, on this surface: the SAME date is Restday for one
        # mirror and Workday for the other. If this ever goes green with both
        # sides equal, the mirror design has stopped meaning anything.
        by_emp = {r["employee"]: r for r in data["rows"]}
        a_cells = {c["date"]: c["day_type"] for c in by_emp[ALT_A]["cells"]}
        b_cells = {c["date"]: c["day_type"] for c in by_emp[ALT_B]["cells"]}
        opposed = [d for d in sats if a_cells[d] != b_cells[d]
                   and "Holiday" not in (a_cells[d], b_cells[d])]
        check("C75-MIRROR", len(opposed) >= 2,
              f"opposite mirrors resolve opposite ways on {len(opposed)} of "
              f"{len(sats)} Saturdays — e.g. {opposed[0] if opposed else '-'}: "
              f"{a_cells.get(opposed[0]) if opposed else '?'} vs "
              f"{b_cells.get(opposed[0]) if opposed else '?'}")

        # -------------------------------------------------------------- C75-LIVE 🔴
        # The grid must not read a stored day_type. Force the two apart on the
        # Finger Log and prove the grid still shows what the RESOLVER says.
        # ⚠️ mutates a field, so it is restored in the `finally` below.
        log = frappe.db.get_value(
            "Finger Log", {"employee": ALT_A, "docstatus": ("<", 2)},
            ["name", "work_date", "day_type"], as_dict=True)
        if log:
            original = log.day_type
            lie = "Holiday" if original != "Holiday" else "Workday"
            try:
                frappe.db.set_value("Finger Log", log.name, "day_type", lie,
                                    update_modified=False)
                month = str(log.work_date)[:7]
                probe = shift_roster.get_roster(month)
                row = next((r for r in probe["rows"] if r["employee"] == ALT_A), None)
                cell = next((c for c in (row or {}).get("cells", [])
                             if c["date"] == str(log.work_date)), None)
                check("C75-LIVE", cell is not None and cell["day_type"] != lie,
                      f"the grid ignores a stored day_type: {log.name} was forced to "
                      f"'{lie}' and the cell still reads "
                      f"'{cell['day_type'] if cell else 'no cell'}'. Three of July's "
                      f"32 cells really do disagree, so this is not hypothetical")
            finally:
                frappe.db.set_value("Finger Log", log.name, "day_type", original,
                                    update_modified=False)
                frappe.db.commit()
        else:
            check("C75-LIVE", False,
                  f"no Finger Log for {ALT_A} to test the stored-vs-live split against")

        # -------------------------------------------------------------- C75-SWAP
        res = file_trade(D_SAT, ALT_A, ALT_B)
        after = shift_roster.get_roster(MONTH)
        a2 = {c["date"]: c for c in
              next(r for r in after["rows"] if r["employee"] == ALT_A)["cells"]}
        b2 = {c["date"]: c for c in
              next(r for r in after["rows"] if r["employee"] == ALT_B)["cells"]}
        check("C75-SWAP", res["kind"] == "Swap"
              and a2[D_SAT]["day_type"] == b_cells[D_SAT]
              and b2[D_SAT]["day_type"] == a_cells[D_SAT]
              and a2[D_SAT]["overridden"] and b2[D_SAT]["overridden"],
              f"a filed trade shows in the grid WITHOUT being looked up: on {D_SAT} "
              f"{ALT_A} went {a_cells[D_SAT]} ➜ {a2[D_SAT]['day_type']} and {ALT_B} "
              f"went {b_cells[D_SAT]} ➜ {b2[D_SAT]['day_type']}, both marked as moved")

        # ---------------------------------------------------------- C75-OVERRIDE
        # MG's sentence: "Mr A's original shift is X but the doc changed it to B."
        ov = [r for r in after["overrides"] if r["employee"] == ALT_A
              and r["start_date"] == D_SAT]
        check("C75-OVERRIDE", len(ov) == 1 and ov[0]["changed"]
              and ov[0]["default_shift"] != ov[0]["shift_type"]
              and ov[0]["kind"] == "Swap" and ov[0]["partner"],
              f"the override table names both shifts: default "
              f"'{ov[0]['default_shift'] if ov else '?'}' ➜ assigned "
              f"'{ov[0]['shift_type'] if ov else '?'}', kind "
              f"{ov[0]['kind'] if ov else '?'}, paired with "
              f"{ov[0]['partner'] if ov else 'NOTHING'}")

        # --------------------------------------------------------------- C75-POP 🔴
        # MG's Q2 rule. PLAIN is on `8am Schedule` and is in NO row of the grid;
        # put him on an alt shift for one day and he must appear — derived from
        # `caf_alt_sat`, never from a list of names.
        before_pop = {r["employee"] for r in after["rows"]}
        alt_shift = frappe.db.get_value("Employee", ALT_A, "default_shift")
        file_trade(D_SINGLE, PLAIN, None, shift=alt_shift)
        with_pop = shift_roster.get_roster(MONTH)
        now_pop = {r["employee"] for r in with_pop["rows"]}
        check("C75-POP", PLAIN not in before_pop and PLAIN in now_pop,
              f"population is a RULE, not a list: {PLAIN} is on 8am Schedule and was "
              f"absent from the grid ({len(before_pop)} rows); one assignment onto "
              f"{alt_shift} put him in it ({len(now_pop)} rows)")

        # -------------------------------------------------------------- C75-KIND
        # A standalone assignment is NOT a swap and must not be filed as one — but
        # it belongs in the same list. One table with a `kind` column, not two
        # sections, because to HR all three are "a doc that overrides a shift".
        single = [r for r in with_pop["overrides"] if r["employee"] == PLAIN]
        check("C75-KIND", len(single) == 1 and single[0]["kind"] == "Single"
              and not single[0]["traded_with"] and not single[0]["partner"],
              f"the standalone case is carried in the SAME list with kind="
              f"'{single[0]['kind'] if single else '?'}', no partner and nobody "
              f"traded with — it is not dressed up as half a swap")

        # ----------------------------------------------------------- C75-HALFDONE
        # Cancel one half and the alarm must find the survivor. This is the whole
        # reason `caf_swap_partner` exists.
        half_before = shift_roster.get_roster(MONTH)["half_done"]["count"]
        one = frappe.get_doc("Shift Assignment", ov[0]["name"])
        one.flags.ignore_permissions = True
        one.cancel()
        frappe.db.commit()
        half_after = shift_roster.get_roster(MONTH)["half_done"]
        check("C75-HALFDONE", half_after["count"] == half_before + 1
              and any(r["employee"] == ALT_B for r in half_after["rows"]),
              f"cancelling one half raises the alarm: {half_before} ➜ "
              f"{half_after['count']}, naming {ALT_B}, who is still rostered for a "
              f"Saturday his partner no longer covers")

        # ------------------------------------------------------------ C75-DETECT 🔴
        # OD-71. Build the 14-February shape and prove the system finds it alone.
        quiet = quiet_day_employees()
        for emp in quiet:
            make_quiet_log(emp)
        frappe.db.commit()
        gap = shift_roster.holiday_gap("2026-06-01", "2026-06-30")
        hit = next((r for r in gap["rows"] if r["work_date"] == D_QUIET), None)
        check("C75-DETECT", hit is not None and hit["no_punch"] == len(quiet)
              and hit["names"],
              f"the detector found {D_QUIET} by itself: {hit['no_punch'] if hit else 0} "
              f"of {hit['rostered'] if hit else 0} rostered people never clocked in, "
              f"and it names them. This is 2026-02-14's shape, which HR found only "
              f"six months later")

        # ------------------------------------------------------------- C75-QUIET
        # The other half, and the one that keeps the alarm readable: it must NOT
        # fire on ordinary days. July is a real month with real punches.
        july = shift_roster.holiday_gap("2026-07-01", "2026-07-31")
        check("C75-QUIET", july["count"] == 0,
              f"and it stays silent on a normal month: July 2026 raised "
              f"{july['count']} day(s). A detector that cries wolf is one HR stops "
              f"reading")

        # ------------------------------------------------------------ C75-FUTURE
        # A working day that has not happened has no punches. Without the
        # `work_date <= today` bound the alarm would fire every week, forever.
        far = shift_roster.holiday_gap("2027-06-01", "2027-06-30")
        check("C75-FUTURE", far["count"] == 0,
              f"future working days are excluded: June 2027 raised {far['count']}. "
              f"Nobody has punched then, so every day would look like a holiday")

        # -------------------------------------------------------------- C75-ROLE 🔴
        # The Page's role list decides who may OPEN the route. It does not decide
        # what a whitelisted method returns to a caller who reaches it directly
        # (§C4). `frappe.only_for` is the lock, and this is what proves it.
        emp_try = as_user(EMP_USER, shift_roster.get_roster, MONTH)
        hru_try = as_user(HR_USER, shift_roster.get_roster, MONTH)
        check("C75-ROLE", refused(emp_try) and not refused(hru_try),
              f"Employee ➜ {emp_try[1] if refused(emp_try) else '🔴 GOT THE ROSTER'}; "
              f"HR User ➜ {'🔴 REFUSED' if refused(hru_try) else str(len(hru_try.get('rows', []))) + ' rows'}. "
              f"MG, 2026-08-12: HR User can SEE. They already hold `read` on Shift "
              f"Assignment, so withholding the roster told them nothing the list view "
              f"would not")

        # 🔴 The other half of "see only", and the one that would fail silently.
        # Reading the roster must not carry the right to change it.
        file_try = as_user(HR_USER, file_trade, D_SAT, ALT_A, ALT_B)
        check("C75-READONLY", refused(file_try),
              f"...but HR User may NOT file: "
              f"{file_try[1] if refused(file_try) else '🔴 HR USER FILED A TRADE'}. "
              f"Read and manage are different populations — the hidden button is "
              f"tidiness, `frappe.only_for` is the lock (§C4)")

        hrm_try = as_user(HRM, shift_roster.get_roster, MONTH)
        check("C75-HR", not refused(hrm_try) and hrm_try.get("rows"),
              f"and HR Manager does get it — {len(hrm_try.get('rows', [])) if not refused(hrm_try) else 0} "
              f"rows. Without this, C75-ROLE could be passing because the method is "
              f"broken for everyone")

        gap_try = as_user(EMP_USER, shift_roster.holiday_gap, "2026-06-01", "2026-06-30")
        check("C75-ROLE2", refused(gap_try),
              f"the detector is locked separately, not only through get_roster: "
              f"{gap_try[1] if refused(gap_try) else '🔴 an Employee read it'}")

        # -------------------------------------------------------------- C75-CONN
        # Placement (a). hrms' own dashboard links Shift Assignment but not
        # Employee, so the standing population was invisible from the shift.
        dash = shift_type_dashboard.get_data()
        items = [i for group in dash["transactions"] for i in group["items"]]
        check("C75-CONN", "Employee" in items
              and dash["non_standard_fieldnames"].get("Employee") == "default_shift"
              and "Shift Assignment" in items,
              f"Shift Type Connections now carries Employee on `default_shift` "
              f"alongside stock's {len(items) - 1} others — without the non-standard "
              f"fieldname it would resolve against `shift` and silently show nothing")

        # ------------------------------------------------------------- C75-GROUP 🔴
        # OD-69(b). The mirror image of the missing-holiday detector: a REST
        # Saturday the whole group came in for.
        groups = rest_groups_on(D_GROUP)
        strong = next((s for s, m in groups.items() if len(m) >= 3), None)
        weak = next((s for s, m in groups.items() if len(m) == 2), None)

        # ONE person working a rest Saturday is overtime, not a roster error.
        # This must NOT fire — it is the assertion that stops the detector
        # becoming an alarm on every legitimate rest-day OT row.
        make_worked_log(groups[strong][0].name, D_GROUP)
        frappe.db.commit()
        one = shift_roster.group_worked_rest_day(D_GROUP, D_GROUP)
        check("C75-GROUP1", one["count"] == 0,
              f"one member of {strong} working {D_GROUP} raises NOTHING "
              f"({one['count']} rows) — that is rest-day overtime, which FBR4 pays "
              f"and nobody should be alarmed about")

        # Now the rest of the group. The signal is the COUNT, not any one log.
        for e in groups[strong][1:]:
            make_worked_log(e.name, D_GROUP)
        frappe.db.commit()
        allg = shift_roster.group_worked_rest_day(D_GROUP, D_GROUP)
        hit = next((r for r in allg["rows"] if r["shift"] == strong), None)
        check("C75-GROUP", hit is not None
              and hit["worked"] == hit["group_size"] == len(groups[strong])
              and hit["strength"] == "strong",
              f"but ALL {len(groups[strong])} of {strong} working it is found: "
              f"{hit['worked'] if hit else 0} of {hit['group_size'] if hit else 0}, "
              f"marked '{hit['strength'] if hit else '-'}'. February 2026 would "
              f"have raised this three times")

        # ⚠️ MG's own objection, made testable: a 2-person group is weak evidence.
        if weak:
            for e in groups[weak]:
                make_worked_log(e.name, D_GROUP)
            frappe.db.commit()
            both = shift_roster.group_worked_rest_day(D_GROUP, D_GROUP)
            w = next((r for r in both["rows"] if r["shift"] == weak), None)
            check("C75-WEAK", w is not None and w["strength"] == "weak",
                  f"and a 2-person group is carried but marked '"
                  f"{w['strength'] if w else '-'}' — MG's point: with two people "
                  f"'both worked' could as easily be two people who came in. HR "
                  f"reads 6-of-6 as urgent and 2-of-2 as worth a glance")
        else:
            check("C75-WEAK", False, "no 2-person group rests on " + D_GROUP)

        # -------------------------------------------------------------- C75-FLAG
        # It FLAGS, it never blocks. Every log above submitted normally.
        res_flag = shift_roster.flag_group_rest_day_work(D_GROUP, D_GROUP)
        flagged = frappe.get_all(
            "Finger Log",
            filters={"work_date": D_GROUP, "caf_hr_review": 1},
            fields=["name", "caf_hr_review_note", "docstatus"])
        check("C75-FLAG", res_flag["count"] > 0 and flagged
              and all(f.docstatus == 1 for f in flagged)
              and "rest day" in (flagged[0].caf_hr_review_note or ""),
              f"{res_flag['count']} log(s) flagged with `caf_hr_review` — the same "
              f"field and worklist Chunk 4 uses, so HR has one queue. Every one is "
              f"still SUBMITTED (docstatus 1): the detector flags and never blocks, "
              f"because rest-day work is legitimate and FBR4 pays it")

        # -------------------------------------------------------------- C75-SEED
        # The real July trade the seeder filed, guarded so a later cleanup cannot
        # quietly remove it and leave the screen empty again.
        seeded = frappe.get_all(
            "Shift Assignment",
            filters={"employee": "HR-EMP-00003", "docstatus": 1,
                     "start_date": ("in", ["2026-07-04", "2026-07-11"])},
            fields=["name", "caf_swap_kind", "caf_swap_partner", "caf_swap_with"])
        check("C75-SEED", len(seeded) == 2
              and all(s.caf_swap_kind == "Swap" and s.caf_swap_partner for s in seeded),
              f"the real July trade is still filed and still paired: {len(seeded)} of 2 "
              f"rows, partners "
              f"{[bool(s.caf_swap_partner) for s in seeded]}. It is the only trade "
              f"actually visible in the imported punches")

    finally:
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    left_sa = frappe.db.count("Shift Assignment",
                              {"employee": ("in", [ALT_A, ALT_B, PLAIN]),
                               "start_date": ("in", [D_SAT, D_SINGLE])})
    left_fl = frappe.db.count("Finger Log", {"work_date": D_QUIET})
    check("C75-CLEAN", left_sa == 0 and left_fl == 0,
          f"the suite left {left_sa} assignment(s) and {left_fl} Finger Log(s) behind")

    print("\n=== Chunk 7.5 — shift & Saturday roster (OD-72, OD-71) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:15s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
