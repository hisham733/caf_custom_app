"""A half-configured alternating pair must not be saveable — design §5.

    bench --site <site> execute caf.tests.fingerlog.test_alt_pair_guard.run

**What §5 actually needed, once it was measured.** The proposal asked for a
`caf_mirror_shift` link so the swap would read data instead of parsing shift
names. Measured 2026-09-01: `caf_sat_mirror` already exists, is populated and
mutual on both live pairs, and **every** consumer already reads it —
`shift_swap.mirror_of()`, `shift_roster.alt_shifts()`, `holiday_lists`, and
`Monthly Roster Confirmation`. Nothing parses a name. So the link half of §5 was
already built; the enforcement half was not.

Each assertion below is a way a pair could be broken through the form, and each
one fails **silently** in production — the shift simply stops alternating, or
starts paying a different day, with no error anywhere.

Self-cleaning: builds its own throwaway shifts, removes them in `finally`.
"""

import frappe
from frappe.utils import strip_html

RESULTS = []
PREFIX = "ZZ Test Alt Pair"
ANCHOR = "2026-04-11"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:26s} {'PASS' if ok else 'FAIL'}  {detail}")


def _shift(suffix, **over):
    name = f"{PREFIX} — {suffix}"
    if frappe.db.exists("Shift Type", name):
        frappe.delete_doc("Shift Type", name, force=True, ignore_permissions=True)
    d = frappe.new_doc("Shift Type")
    d.__newname = name
    d.start_time = "08:30:00"
    d.end_time = "17:30:00"
    d.caf_lunch_minutes = 60
    for f in ("caf_work_mon", "caf_work_tue", "caf_work_wed", "caf_work_thu",
              "caf_work_fri", "caf_work_sat"):
        setattr(d, f, 1)
    for k, v in over.items():
        setattr(d, k, v)
    d.flags.ignore_permissions = True
    d.insert(ignore_permissions=True)
    return d


def _seed_alt(name, anchor, mirror=None, end_time=None):
    """Make a shift alternating WITHOUT going through validate.

    🔴 Necessary, and the reason is the guard working: an alternating shift with
    no mirror is exactly what `guard_alt_sat_pairing` refuses, so these fixtures
    cannot be built through `insert()`/`save()`. `db.set_value` is the same door
    `alt_saturday_setup.py` uses to seed the live pairs, and using it here keeps
    the fixture honest — it represents a row that reached the database before the
    guard existed, which is precisely the state the guard has to cope with.
    """
    frappe.db.set_value("Shift Type", name, "caf_alt_sat", 1, update_modified=False)
    frappe.db.set_value("Shift Type", name, "caf_sat_anchor_date", anchor,
                        update_modified=False)
    frappe.db.set_value("Shift Type", name, "caf_sat_anchor", "Rest",
                        update_modified=False)
    if mirror is not None:
        frappe.db.set_value("Shift Type", name, "caf_sat_mirror", mirror,
                            update_modified=False)
    if end_time:
        frappe.db.set_value("Shift Type", name, "end_time", end_time,
                            update_modified=False)


def _refuses(doc, fragment):
    """Save `doc` and report whether it was refused for the expected reason."""
    try:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        return False, "SAVED — not refused"
    except Exception as e:
        msg = strip_html(str(e))
        return (fragment.lower() in msg.lower()), msg[:150]


def run():
    frappe.set_user("Administrator")
    made = []
    try:
        a = _shift("A"); made.append(a.name)
        b = _shift("B"); made.append(b.name)

        # ── AP1 — alternating with nothing to alternate with ───────────────
        a.caf_alt_sat = 1
        ok, msg = _refuses(a, "needs")
        check("AP1-NEEDS-ALL-THREE", ok,
              f"ticking 'Alternate Saturdays' alone is refused, naming what is "
              f"missing — {msg!r}. A blank anchor makes the calendar generator "
              f"skip the alternation entirely, so the PAIR COLLAPSES INTO ONE "
              f"list and nobody alternates — with no error anywhere")

        # ── AP2 — its own mirror ───────────────────────────────────────────
        a.reload(); a.caf_alt_sat = 1
        a.caf_sat_mirror = a.name
        a.caf_sat_anchor_date = ANCHOR
        a.caf_sat_anchor = "Work"
        ok, msg = _refuses(a, "cannot be its own mirror")
        check("AP2-NOT-SELF", ok, f"a shift may not mirror itself — {msg!r}")

        # ── AP3 — the partner does not alternate ───────────────────────────
        a.reload(); a.caf_alt_sat = 1
        a.caf_sat_mirror = b.name          # b has caf_alt_sat = 0
        a.caf_sat_anchor_date = ANCHOR
        a.caf_sat_anchor = "Work"
        ok, msg = _refuses(a, "not marked as an alternating shift")
        check("AP3-PARTNER-MUST-ALTERNATE", ok,
              f"naming a NON-alternating shift as the mirror is refused — {msg!r}. "
              f"Otherwise the swap works one way and not the other")

        # ── AP4 — 🔴 the money rule: mirrors must contract the same day ────
        c = _shift("C-different-hours", end_time="18:30:00"); made.append(c.name)
        _seed_alt(c.name, ANCHOR)
        a.reload(); a.caf_alt_sat = 1
        a.caf_sat_mirror = c.name
        a.caf_sat_anchor_date = ANCHOR
        a.caf_sat_anchor = "Work"
        ok, msg = _refuses(a, "same day")
        check("AP4-SAME-CONTRACTED-DAY", ok,
              f"mirrors running different hours are refused — {msg!r}. A swap "
              f"moves somebody from one half to the other for the day, so "
              f"mismatched start/end/lunch silently changes what their day is "
              f"worth. Nobody decides that, and nothing reports it (FBR53)")

        # ── AP5 — both sides Rest is not an alternation ────────────────────
        frappe.db.set_value("Shift Type", b.name, "caf_alt_sat", 1)
        frappe.db.set_value("Shift Type", b.name, "caf_sat_anchor_date", ANCHOR)
        frappe.db.set_value("Shift Type", b.name, "caf_sat_anchor", "Work")
        a.reload(); a.caf_alt_sat = 1
        a.caf_sat_mirror = b.name
        a.caf_sat_anchor_date = ANCHOR
        a.caf_sat_anchor = "Work"          # same side as B
        ok, msg = _refuses(a, "do not alternate")
        check("AP5-MUST-BE-OPPOSITE", ok,
              f"both halves starting on the SAME side is refused — {msg!r}. They "
              f"would rest and work in step, so nobody ever covers — and that "
              f"reads as a roster mistake rather than a configuration one")

        # ── AP6 — ✅ a correct pair saves, and completes itself ────────────
        frappe.db.set_value("Shift Type", b.name, "caf_sat_anchor", "Rest")
        frappe.db.set_value("Shift Type", b.name, "caf_sat_mirror", None)
        a.reload(); a.caf_alt_sat = 1
        a.caf_sat_mirror = b.name
        a.caf_sat_anchor_date = ANCHOR
        a.caf_sat_anchor = "Work"
        a.flags.ignore_permissions = True
        a.save(ignore_permissions=True)
        back = frappe.db.get_value("Shift Type", b.name, "caf_sat_mirror")
        check("AP6-COMPLETES-THE-PAIR", back == a.name,
              f"a valid pair saves, and {b.name} was given {back!r} back "
              f"automatically. HR configures a pair one shift at a time, so "
              f"between the two saves it is one-directional — and if they stop "
              f"there the swap works from one side only")

        # ── AP7 — a third shift cannot steal a partner ─────────────────────
        d = _shift("D"); made.append(d.name)
        _seed_alt(d.name, ANCHOR)
        d.reload(); d.caf_alt_sat = 1
        d.caf_sat_mirror = b.name          # b is already paired with a
        d.caf_sat_anchor_date = ANCHOR
        d.caf_sat_anchor = "Rest"
        ok, msg = _refuses(d, "already the mirror of")
        check("AP7-NO-THREESOME", ok,
              f"claiming an already-paired shift is refused, naming the current "
              f"partner — {msg!r}. Silently re-pointing would leave A naming B "
              f"while B names D: an asymmetry the audit reports but nothing stops")

        # ── AP8 — the live pairs still satisfy every rule ──────────────────
        live = frappe.get_all("Shift Type", filters={"caf_alt_sat": 1},
                              fields=["name", "caf_sat_mirror", "caf_sat_anchor",
                                      "caf_sat_anchor_date", "start_time",
                                      "end_time", "caf_lunch_minutes"])
        live = [s for s in live if not s.name.startswith(PREFIX)]
        bad = []
        for s in live:
            o = next((x for x in live if x.name == s.caf_sat_mirror), None)
            if not o:
                bad.append(f"{s.name} mirror missing")
                continue
            if o.caf_sat_mirror != s.name:
                bad.append(f"{s.name} not mutual")
            if s.caf_sat_anchor == o.caf_sat_anchor:
                bad.append(f"{s.name} same side as its mirror")
            if str(s.caf_sat_anchor_date) != str(o.caf_sat_anchor_date):
                bad.append(f"{s.name} anchor date differs")
            if any(str(s[f]) != str(o[f]) for f in
                   ("start_time", "end_time", "caf_lunch_minutes")):
                bad.append(f"{s.name} contracted day differs from its mirror")
        check("AP8-LIVE-PAIRS-VALID", len(live) > 0 and not bad,
              f"the {len(live)} live alternating shift(s) all satisfy the new "
              f"rules ({bad or 'no problems'}) — the guard describes what the "
              f"site already does, so turning it on refuses nothing that exists")

    finally:
        frappe.set_user("Administrator")
        # Break the links first: a mirror is a Link field, and a referenced doc
        # cannot be deleted while something points at it (quirks #63).
        for s in made:
            if frappe.db.exists("Shift Type", s):
                frappe.db.set_value("Shift Type", s, "caf_sat_mirror", None,
                                    update_modified=False)
        for s in made:
            if frappe.db.exists("Shift Type", s):
                frappe.delete_doc("Shift Type", s, force=True,
                                  ignore_permissions=True)
        frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
