"""The guards against ordinary data-entry error — MG's manual test, 2026-09-02.

    bench --site <site> execute caf.tests.fingerlog.test_basic_validation.run

MG filed a real `Monthly Roster Confirmation` by hand and it submitted carrying
two mistakes that nothing noticed. Both are the same species: **a form that
believes what it is told.**

    ROSTER-2026-08, submitted, owner natalie@
      · a holiday dated 2026-09-09        — not in the month being confirmed
      · ONE Saturday row, dated 2026-09-11 — not in the month, not a Saturday,
        no shift, and `agreed` ticked

The Saturday one is the serious half. `fill_saturdays` was guarded by
`if not self.saturdays`, so a single row in the grid — including the empty one
the desk's **Add Row** button makes — skipped the whole pre-fill. **15 generated
rows became 1 blank one, and the document then recorded that HR had confirmed the
roster.** That is precisely the failure the form exists to prevent (§6.12: *"the
manual step is where the errors came from"*).

Also covered: `OT Approval.type = special_approve`, restricted to HR Manager and
Leave Approver on 2026-09-02 (FBR71). A **normal** approval stays open to the
`Employee` role on purpose (FBR70) — six of these assertions exist to prove the
new guard did NOT narrow that.

Self-cleaning: every case is rolled back; nothing is left on the site.
"""

import frappe
from frappe.utils import add_days, nowdate

RESULTS = []
MONTH = "2026-11-01"          # far from the imported July/August data


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:28s} {'PASS' if ok else 'FAIL'}  {detail}")


def _roster(seed=None, holidays=None, month=MONTH):
    d = frappe.new_doc("Monthly Roster Confirmation")
    d.month_start = month
    if holidays:
        for name, date_, day in holidays:
            r = d.append("holidays", {})
            r.holiday_name, r.holiday_date, r.day_of_week = name, date_, day
    else:
        d.no_new_holidays = 1
    if seed:
        seed(d)
    d.flags.ignore_permissions = True
    d.insert()
    return d


def _refused(fn):
    try:
        return False, fn()
    except frappe.ValidationError as e:
        return True, str(e)


def run():
    frappe.set_user("Administrator")
    try:
        # ── BV1 — the control: a clean form generates the whole month ──────
        try:
            d = _roster()
            n_clean, ticks = len(d.saturdays), sum(1 for s in d.saturdays if s.agreed)
        finally:
            frappe.db.rollback()
        check("BV1-GENERATES-THE-MONTH", n_clean > 1,
              f"a clean form pre-fills {n_clean} Saturday rows ({ticks} ticked) from "
              f"the generated calendar — every Saturday of the month × every "
              f"alternating shift group. This is the number the defect below "
              f"replaced with 1")

        # ── BV2 — 🔴 the defect MG found ───────────────────────────────────
        try:
            d = _roster(seed=lambda x: x.append("saturdays", {}))
            n_empty = len(d.saturdays)
        finally:
            frappe.db.rollback()
        check("BV2-EMPTY-ROW-NO-LONGER-WINS", n_empty == n_clean,
              f"an EMPTY grid row (what the desk's Add Row makes) still yields "
              f"{n_empty} rows, not 1. 🔴 Before 2026-09-02 the guard was "
              f"`if not self.saturdays`, so one blank row suppressed the entire "
              f"pre-fill and the form then claimed HR had confirmed a table "
              f"nobody had seen — measured on MG's real ROSTER-2026-08")

        # ── BV3 — hand-typed junk is removed, not trusted ──────────────────
        try:
            d = _roster(seed=lambda x: x.append(
                "saturdays", {"saturday": "2026-12-11", "agreed": 1}))
            n_junk = len(d.saturdays)
            junk_left = [s for s in d.saturdays if not s.shift_type]
        finally:
            frappe.db.rollback()
        check("BV3-HAND-TYPED-ROW-DROPPED", n_junk == n_clean and not junk_left,
              f"a hand-typed row dated 2026-12-11 — wrong month AND a Friday — is "
              f"gone, and the table is back to {n_junk} generated rows. The table "
              f"is a CONFIRMATION, not an entry: rebuilding it is what makes "
              f"'what HR ticks' and 'what the system will do' the same thing")

        # ── BV4 — but a genuine UNTICK survives the rebuild ────────────────
        # Without this, the rebuild would erase HR's actual answer, which is a
        # worse bug than the one it fixes.
        try:
            first = _roster()
            target = (str(first.saturdays[0].saturday), first.saturdays[0].shift_type)
            frappe.db.rollback()
            d = _roster(seed=lambda x: x.append("saturdays", {
                "saturday": target[0], "shift_type": target[1],
                "generated": "Rest", "agreed": 0}))
            kept = [s for s in d.saturdays
                    if (str(s.saturday), s.shift_type) == target]
            survived = kept and kept[0].agreed == 0
            others = sum(1 for s in d.saturdays if s.agreed)
        finally:
            frappe.db.rollback()
        check("BV4-UNTICK-SURVIVES", bool(survived) and others == n_clean - 1,
              f"HR unticking {target[0]} {target[1]} survives the rebuild "
              f"({others} of {n_clean} still ticked). 🔴 This is the assertion that "
              f"keeps the fix from being worse than the defect — a rebuild that "
              f"silently re-ticked every row would turn HR's 'this one is wrong' "
              f"back into 'I agree'")

        # ── BV5 — a holiday outside the month ──────────────────────────────
        hit, msg = _refused(
            lambda: _roster(holidays=[("ZZ probe", "2026-12-09", "Wednesday")]))
        frappe.db.rollback()
        check("BV5-HOLIDAY-OUT-OF-MONTH", hit and "not in" in msg,
              f"a holiday dated 2026-12-09 on the November form is refused. "
              f"⚠️ The day-of-week checksum could NOT catch MG's case: 9 September "
              f"2026 really is a Wednesday, so the two fields agreed with each "
              f"other while both disagreed with the form they were on. It is not "
              f"cosmetic — on_submit appends the row to that year's holiday list "
              f"and regenerates the alternate-Saturday calendars")

        # ── BV6 — and the control, so BV5 cannot pass by refusing everything ─
        hit, _m = _refused(
            lambda: _roster(holidays=[("ZZ probe", "2026-11-09", "Monday")]))
        frappe.db.rollback()
        check("BV6-HOLIDAY-IN-MONTH-PASSES", not hit,
              "a holiday dated 2026-11-09 on the November form is accepted. "
              "Without this, BV5 would pass against a form that refuses every "
              "holiday ever entered")

        # ── BV7 — the weekday checksum still works ─────────────────────────
        hit, msg = _refused(
            lambda: _roster(holidays=[("ZZ probe", "2026-11-09", "Sunday")]))
        frappe.db.rollback()
        check("BV7-WEEKDAY-CHECKSUM-KEPT", hit and "Monday" in msg,
              "MG's original checksum — the date and the weekday are entered "
              "separately so a typo has something to disagree with — is untouched "
              "by the new guard")

        # ── BV8..BV10 — OT Approval: special_approve is role-gated ─────────
        _ot_special()

        # ── BV11..BV13 — the import date rules, where they actually live ───
        _import_dates()

        # ── BV14 — Ingress Sync Settings port range ────────────────────────
        _port_range()

    finally:
        frappe.set_user("Administrator")
        frappe.db.rollback()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed


def _import_dates():
    """🔴 The import date rules live on `manual_import`, NOT on the doctype.

    The 2026-09-02 survey first reported both of these as missing, because it
    created a bare `Ingress Import Batch` **document** and watched it save. A
    batch document is only the RECORD of a run; nothing imports when you insert
    one. The rules are on the function that does the work — the third time in two
    days that probing the wrong surface produced a false finding.

    ⚠️ These call `manual_import` for real. The two refusals throw before the
    machine is touched, so nothing is created. The positive control deliberately
    does NOT run — a successful import would write Finger Logs — so
    `from_date == to_date` is asserted by the fact that it gets past the date
    checks and fails on the connection instead.
    """
    from caf.caf.ingress import sync

    hrm = _pick("HR Manager")
    if not hrm:
        check("BV11-IMPORT-DATE-ORDER", False, "no HR Manager on this site")
        return

    def attempt(frm, to):
        frappe.set_user(hrm)
        try:
            sync.manual_import(frm, to, purpose="Test")
            return "RAN"
        except Exception as e:
            return f"{type(e).__name__}: {str(e).replace(chr(10), ' ')[:150]}"
        finally:
            frappe.set_user("Administrator")
            frappe.db.rollback()

    today = nowdate()
    v = attempt("2026-06-30", "2026-06-01")
    check("BV11-IMPORT-DATE-ORDER", "is before" in v,
          f"from_date after to_date → {v}. Refused before the machine is "
          f"touched, so no batch is created for an impossible request")

    v = attempt(add_days(today, 5), add_days(today, 9))
    check("BV12-IMPORT-NOT-FUTURE", "still incomplete" in v,
          f"a future range → {v}. FBR43: yesterday is the newest importable work "
          f"date, because today's punches are mid-sentence — somebody has clocked "
          f"in and not out. ⚠️ Refused LOUDLY rather than clamped: a clamp would "
          f"let somebody ask for 1–17 Aug, receive 1–16, and never learn")

    v = attempt(add_days(today, -1), today)
    check("BV13-IMPORT-NOT-TODAY", "still incomplete" in v,
          f"to_date = today → {v}. This is MG's point exactly: Ingress is still "
          f"recording, and `attendance` is only materialised when somebody runs "
          f"the day in Ingress (FBR49) — so even yesterday can be half-written, "
          f"which the batch reports as `unprocessed_dates`")


def _port_range():
    """`port = 0` used to save, and it is worse than inert."""
    before = frappe.db.get_single_value("Ingress Sync Settings", "port")
    outcomes = {}
    for label, value in (("0", 0), ("70000", 70000), ("3306", 3306)):
        try:
            d = frappe.get_doc("Ingress Sync Settings")
            d.port = value
            d.flags.ignore_permissions = True
            d.save()
            outcomes[label] = "accepted"
        except frappe.ValidationError:
            outcomes[label] = "refused"
        finally:
            frappe.db.rollback()
    # rollback does not restore a Single's cached doc; put the value back plainly
    frappe.db.set_single_value("Ingress Sync Settings", "port", before)
    frappe.db.commit()
    frappe.clear_document_cache("Ingress Sync Settings", "Ingress Sync Settings")

    check("BV14-PORT-RANGE",
          outcomes["0"] == "refused" and outcomes["70000"] == "refused"
          and outcomes["3306"] == "accepted"
          and frappe.db.get_single_value("Ingress Sync Settings", "port") == before,
          f"port 0 → {outcomes['0']}, 70000 → {outcomes['70000']}, "
          f"3306 → {outcomes['3306']}; restored to {before}. 🔴 Zero was not "
          f"inert — `get_settings()` reads `int(doc.port or 3306)`, so it "
          f"SILENTLY became 3306 while the settings page showed 0, and the next "
          f"person debugging a connection would read a number the code never "
          f"uses. A wrong port fails as a timeout, which looks exactly like the "
          f"Ingress PC being switched off (FBR48)")


def _pick(role_needed, role_forbidden=()):
    rows = frappe.db.sql(
        """SELECT DISTINCT hr.parent FROM `tabHas Role` hr
           JOIN `tabUser` u ON u.name = hr.parent
           WHERE hr.role = %s AND u.enabled = 1 AND u.name NOT IN ('Administrator','Guest')
           ORDER BY hr.parent""", (role_needed,))
    for (user,) in rows:
        if set(frappe.get_roles(user)).isdisjoint(role_forbidden):
            return user
    return None


def _file_ot(user, kind, target=None):
    """Returns 'DENIED' | 'ALLOWED' | 'ERR:<Type>'. Always rolled back.

    ⚠️ `target` defaults to the FILER'S OWN Employee record, and that is not a
    convenience. 94 of the 98 users carry a `User Permission` allowing only their
    own Employee, `apply_to_all_doctypes = 1` — so naming somebody else in the
    child row raises `PermissionError` at `check_permission("create")` even though
    `frappe.has_permission("OT Approval", "create")` is True. Doctype-level and
    document-level are different questions (quirks #51); a probe that names an
    arbitrary employee measures the User Permission, not the role.
    """
    target = target or frappe.db.get_value("Employee", {"user_id": user}, "name")
    dept = frappe.db.get_value("Employee", target, "department")
    frappe.set_user(user)
    try:
        d = frappe.new_doc("OT Approval")
        d.work_date, d.type, d.reason, d.ot_department = "2026-06-02", kind, "probe", dept
        r = d.append("emp_list", {})
        r.emp_id, r.start_work, r.ot_end, r.ot_duration = target, "08:00:00", "19:00:00", 2.5
        d.insert()
        return "ALLOWED"
    except frappe.PermissionError:
        return "DENIED"
    except Exception as e:
        return f"ERR:{type(e).__name__}"
    finally:
        frappe.set_user("Administrator")
        frappe.db.rollback()


def _pick_ot_employee():
    """A plain Employee whose own shift allows OT — otherwise the 'normal stays
    open' assertion passes because the FIXTURE could not have overtime, which
    proves nothing about the permission model."""
    for r in frappe.db.sql(
        """SELECT e.user_id FROM `tabEmployee` e
           JOIN `tabShift Type` st ON st.name = e.default_shift
           WHERE e.status='Active' AND IFNULL(e.user_id,'')<>'' AND st.caf_allow_ot=1
           ORDER BY e.name""", as_dict=True):
        roles = set(frappe.get_roles(r.user_id))
        if roles.isdisjoint({"HR Manager", "HR User", "System Manager", "Leave Approver"}):
            return r.user_id
    return None


def _ot_special():
    plain = _pick_ot_employee()
    approver = _pick("Leave Approver", {"HR Manager", "HR User", "System Manager"})
    hrm = _pick("HR Manager")
    if not all((plain, approver, hrm)):
        check("BV8-OT-SPECIAL-GATED", False,
              f"could not resolve a user for each role (plain={plain}, "
              f"approver={approver}, hrm={hrm}) — the assertions below would be vacuous")
        return

    v_plain = _file_ot(plain, "special_approve")
    v_appr = _file_ot(approver, "special_approve")
    v_hrm = _file_ot(hrm, "special_approve")
    check("BV8-OT-SPECIAL-GATED",
          v_plain == "DENIED" and v_appr != "DENIED" and v_hrm != "DENIED",
          f"special_approve: Employee={v_plain}  LeaveApprover={v_appr}  "
          f"HRManager={v_hrm}. 🔴 It is the FINAL ARBITER — validate() runs a raw "
          f"UPDATE cancelling every other submitted row for that (employee, date), "
          f"and the Finger Log then takes its figure verbatim with has_overwrite. "
          f"So it overrides an approval WITHOUT cancelling the document holding "
          f"it — and cancel is exactly the permission Employee does not have")

    # 🔴 The other direction, and it is the one that matters most: the new guard
    # must not have narrowed the NORMAL type, which is open by business rule.
    v_norm = _file_ot(plain, "normal")
    check("BV9-OT-NORMAL-STAYS-OPEN", v_norm != "DENIED",
          f"an ordinary Employee filing a NORMAL approval: {v_norm} (not a "
          f"permission refusal). **FBR70 is a business rule, not an oversight** — "
          f"department reps file OT for their area and the reps rotate often, so "
          f"CAF chose a wide create+submit over a role reassigned every rotation. "
          f"The controls are that Employee holds no cancel, no delete and no "
          f"amend, and that `owner` names who filed it")

    perms = {r.role: r for r in frappe.get_all(
        "Custom DocPerm", filters={"parent": "OT Approval"},
        fields=["role", "`create`", "`delete`", "submit", "cancel", "amend"])}
    if not perms:
        perms = {r.role: r for r in frappe.get_all(
            "DocPerm", filters={"parent": "OT Approval"},
            fields=["role", "`create`", "`delete`", "submit", "cancel", "amend"])}
    e = perms.get("Employee") or {}
    check("BV10-OT-EMPLOYEE-CANNOT-UNDO",
          bool(e) and not e.get("cancel") and not e.get("delete") and not e.get("amend"),
          f"the Employee role on OT Approval: create={e.get('create')} "
          f"submit={e.get('submit')} cancel={e.get('cancel')} "
          f"delete={e.get('delete')} amend={e.get('amend')}. **Filing is open; "
          f"UNDOING is not.** That asymmetry is the whole control, so it is worth "
          f"a test of its own — widening cancel or delete here would remove the "
          f"reason the open create is safe")
