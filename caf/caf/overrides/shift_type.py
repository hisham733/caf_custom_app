# Copyright (c) 2026, CAF and contributors
# For license information, please see license.txt

"""Shift Type guards — the rules a shift cannot contradict.

Hooked as `doc_events["Shift Type"]["validate"]`.
"""

import frappe
from frappe import _

from caf.caf.work_hours import PUNCH_EITHER


def validate(doc, method=None):
    guard_single_punch_has_no_ot(doc)
    warn_on_mixed_population(doc)


def guard_single_punch_has_no_ot(doc):
    """🔴 A shift that credits a day from one punch may not also pay overtime.

    MG's rule, 2026-08-22, and the reasoning is the important part:

    On an "In OR Out only" shift, `caf_work_hours` is set to the full contracted
    day from a SINGLE tap. That is an **assumption**, not a measurement — nobody
    knows when the person left. Overtime is a claim about hours worked BEYOND the
    contracted day, so paying it on top would stack an unverifiable number on an
    unverified one.

    Enforced on the server because the client-side lock is escapable — the API,
    a Data Import and `bench execute` all bypass form scripts, and this is a
    money rule.
    """
    if (doc.get("caf_required_punches") or "").strip() != PUNCH_EITHER:
        return
    if not doc.get("caf_allow_ot"):
        return

    frappe.throw(
        _("<b>{0}</b> credits a full contracted day from a single punch, so it "
          "cannot also allow overtime."
          "<br><br>On this rule nobody knows when the person left — the day's "
          "hours are assumed, not measured. Overtime would be an unverifiable "
          "figure on top of an unverified one."
          "<br><br>Either untick <b>Allow Overtime</b>, or choose a punch rule "
          "that records when the day ended.").format(doc.name),
        title=_("Overtime needs a measured day"))


def warn_on_mixed_population(doc):
    """A per-shift rule is only honest if everyone on the shift shares it.

    MG's design rule, 2026-08-22: *an employee follows every parameter of the
    shift they are assigned to.* That makes per-shift punch rules safe — and it
    means a shift must never hold two people who need different treatment.

    A warning, not a refusal: HR legitimately changes a rule BEFORE moving people,
    and refusing would make the intended order of work impossible. It fires only
    when the rule actually changes, so saving an unrelated field stays quiet.
    """
    if doc.is_new() or not doc.has_value_changed("caf_required_punches"):
        return

    n = frappe.db.count("Employee", {"status": "Active", "default_shift": doc.name})
    if n > 1:
        frappe.msgprint(
            _("{0} active employees are on <b>{1}</b>. This punch rule now applies "
              "to <b>all</b> of them — a shift may not hold people who need "
              "different treatment. Move anybody who does onto their own shift."
              ).format(n, doc.name),
            title=_("Check who else is on this shift"), indicator="orange")
