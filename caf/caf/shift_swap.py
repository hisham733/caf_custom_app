"""Saturday swaps and covers, filed as one action. OD-65 / OD-52 · Chunk 7.3.

    bench --site <site> execute caf.caf.shift_swap.setup_fields

WHAT THIS PREVENTS
------------------
A trade is **two** Shift Assignments, one per employee. Filed by hand, one of them
gets forgotten — and then Mr A works the Saturday while Mr B is still rostered for
it, silently, because nothing links the two documents. This files both, submits
both and links them, or it files neither.

🔴 SWAP AND COVER ARE NOT THE SAME OPERATION, AND THE TOOL SAYS SO
-------------------------------------------------------------------
MG corrected an earlier version of this rule: two employees on the SAME shift is
the normal case, not an error, because HR may put a whole family on one side and
express every trade by moving one person.

    A and B on OPPOSITE mirrors  ->  SWAP   each takes the other's shift for the
                                            date. A works B's rest Saturday AND B
                                            rests A's working one. Reciprocal.

    A and B on the SAME shift    ->  COVER  only one can move. They both rest that
                                            Saturday; moving one to the mirror
                                            makes him WORK it and the other still
                                            rests. One gives up a rest day and
                                            gets nothing back.

**A cover's reciprocal needs a second action on another date.** Calling both
"swap" would let HR believe a debt was settled when it was not, which is the whole
reason the two are named differently in the payload and on screen.

WHAT THE VALIDATION READS
-------------------------
`caf_sat_mirror`, never the shift name. The names carry `1st-3rd` / `2nd-4th`
because MG asked for the Saturdays to be visible, but they are documentation: a
public holiday does not advance the alternation, so after the year's first one the
numbers stop being literally true. A link cannot drift that way.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import getdate

from caf.caf.shift_resolution import get_shift_for_date, resolve_day_type

FIELDS = {
    "Shift Assignment": [
        {
            "fieldname": "caf_swap_section",
            "label": "Swap",
            "fieldtype": "Section Break",
            "insert_after": "status",
            "collapsible": 1,
        },
        {
            "fieldname": "caf_swap_with",
            "label": "Traded With",
            "fieldtype": "Link",
            "options": "Employee",
            "insert_after": "caf_swap_section",
            "read_only": 1,
            "description": (
                "The other person in the trade. Set on BOTH rows of a swap, and on "
                "the single row of a cover."
            ),
        },
        {
            "fieldname": "caf_swap_partner",
            "label": "Paired Assignment",
            "fieldtype": "Link",
            "options": "Shift Assignment",
            "insert_after": "caf_swap_with",
            "read_only": 1,
            "description": (
                "The other half of a swap. Empty on a COVER, which is one row by "
                "nature. A row with `Traded With` set and no partner is either a "
                "cover or a half-done swap — which is exactly what makes the "
                "difference findable by query rather than invisible."
            ),
        },
        {
            "fieldname": "caf_swap_kind",
            "label": "Trade Type",
            "fieldtype": "Select",
            "options": "\nSwap\nCover",
            "insert_after": "caf_swap_partner",
            "read_only": 1,
        },
    ]
}


def setup_fields():
    create_custom_fields(FIELDS, ignore_validate=True)
    frappe.clear_cache(doctype="Shift Assignment")
    frappe.db.commit()
    meta = frappe.get_meta("Shift Assignment")
    for f in FIELDS["Shift Assignment"]:
        ok = "ok  " if meta.get_field(f["fieldname"]) else "🔴 MISSING"
        print(f"    {ok} {f['fieldname']}")


def mirror_of(shift):
    """The other half of the pair, or None. Reads the link, never the name."""
    if not shift:
        return None
    return frappe.db.get_value("Shift Type", shift, "caf_sat_mirror")


def _employee_name(employee):
    return frappe.db.get_value("Employee", employee, "employee_name") or employee


@frappe.whitelist()
def plan(work_date, employee_a, employee_b=None):
    """What WOULD happen, without doing it. Drives the dialog's preview.

    Separated from `create()` so HR sees the consequence before agreeing to it —
    the same reason the cancel dialog names the partner rather than acting.
    """
    frappe.only_for(["HR Manager", "System Manager"])
    work_date = getdate(work_date)

    shift_a = get_shift_for_date(employee_a, work_date)
    if not shift_a:
        frappe.throw(_("{0} has no shift on {1}: no assignment covers the date and no default shift is set.")
                     .format(_employee_name(employee_a), work_date))

    day_a, _s = resolve_day_type(employee_a, work_date)
    out = {
        "work_date": str(work_date),
        "a": {"employee": employee_a, "employee_name": _employee_name(employee_a),
              "shift_now": shift_a, "day_now": day_a},
    }

    if not employee_b:
        # The standalone case MG insisted on: one person following a different
        # shift for a day — an earlier start, OT eligibility, a longer lunch. It is
        # a legitimate document and is NOT validated as a pair.
        out["kind"] = "Single"
        return out

    shift_b = get_shift_for_date(employee_b, work_date)
    if not shift_b:
        frappe.throw(_("{0} has no shift on {1}.").format(_employee_name(employee_b), work_date))
    if employee_a == employee_b:
        frappe.throw(_("A trade needs two different people."))

    day_b, _s = resolve_day_type(employee_b, work_date)
    out["b"] = {"employee": employee_b, "employee_name": _employee_name(employee_b),
                "shift_now": shift_b, "day_now": day_b}

    mirror_a = mirror_of(shift_a)

    if shift_b == mirror_a and mirror_a:
        # Opposite sides of one pair — a true exchange.
        out["kind"] = "Swap"
        out["a"]["shift_new"] = shift_b
        out["b"]["shift_new"] = shift_a
    elif shift_a == shift_b:
        # Same side. Only one can move, and it must be the one who is RESTING —
        # moving the person who is already working changes nothing.
        if not mirror_a:
            frappe.throw(_("{0} is not an alternating shift, so there is nothing to trade. "
                           "File a single assignment instead.").format(shift_a))
        out["kind"] = "Cover"
        out["a"]["shift_new"] = mirror_a
        out["b"]["shift_new"] = None
        out["note"] = _("A cover is one-way: {0} gives up the day and gets nothing back. "
                        "File a second trade on another date to settle it.").format(
                            _employee_name(employee_a))
    else:
        # 🔴 Different families. 8-5 and 8:30am people cannot cover for each other:
        # different times, different rules, and neither shift's mirror is the
        # other's.
        frappe.throw(_("{0} is on {1} and {2} is on {3}. These are different shift families, "
                       "so there is nothing to trade between them.").format(
                           _employee_name(employee_a), shift_a,
                           _employee_name(employee_b), shift_b))

    return out


def _make(employee, work_date, shift, traded_with=None, kind=None):
    doc = frappe.new_doc("Shift Assignment")
    doc.employee = employee
    doc.company = frappe.db.get_value("Employee", employee, "company")
    doc.shift_type = shift
    # 🔴 Both dates, always — MG's guard. `end_date` is `reqd = 0` in stock, and an
    # open-ended assignment would silently own every later date.
    doc.start_date = doc.end_date = work_date
    doc.status = "Active"
    doc.caf_swap_with = traded_with
    doc.caf_swap_kind = kind
    doc.insert()
    doc.submit()
    return doc


@frappe.whitelist()
def create(work_date, employee_a, employee_b=None, shift=None):
    """File the trade. Both rows or neither.

    ⚠️ One transaction. If the second insert fails — an overlapping assignment,
    a validation stock refuses — the first must not survive, or the tool has
    created exactly the half-done state it exists to prevent.
    """
    frappe.only_for(["HR Manager", "System Manager"])
    work_date = getdate(work_date)
    detail = plan(work_date, employee_a, employee_b)

    if detail["kind"] == "Single":
        if not shift:
            frappe.throw(_("Choose the shift {0} should follow on {1}.")
                         .format(_employee_name(employee_a), work_date))
        doc = _make(employee_a, work_date, shift)
        frappe.db.commit()
        return {"kind": "Single", "created": [doc.name], "detail": detail}

    sp = "caf_swap"
    frappe.db.savepoint(sp)
    try:
        a = _make(employee_a, work_date, detail["a"]["shift_new"],
                  traded_with=employee_b, kind=detail["kind"])
        created = [a.name]

        if detail["kind"] == "Swap":
            b = _make(employee_b, work_date, detail["b"]["shift_new"],
                      traded_with=employee_a, kind="Swap")
            created.append(b.name)
            # Both directions. A one-way link is a half-configured pair and it
            # fails in the direction nobody tests.
            frappe.db.set_value("Shift Assignment", a.name, "caf_swap_partner", b.name)
            frappe.db.set_value("Shift Assignment", b.name, "caf_swap_partner", a.name)
    except Exception:
        frappe.db.rollback(save_point=sp)
        raise

    frappe.db.commit()
    return {"kind": detail["kind"], "created": created, "detail": detail}


def unlink_pair(doc, method=None):
    """`before_cancel` — break the pairing so the cancel can proceed.

    🔴 FOUND BY THE TESTS, and it contradicted the decision. `caf_swap_partner` is
    a real Link, and Frappe's link check fires on **cancel**, not only on delete —
    so cancelling one half of a swap raised `LinkExistsError` and MG's chosen
    behaviour ("inform HR, then let them cancel one or both") was **impossible**:
    the pair could only ever be cancelled together, and the message HR would have
    seen names two document IDs and explains nothing.

    Clearing both sides first keeps the Link's integrity where it is useful — a
    LIVE pair cannot lose one half by accident — while letting the deliberate
    break through. The warning is the dialog's job, not the database's.

    ⚠️ Both sides, not one. Leaving the survivor pointing at a cancelled row is
    the half-configured state `half_done_swaps()` exists to find, and creating it
    here would mean the tool manufactured its own alarm.
    """
    partner = doc.get("caf_swap_partner")
    if not partner:
        return
    frappe.db.set_value("Shift Assignment", doc.name, "caf_swap_partner", None,
                        update_modified=False)
    if frappe.db.exists("Shift Assignment", partner):
        frappe.db.set_value("Shift Assignment", partner, "caf_swap_partner", None,
                            update_modified=False)
    doc.caf_swap_partner = None


@frappe.whitelist()
def partner_of(assignment):
    """Is this half of a pair? Drives the cancel dialog.

    MG's decision: inform, then let HR choose — neither auto-cancel nor refuse.
    Auto-cancelling would change another employee's roster from a form that looks
    ordinary; refusing would block a legitimate cancel until HR hunts for the
    other row. Naming it makes the silent half-cancel impossible without taking
    the choice away.
    """
    row = frappe.db.get_value(
        "Shift Assignment", assignment,
        ["caf_swap_partner", "caf_swap_with", "caf_swap_kind", "employee",
         "start_date"], as_dict=True)
    if not row or not row.caf_swap_with:
        return {"paired": False}

    partner = None
    if row.caf_swap_partner:
        partner = frappe.db.get_value(
            "Shift Assignment", row.caf_swap_partner,
            ["name", "employee", "shift_type", "start_date", "docstatus"],
            as_dict=True)
        if partner:
            partner["employee_name"] = _employee_name(partner.employee)

    return {
        "paired": True,
        "kind": row.caf_swap_kind,
        "work_date": str(row.start_date),
        "traded_with": row.caf_swap_with,
        "traded_with_name": _employee_name(row.caf_swap_with),
        "partner": partner,
    }


@frappe.whitelist()
def cancel_both(assignment):
    """Cancel this row and its partner. Only reached when HR chose it."""
    frappe.only_for(["HR Manager", "System Manager"])
    info = partner_of(assignment)
    names = [assignment]
    if info.get("partner") and info["partner"].get("docstatus") == 1:
        names.append(info["partner"]["name"])

    for name in names:
        doc = frappe.get_doc("Shift Assignment", name)
        doc.cancel()
    frappe.db.commit()
    return {"cancelled": names}


@frappe.whitelist()
def half_done_swaps():
    """Every pair that is only half filed — the failure this tool exists to stop.

    Feeds §9d.5's roster overview, and worth having even now: it finds anything
    filed before this tool existed, or a swap whose second row was cancelled
    alone.
    """
    rows = frappe.db.sql("""
        SELECT sa.name, sa.employee, sa.start_date, sa.shift_type,
               sa.caf_swap_with, sa.caf_swap_kind, sa.caf_swap_partner,
               p.docstatus AS partner_docstatus
          FROM `tabShift Assignment` sa
          LEFT JOIN `tabShift Assignment` p ON p.name = sa.caf_swap_partner
         WHERE sa.docstatus = 1
           AND sa.caf_swap_kind = 'Swap'
           AND (sa.caf_swap_partner IS NULL OR sa.caf_swap_partner = ''
                OR p.docstatus != 1)
      ORDER BY sa.start_date DESC
    """, as_dict=True)
    for r in rows:
        r["employee_name"] = _employee_name(r.employee)
    return {"rows": rows, "count": len(rows)}
