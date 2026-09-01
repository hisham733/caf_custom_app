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
    guard_alt_sat_pairing(doc)
    warn_on_mixed_population(doc)
    fill_shift_family(doc)


def on_update(doc, method=None):
    complete_alt_sat_pairing(doc)


# ------------------------------------------------------- alternating Saturdays

# The three fields that only mean anything together. `caf_alt_sat` alone says
# "this shift alternates" and answers none of: alternates WITH WHAT, from WHEN,
# and starting on WHICH side.
PAIR_FIELDS = (("caf_sat_mirror", "Mirror Shift"),
               ("caf_sat_anchor_date", "Anchor Date"),
               ("caf_sat_anchor", "Anchor"))

# What a mirror pair must share, or a swap silently moves somebody's contracted
# day. `net_minutes()` is `end - start - lunch`, so these three ARE the pay basis
# (FBR53).
SAME_CONTRACTED_DAY = ("start_time", "end_time", "caf_lunch_minutes")


def guard_alt_sat_pairing(doc):
    """🔴 A half-configured alternating pair must not be saveable.

    **Design §5, built 2026-09-01 — and it is the ONLY part of §5 that was still
    missing.** The proposal asked for a `caf_mirror_shift` link so the swap code
    would read data instead of inferring from the shift name. Measured first, and
    the field already exists (`caf_sat_mirror`) and every consumer already reads
    it: `shift_swap.mirror_of()` (the swap itself), `shift_roster.alt_shifts()`,
    `holiday_lists`, and `Monthly Roster Confirmation` all select on
    `caf_alt_sat` / `caf_sat_mirror` and none of them parses a name. So MG's Pass
    C8 message — *"8am Schedule is not an alternating shift, so there is nothing
    to trade"* — was already data-driven and already correct; a NEW pair created
    by HR works the moment the fields are filled.

    What was missing is that nothing **enforced** the fields being filled
    correctly. `readiness_audit.check_alt_pairs` reports a broken pair, but only
    when somebody runs the audit — so a half-configured pair can sit there,
    and its failure mode is silent:

      mirror blank        the swap dialog refuses every trade on that shift, with
                          a message that says the shift does not alternate — which
                          is indistinguishable from an ordinary non-alternating one
      anchor blank        `generate_holiday_lists` skips the shift's alternation
                          entirely (it keys on anchor_date + anchor), so the pair
                          collapses into ONE calendar and nobody alternates at all
      anchors the same    both halves rest on the same Saturdays. Nobody covers,
                          and it reads as a roster mistake rather than a config one
      different hours     🔴 a swap moves somebody between the two, so mismatched
                          start/end/lunch silently changes their contracted day —
                          a pay-basis change nobody decided (FBR53)

    Each of those is refused here, at the point where a person can still fix it.
    """
    if not doc.get("caf_alt_sat"):
        return

    missing = [label for field, label in PAIR_FIELDS if not doc.get(field)]
    if missing:
        frappe.throw(
            _("An alternating-Saturday shift needs {0}."
              "<br><br><b>Alternating</b> means two shifts trade Saturdays with "
              "each other, so the shift has to say <i>which</i> shift, from "
              "<i>which Saturday</i>, and <i>which side</i> it starts on. Without "
              "all three the calendar generator cannot build the pattern and the "
              "swap dialog will refuse every trade."
              "<br><br>Untick <b>Alternate Saturdays</b> if this shift does not "
              "alternate.").format(frappe.bold(", ".join(missing))),
            title=_("Incomplete alternating pair"))

    mirror = doc.caf_sat_mirror
    if mirror == doc.name:
        frappe.throw(_("A shift cannot be its own mirror. The mirror is the "
                       "<b>other</b> shift it trades Saturdays with."),
                     title=_("Incomplete alternating pair"))

    other = frappe.db.get_value(
        "Shift Type", mirror,
        ["name", "caf_alt_sat", "caf_sat_mirror", "caf_sat_anchor",
         "caf_sat_anchor_date"] + list(SAME_CONTRACTED_DAY), as_dict=True)
    if not other:
        frappe.throw(_("Mirror shift {0} does not exist.").format(frappe.bold(mirror)),
                     title=_("Incomplete alternating pair"))

    if not other.caf_alt_sat:
        frappe.throw(
            _("{0} is not marked as an alternating shift, so it cannot be a "
              "mirror. Tick <b>Alternate Saturdays</b> on it first.")
            .format(frappe.bold(mirror)), title=_("Incomplete alternating pair"))

    # Already spoken for. Silently re-pointing would leave a THIRD shift naming a
    # partner that no longer names it back.
    if other.caf_sat_mirror and other.caf_sat_mirror != doc.name:
        frappe.throw(
            _("{0} is already the mirror of {1}. A pair is exactly two shifts — "
              "clear that link first if you mean to re-pair them.")
            .format(frappe.bold(mirror), frappe.bold(other.caf_sat_mirror)),
            title=_("Incomplete alternating pair"))

    # 🔴 The money rule. A swap moves a person from one half to the other for a
    # day, so the two halves must contract the same day (FBR53).
    differs = [f for f in SAME_CONTRACTED_DAY
               if str(doc.get(f)) != str(other.get(f))]
    if differs:
        frappe.throw(
            _("{0} and {1} must contract the SAME day to be mirrors — they differ "
              "on {2}."
              "<br><br>A Saturday swap moves somebody from one to the other for "
              "the day. If the two run different hours or lunch, the swap quietly "
              "changes what that person's day is worth, and nobody decided that.")
            .format(frappe.bold(doc.name), frappe.bold(mirror),
                    frappe.bold(", ".join(differs))),
            title=_("Mirrors must contract the same day"))

    # The two must start on OPPOSITE sides of the same Saturday, or they do not
    # alternate against each other — they alternate in step.
    if str(doc.caf_sat_anchor_date) != str(other.caf_sat_anchor_date):
        frappe.throw(
            _("{0} and {1} must share an <b>Anchor Date</b> — the alternation is "
              "counted from it, so two different dates describe two unrelated "
              "patterns that happen to be linked.")
            .format(frappe.bold(doc.name), frappe.bold(mirror)),
            title=_("Incomplete alternating pair"))

    if doc.caf_sat_anchor == other.caf_sat_anchor:
        frappe.throw(
            _("Both {0} and {1} are set to <b>{2}</b> on {3}, so they do not "
              "alternate against each other — they rest and work in step, and "
              "nobody ever covers."
              "<br><br>One side must be <b>Work</b> and the other <b>Rest</b>.")
            .format(frappe.bold(doc.name), frappe.bold(mirror),
                    doc.caf_sat_anchor, doc.caf_sat_anchor_date),
            title=_("A mirror pair must be opposite"))


def complete_alt_sat_pairing(doc, method=None):
    """Fill in the other half of a new pair, so it is never asymmetric.

    HR configures a pair one shift at a time: A names B, save; B names A, save.
    Between those two saves the pairing is one-directional, and if HR stops there
    — or forgets — the audit reports a broken pair and the swap only works from
    one side.

    So the second half is written automatically, and ONLY when it is blank.
    `validate` has already refused the case where B names somebody else, so the
    only reachable states here are "blank" (fill it) and "already correct"
    (nothing to do). `db.set_value` rather than a save, to avoid recursing back
    into this hook through B's own `on_update`.
    """
    if not doc.get("caf_alt_sat") or not doc.get("caf_sat_mirror"):
        return
    other = frappe.db.get_value("Shift Type", doc.caf_sat_mirror,
                                "caf_sat_mirror")
    if other:
        return
    frappe.db.set_value("Shift Type", doc.caf_sat_mirror, "caf_sat_mirror",
                        doc.name, update_modified=False)
    frappe.msgprint(
        _("{0} now names {1} as its mirror too — a pair has to point both ways "
          "or the swap only works from one side.").format(
              frappe.bold(doc.caf_sat_mirror), frappe.bold(doc.name)),
        title=_("Pair completed"), indicator="green")


def _hhmm(value):
    """`08:30` from whatever a Time field happens to be holding.

    🔴 Every READ path hands a `Time` field back as a **`datetime.timedelta`** —
    `get_value`, `get_doc` and `get_all` alike, because MariaDB `TIME` is a signed
    duration (the same fact that lets it hold 838 h, quirks §17). `str()` on a
    timedelta gives `'8:30:00'` with **no leading zero**, so the obvious
    `str(t)[:5]` produces `'8:30:'`. Measured 2026-09-01 on the first dry run:
    every one of the 14 shifts got a label like `6:00:-14:30 · 60`.

    An **un-persisted** document still holds the plain `str` the client sent —
    Frappe does not cast `Time` on the way in — and that stringifies correctly.
    So the answer depends on whether the value has been through the database, and
    a test that builds its own doc in memory never sees the bug. Measured, not
    assumed: `new_doc` → `str`, every read → `timedelta`, `frappe.utils.get_time`
    → `datetime.time`. All three are handled here.
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
