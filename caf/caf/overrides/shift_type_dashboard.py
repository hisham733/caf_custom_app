"""Shift Type → Connections.  Chunk 7.5, OD-72, placement (a).

MG asked for a quick way to see *which employee is assigned to which shift_type*.
That question has two forms, and they need two different homes:

    "who is on THIS shift, permanently?"      no date  -> here, the form
    "what shift is Mr A on THIS Saturday,
     and did a document change it?"           a date   -> page/shift_roster

⚠️ hrms already ships a dashboard for Shift Type and it links **Shift Assignment**
but not **Employee** — so the standing population, which is the larger and more
stable answer, was the one you could not see from the shift. That is the whole
change: one extra transaction group.

`Employee.default_shift` is a non-standard fieldname here; without saying so the
link resolves against `shift` and silently returns nothing.
"""

from frappe import _

from hrms.hr.doctype.shift_type.shift_type_dashboard import get_data as stock_data


def get_data(data=None):
    out = stock_data()
    out.setdefault("non_standard_fieldnames", {})["Employee"] = "default_shift"
    out["transactions"] = [
        {"label": _("People"), "items": ["Employee"]},
    ] + list(out.get("transactions") or [])
    return out
