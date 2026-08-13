"""The monthly roster confirmation. OD-71 (a) and (b), MG's design.

Purpose : HR states, BEFORE the month begins, that next month's calendar is
          right — the forward half of OD-71, whose detector can only look back.
Doctype : Monthly Roster Confirmation (submittable, one per month, amendable)
Children: Monthly Roster Holiday · Monthly Roster Saturday
Fires   : on_submit appends to `CAF Public Holidays <year>`, which triggers
          `holiday_lists.on_public_holidays_changed` (OD-74) and regenerates the
          alternate-Saturday calendars.
Gate    : `require_confirmed_month` is hooked to `Finger Log.before_submit` and
          is OFF until `HR Settings.caf_roster_gate_from` is set.
Refs    : framework §6.12 (OD-71) · §6.13a (the walk, measured) · OD-74 ·
          roadmap §9d · test plan ROSTER-*
Changelog
---------
1.0  2026-08-13  Initial — OD-71 (a) + (b), with MG's day-of-week checksum

WHAT IT IS FOR
--------------
OD-71's detector is **backward-looking by construction** — it needs punches, so
it can only fire the Monday *after* a holiday nobody recorded. This is the
forward half: HR states, before the month begins, that the calendar is right.

TWO HALVES, ONE FORM — MG's decision. They are two answers to one question
("*is next month's calendar right?*"), and splitting them means HR can do one and
not the other:

    (a) any new public or company holidays?   -> appended to CAF Public Holidays
                                                 on submit, which regenerates the
                                                 alternate-Saturday calendars
                                                 (OD-74)
    (b) is the alternate-Saturday roster right? -> CONFIRMED, never re-entered

🔴 (b) IS A CONFIRMATION AND NOT AN ENTRY, and that is deliberate. MG asked for
"a monthly to-do for HR Manager to set workday/restday manually, same as the
policy at Ingress". The evidence says the manual step is where the errors came
from — February's unrecorded holiday and its four mislabelled day types were both
hand-entry — and the generated calendar already matches practice 17/18 and 16/18
from the anchor. So the rows are read-only and pre-filled, and HR ticks.

⚠️ The Saturday table is NOT a second rendering of the roster screen. It is the
record that somebody looked. MG: *"but don't you already have a dashboard that
shows this?"* — yes, `page/shift-roster`, and this links to it.

THE DAY-OF-WEEK CHECKSUM — MG, 2026-08-13
------------------------------------------
HR enters the holiday's **name**, its **date** and its **day** independently, and
`validate` refuses to save if the day does not match the date. *"You never know."*
The same shape as `work + short = net`: a value that can be derived is asked for
anyway, so that a typo has something to disagree with. A holiday keyed a day out
is precisely the error that inverts every Saturday after it.
"""

import calendar
from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, get_first_day, get_last_day, getdate

from caf.caf.holiday_lists import PH_LIST
from caf.caf.shift_resolution import RESTDAY, resolve_day_type

DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class MonthlyRosterConfirmation(Document):
    def autoname(self):
        d = getdate(self.month_start)
        self.name = f"ROSTER-{d.year}-{d.month:02d}"

    def validate(self):
        d = get_first_day(getdate(self.month_start))
        self.month_start = d
        self.month_label = d.strftime("%B %Y")

        self.check_day_matches_date()
        self.check_answer_is_consistent()
        if not self.saturdays:
            self.fill_saturdays()

    def check_day_matches_date(self):
        """🔴 MG's checksum. The date and the weekday are entered separately so
        that a typo has something to disagree with."""
        for row in self.holidays or []:
            if not row.holiday_date or not row.day_of_week:
                continue
            actual = DOW[getdate(row.holiday_date).weekday()]
            if actual != row.day_of_week:
                frappe.throw(
                    _("Row {0}: <b>{1}</b> is dated {2}, which is a <b>{3}</b> — "
                      "not a {4}. One of the two is a typo, and a holiday keyed a "
                      "day out moves every alternate Saturday after it.").format(
                          row.idx, row.holiday_name, row.holiday_date,
                          actual, row.day_of_week),
                    title=_("The date and the day disagree"))

            row.already_in_list = 1 if frappe.db.exists("Holiday", {
                "parent": PH_LIST.format(year=getdate(row.holiday_date).year),
                "holiday_date": getdate(row.holiday_date)}) else 0

    def check_answer_is_consistent(self):
        """"Nothing new" and a list of new things cannot both be true."""
        if self.no_new_holidays and self.holidays:
            frappe.throw(
                _("<b>No new holidays this month</b> is ticked, but {0} are "
                  "listed. Untick it, or clear the table.").format(
                      len(self.holidays)))
        if not self.no_new_holidays and not self.holidays:
            frappe.throw(
                _("Either list the new holidays, or tick <b>No new holidays this "
                  "month</b>. An unanswered form is the thing this exists to "
                  "prevent."))

    def fill_saturdays(self):
        """Pre-fill (b) from the GENERATED calendar. Read-only rows — HR ticks."""
        first = getdate(self.month_start)
        last = get_last_day(first)

        alt = frappe.get_all("Shift Type", filters={"caf_alt_sat": 1}, pluck="name")
        if not alt:
            return
        people = frappe.get_all(
            "Employee",
            filters={"default_shift": ("in", alt), "status": "Active"},
            fields=["name", "employee_name", "default_shift"])

        d = first
        while d <= last:
            if d.weekday() == calendar.SATURDAY:
                by_shift = {}
                for e in people:
                    day_type, shift = resolve_day_type(e.name, d)
                    if shift in alt:
                        by_shift.setdefault((shift, day_type), []).append(
                            e.employee_name)
                for (shift, day_type), names in sorted(by_shift.items()):
                    self.append("saturdays", {
                        "saturday": d,
                        "shift_type": shift,
                        "generated": "Rest" if day_type == RESTDAY else "Work",
                        "employees": ", ".join(sorted(names)),
                        "agreed": 1,
                    })
            d = add_days(d, 1)

    def on_submit(self):
        """Append the holidays, which fires OD-74 and regenerates the calendars.

        ⚠️ One save per year touched, not one per holiday — every save
        regenerates, and doing it per row would regenerate N times and report N
        diffs for one decision.
        """
        by_year = {}
        for row in self.holidays or []:
            if row.already_in_list:
                continue
            by_year.setdefault(getdate(row.holiday_date).year, []).append(row)

        for year, rows in sorted(by_year.items()):
            name = PH_LIST.format(year=year)
            if not frappe.db.exists("Holiday List", name):
                frappe.throw(
                    _("{0} does not exist, so {1}'s holidays cannot be recorded. "
                      "Generate that year's lists first — the alternate-Saturday "
                      "walk refuses a year it cannot see (OD-71b).").format(
                          name, year))
            doc = frappe.get_doc("Holiday List", name)
            for row in rows:
                doc.append("holidays", {
                    "holiday_date": getdate(row.holiday_date),
                    "weekly_off": 0,
                    "description": row.holiday_name,
                })
            doc.flags.ignore_permissions = True
            doc.save()                       # -> on_public_holidays_changed
            for row in rows:
                row.db_set("added_to_list", 1, update_modified=False)

    def on_cancel(self):
        """⚠️ Cancelling does NOT remove the holidays it added.

        Regeneration is symmetric (ALT-HOOK-BACK), so removing them would be
        *possible* — but a holiday that was really taken stays true whatever
        happens to the form that recorded it, and silently un-declaring one from
        a cancel would invert every Saturday after it. HR removes it from the
        Holiday List deliberately, where the diff is reported.
        """
        added = [r.holiday_name for r in (self.holidays or []) if r.added_to_list]
        if added:
            frappe.msgprint(
                _("This form is cancelled, but the holidays it recorded are still "
                  "in the Holiday List: <b>{0}</b>. Remove them there if they were "
                  "wrong — the alternate-Saturday calendars will regenerate and "
                  "report what moved.").format(", ".join(added)),
                title=_("The holidays remain"), indicator="orange")


# ── the Finger Log gate ─────────────────────────────────────────────────────
# MG: *"make it costly ... by stopping finger_log from submission (can download
# from ingress + can save but cannot submit)."*
#
# The draft is HR's queue — the same shape as OD-58's Not Full Day. Download and
# save always work; SUBMIT is what waits.
#
# 🔴 OFF UNTIL A DATE IS SET, and that is not timidity. Every imported July row
# and every test fixture predates this form, so a gate with no start date would
# refuse the entire existing dataset and every suite that creates a log. It also
# matches D-NEW-1: pre-implementation data is not governed by the new rules.
# Set `caf_roster_gate_from` on HR Settings at go-live.
GATE_FIELD = "caf_roster_gate_from"


def setup_fields():
    """    bench --site <site> execute caf.caf.doctype.monthly_roster_confirmation
           .monthly_roster_confirmation.setup_fields
    """
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields({
        "HR Settings": [{
            "fieldname": GATE_FIELD,
            "label": "Roster confirmation required from",
            "fieldtype": "Date",
            "insert_after": "hr_settings_section" if frappe.db.exists(
                "DocField", {"parent": "HR Settings",
                             "fieldname": "hr_settings_section"}) else None,
            "description": ("Finger Logs whose work date falls on or after this "
                            "date cannot be submitted until that month's Monthly "
                            "Roster Confirmation is submitted. Leave empty to "
                            "disable the gate — which is correct until go-live, "
                            "because every imported row predates the form."),
        }],
    }, update=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="HR Settings")
    print(f"HR Settings.{GATE_FIELD}: {'ok' if _field_exists() else 'MISSING'}")


def _field_exists():
    """🔴 NOT `frappe.db.has_column()`. `HR Settings` is a **Single** — it has no
    `tabHR Settings`, so `has_column` raises `TableMissingError` rather than
    returning False. Caught here before shipping; the same call inside
    `gate_from()` would have thrown on **every Finger Log submit**."""
    return bool(frappe.get_meta("HR Settings").has_field(GATE_FIELD))


def gate_from():
    """The date the gate starts applying, or None while it is off.

    🔴 FOUND BY THE TESTS, and it is the difference between "off" and "block
    everything". Clearing this field does not always store NULL — writing `None`
    to a Date on a **Single** left a value that `getdate()` read back as
    **`0001-01-01`**. Truthy, in the past, and therefore a gate that refuses
    EVERY Finger Log ever recorded, with a message about a month in year 1.

    So "unset" is tested by MEANING, not by truthiness: anything before 1900 is
    nobody's go-live date.
    """
    if not _field_exists():
        return None
    v = frappe.db.get_single_value("HR Settings", GATE_FIELD)
    if not v or str(v) in ("None", "0000-00-00"):
        return None
    try:
        d = getdate(v)
    except Exception:
        return None
    return d if d and d.year > 1900 else None


def require_confirmed_month(doc, method=None):
    """`Finger Log.before_submit`. Keyed on the WORK DATE's month, never today."""
    start = gate_from()
    if not start or not doc.get("work_date"):
        return
    work_date = getdate(doc.work_date)
    if work_date < start:
        return

    month = get_first_day(work_date)
    name = f"ROSTER-{month.year}-{month.month:02d}"
    # 🔴 KEYED ON `month_start`, NOT ON THE NAME. Corrected 2026-08-13 (OD-81c).
    #
    # The lookup used to be `{"name": name, "docstatus": 1}`. Frappe names an
    # amendment `ROSTER-2026-11-**1**`, so once HR corrected a month by the
    # sanctioned cancel-and-amend route, the exact-name match could never find
    # the replacement again and **attendance for that month was blocked
    # permanently**. Measured across all three states (test AM5): confirmed ➜
    # passes · cancelled ➜ refuses, correctly, that is the amend window ·
    # amended and re-submitted ➜ still refused.
    #
    # The month is the identity; the name is a label. `month_start` survives the
    # amend unchanged, so this finds the replacement and keeps refusing while
    # only a cancelled original exists.
    if frappe.db.exists("Monthly Roster Confirmation",
                        {"month_start": month, "docstatus": 1}):
        return

    # ⚠️ The message carries the way out. A refusal that only says "blocked" is
    # a support call; one with a link is a click.
    if frappe.db.exists("Monthly Roster Confirmation", name):
        route = f"/app/monthly-roster-confirmation/{name}"
        action = _("<a href='{0}'>Open {1} and submit it</a>").format(route, name)
    else:
        route = "/app/monthly-roster-confirmation/new"
        action = _("<a href='{0}'>Create the confirmation for {1}</a>").format(
            route, month.strftime("%B %Y"))

    frappe.throw(
        _("<p>The roster for <b>{0}</b> has not been confirmed, so attendance for "
          "that month cannot be submitted yet.</p><p>{1}</p>").format(
              month.strftime("%B %Y"), action),
        title=_("Month not confirmed"))
