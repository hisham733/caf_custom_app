# Copyright (c) 2026, CAF and contributors
# For license information, please see license.txt

"""Shift Type guards — the rules a shift cannot contradict.

Hooked as `doc_events["Shift Type"]["validate"]`.
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint

from caf.caf.work_hours import PUNCH_EITHER


def validate(doc, method=None):
    guard_single_punch_has_no_ot(doc)
    warn_on_mixed_population(doc)
    fill_shift_family(doc)


def _hhmm(value):
    """`08:30` from whatever a Time field happens to be holding.

    🔴 Frappe hands a `Time` field back as a **`datetime.timedelta`**, not a
    `datetime.time` — `str()` on it gives `'8:30:00'` with **no leading zero**, so
    the obvious `str(t)[:5]` produces `'8:30:'`. Measured 2026-09-01, on the first
    dry run: every one of the 14 shifts got a label like `6:00:-14:30 · 60`.
    A `datetime.time` (what a freshly-typed form value is) *does* stringify as
    `'08:30:00'`, which is why the bug survives casual testing — it depends on
    whether the value came from the database or from the form.
    """
    if value is None:
        return "??:??"
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}"
    text = str(value)
    return text[:5] if len(text) >= 5 and text[2] == ":" else f"{text:0>8}"[:5]


def derive_family(row):
    """The CONTRACTED DAY — `start · end · lunch` — as one label.

    MG + HR, 2026-09-01: *"shift_type not a 'tree' but cheaply group by start +
    end + lunch duration."* Chosen because it is what actually drives the
    arithmetic: `net_minutes()` is exactly `end - start - lunch`. Two shifts in
    one family therefore produce the same contracted hours, so moving somebody
    between them changes the RULES and never the pay basis — which is what makes
    a family a safe unit to reason about, and why each of the four punch-rule
    shifts sits in the same family as the shift its people left.

    Takes a document or a plain row, so the setup script and this hook share one
    definition rather than two that can disagree.
    """
    return "{0}-{1} · {2}".format(
        _hhmm(row.get("start_time")), _hhmm(row.get("end_time")),
        cint(row.get("caf_lunch_minutes")))


def fill_shift_family(doc):
    """Label a family-less shift with its CONTRACTED DAY — `start · end · lunch`.

    MG + HR, 2026-09-01: *"shift_type not a 'tree' but cheaply group by start +
    end + lunch duration."* The family is what drives the arithmetic —
    `net_minutes()` is exactly `end - start - lunch` — so two shifts in one family
    produce the same contracted hours, and moving somebody between them changes
    the rules without touching the pay basis.

    ⚠️ **Only when BLANK.** A stored derivation drifts — that is the objection
    that killed `shift_type.work_hour` (design §8 item 7), and it applies here
    too: change `start_time` later and this label goes stale. It is stored anyway
    because HR must be able to override it with their own wording, and
    overwriting a typed value on every save would make that impossible. So the
    column is a DEFAULT, never an authority: anything that needs the true family
    derives it live from the three fields.
    """
    if doc.get("caf_shift_family"):
        return
    if doc.get("start_time") is None or doc.get("end_time") is None:
        return
    doc.caf_shift_family = derive_family(doc)


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
