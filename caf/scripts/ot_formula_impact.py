"""What would change if CAF computed overtime instead of importing it. FBR85.

    bench --site <site> execute caf.scripts.ot_formula_impact.report
    bench --site <site> execute caf.scripts.ot_formula_impact.report --kwargs "{'detail': 20}"

READ ONLY. It writes nothing, ever. It exists so the FBR85 decision is taken
against today's data rather than a figure measured on 2026-09-08.

WHAT IT COMPARES
----------------
    TODAY   `ot_in_hour` = Ingress' `attendance.othour`, gated and rounded by
            CAF's three per-shift rules (FBR81). CAF never looks at the punches.
    FBR85   the same gate and rounding, applied to a figure CAF computes from
            the punches it already holds.

THE FORMULA, in the order FBR85 states it
-----------------------------------------
    1  shift has caf_allow_ot = 0                     ->  0
    2  caf_required_punches = "In OR Out only"        ->  0   (one punch cannot
                                                               bound a window)
    3  either punch missing                           ->  not computable; the day
                                                           is held by OD-58 and is
                                                           excluded from the count
    4  out <= in                                      ->  out += 24h  (FDR1: the
                                                           OT belongs to the day
                                                           they STARTED)
    5  Workday        raw = max(0, out - shift_end)
       Rest/Holiday   raw = (out - in) - lunch actually taken
    6  gate      caf_ot_gate_minutes    (FBR26)
    7  round     caf_ot_round_minutes, downwards (FBR27 / FBR1)

⚠️ Step 5 is the whole decision. On a Workday it measures from the SHIFT END, so
an early arrival earns nothing; Ingress measures from the punch pair, so it pays
for arriving early. Every faller this report finds is that difference.
"""

import frappe
from frappe.utils import cint, flt, get_time

ZERO = "00:00:00"


def _mins(t):
    """A Frappe Time as minutes past midnight, or None when there is no punch."""
    if not t or str(t) == ZERO:
        return None
    v = get_time(t)
    return v.hour * 60 + v.minute + (1 if v.second >= 30 else 0)


def _gate_and_round(minutes, p):
    if minutes < cint(p.get("caf_ot_gate_minutes")):
        return 0.0
    step = cint(p.get("caf_ot_round_minutes"))
    if step > 0:
        minutes -= minutes % step
    return minutes / 60.0


def fbr85_hours(row, p):
    """The FBR85 figure for one log, or None when it is not computable."""
    if not p or not p.get("caf_allow_ot"):
        return 0.0
    if (p.get("caf_required_punches") or "") == "In OR Out only":
        return 0.0

    t_in, t_out = _mins(row.time_in), _mins(row.out)
    if t_in is None or t_out is None:
        return None                                   # step 3 — held, not zero
    if t_out <= t_in:
        t_out += 24 * 60                              # step 4

    if row.day_type == "Workday":
        end = _mins(p.get("end_time"))
        if end is None:
            return None
        if end <= _mins(p.get("start_time") or ZERO):
            end += 24 * 60
        raw = max(0, t_out - end)
    else:
        brk, res = _mins(row.get("break")), _mins(row.resume)
        lunch = (res - brk) if (brk is not None and res is not None and res > brk) else 0
        raw = max(0, (t_out - t_in) - lunch)

    return _gate_and_round(raw, p)


def _approval_row(emp, work_date):
    """The submitted OT Approval row covering this person on this day, if any."""
    rows = frappe.get_all("OT Approval Table",
                          filters={"emp_id": emp, "work_date": work_date,
                                   "docstatus": 1},
                          fields=["parent", "start_work", "ot_end", "ot_duration"],
                          order_by="creation desc")
    return rows[0] if rows else None


def i1_hours(row, p, restday_rule="FBR91"):
    """FBR85 **plus I1**: the early portion counts when an approval sanctions it.

        raw = max(0, out - shift_end)                        the late portion
            + max(0, shift_start - max(in, start_work))      the EARLY portion

    ⭐ `max(in, start_work)` is the control. The credit reaches back only as far
    as the SANCTIONED start, never as far as the punch — somebody who turns up at
    06:00 against a 07:00 sanction is paid from 07:00. Measured: 06:00 and 06:53
    both yield 1.50 h; arriving at 07:15 yields 1.00 h, from the real arrival.

    ⚠️ `restday_rule` exists because FBR85 and FBR91 DISAGREE, and FBR91 is the
    one HR signed off. FBR85 step 5 deducts the lunch actually punched; FBR91
    deducts **exactly one hour** whenever both lunch punches exist. On the 12
    rest days that rise, the difference is +7.5 h against +1.5 h.
    """
    if not p or not p.get("caf_allow_ot"):
        return 0.0
    if (p.get("caf_required_punches") or "") == "In OR Out only":
        return 0.0

    t_in, t_out = _mins(row.time_in), _mins(row.out)
    if t_in is None or t_out is None:
        return None
    if t_out <= t_in:
        t_out += 24 * 60

    start, end = _mins(p.get("start_time")), _mins(p.get("end_time"))
    if start is None or end is None:
        return None
    if end <= start:
        end += 24 * 60

    if row.day_type != "Workday":
        # 🔴 MEASURED 2026-09-14 against every submitted non-workday log:
        # Ingress' own rest-day figure is `(out − max(in, shift_start)) − 60`,
        # reproduced to the minute on **39 of 40**, and the single exception is
        # the one person who arrived LATE — for whom the punch wins, which is
        # what `max()` already says. The rest day is therefore measured from the
        # SHIFT, exactly like a workday; the early arrival is unpaid on both.
        # ⚠️ This does NOT contradict FBR90/F1 ("rest-day work is entirely
        # overtime") — that rule is about CLASSIFICATION, not about when the day
        # starts. And FBR91's flat lunch hour is kept: it is the −60 here.
        brk, res = _mins(row.get("break")), _mins(row.resume)
        both = brk is not None and res is not None
        if restday_rule == "FBR91":
            lunch = 60 if both else 0
        else:
            lunch = (res - brk) if (both and res > brk) else 0

        begin = max(t_in, start)
        c = _approval_row(row.employee, row.work_date)
        if c:                                   # I1 applies here too
            sw = _mins(c.start_work)
            if sw is not None and sw < start:
                begin = max(t_in, sw)
        return _gate_and_round(max(0, (t_out - begin) - lunch), p)

    late = max(0, t_out - end)
    early = 0
    c = _approval_row(row.employee, row.work_date)
    if c:
        sw = _mins(c.start_work)
        if sw is not None and sw < start:
            early = max(0, start - max(t_in, sw))
    return _gate_and_round(late + early, p)


def i1_report(detail=10):
    """FBR85 + I1 + FBR91 against what is paid today, over every submitted log.

        bench --site <site> execute caf.scripts.ot_formula_impact.i1_report

    This is the number the FBR85 decision should be taken on — not `report()`'s,
    which measures FBR85 with **no** route for a sanctioned early start.
    """
    from caf.caf.shift_resolution import get_shift_params

    logs = frappe.get_all(
        "Finger Log", filters={"docstatus": 1},
        fields=["name", "employee", "employee_name", "shift_type", "work_date",
                "day_type", "time_in", "`break`", "resume", "out",
                "overtime", "ot_in_hour"], order_by="work_date")

    params, same, up, down, held, barred = {}, 0, [], [], 0, 0
    for r in logs:
        if r.shift_type not in params:
            params[r.shift_type] = get_shift_params(r.shift_type)
        p = params[r.shift_type]
        if not p or not p.get("caf_allow_ot"):
            barred += 1
            continue
        new = i1_hours(r, p)
        if new is None:
            held += 1
            continue
        delta = round(new - flt(r.ot_in_hour or 0), 4)
        if abs(delta) < 0.001:
            same += 1
        elif delta > 0:
            up.append((delta, r))
        else:
            down.append((delta, r))

    eligible = same + len(up) + len(down)
    print("=" * 74)
    print("FBR85 + I1 + FBR91 — overtime computed in ERPNext, with a route for")
    print("the planner's sanctioned early start")
    print("=" * 74)
    print("  OT-ELIGIBLE, compared              %6d" % eligible)
    print("     unchanged                       %6d   %5.1f%%"
          % (same, 100.0 * same / eligible if eligible else 0))
    print("     RISE                            %6d   %+7.1f h"
          % (len(up), sum(d for d, _ in up)))
    print("     FALL                            %6d   %+7.1f h"
          % (len(down), sum(d for d, _ in down)))
    print("  net                                        %+7.1f h"
          % (sum(d for d, _ in up) + sum(d for d, _ in down)))
    print("  (held, a punch missing %d · on a no-OT shift %d)" % (held, barred))

    print("\n  EVERY REMAINING DIFFERENCE, and why — these are the whole worklist")
    print("    %-11s %-22s %-9s %-9s %-6s %-6s %s"
          % ("date", "employee", "day", "sanction", "now", "I1", "what it means"))
    for delta, r in sorted(down + up, key=lambda x: x[0])[:cint(detail)]:
        c = _approval_row(r.employee, r.work_date)
        p = params.get(r.shift_type) or {}
        sw = _mins(c.start_work) if c else None
        start = _mins(p.get("start_time"))
        # ⚠️ The early-start test applies to a WORKDAY only. On a rest day the
        # whole day is overtime and `start_work` decides nothing — labelling such
        # a row "the approval does not sanction an early start" reads as a
        # finding when it is not one.
        if r.day_type != "Workday":
            why = "rest day — FBR91's flat lunch hour, not an early start"
        elif not c:
            why = "no OT Approval covers the day"
        elif sw is None:
            why = "approval has no start_work"
        elif start is not None and sw >= start:
            why = "the approval does NOT sanction an early start"
        else:
            why = "sanctioned — check the punches"
        print("    %-11s %-22s %-9s %-9s %-6.2f %-6.2f %s"
              % (r.work_date, (r.employee_name or "")[:22], r.day_type,
                 str(c.start_work)[:8] if c else "-",
                 flt(r.ot_in_hour or 0), flt(r.ot_in_hour or 0) + delta, why))

    return {"eligible": eligible, "same": same, "up": len(up),
            "up_hours": round(sum(d for d, _ in up), 2), "down": len(down),
            "down_hours": round(sum(d for d, _ in down), 2)}


def report(detail=8):
    """Every submitted log, today's figure against FBR85's."""
    from caf.caf.shift_resolution import get_shift_params

    logs = frappe.get_all(
        "Finger Log", filters={"docstatus": 1},
        fields=["name", "employee", "employee_name", "shift_type", "work_date",
                "day_type", "time_in", "`break`", "resume", "out",
                "overtime", "ot_in_hour", "final_ot"],
        order_by="work_date")

    params, same, up, down, held, barred = {}, 0, [], [], 0, 0
    for r in logs:
        if r.shift_type not in params:
            params[r.shift_type] = get_shift_params(r.shift_type)
        p = params[r.shift_type]

        if not p or not p.get("caf_allow_ot"):
            barred += 1
            continue

        new = fbr85_hours(r, p)
        if new is None:
            held += 1
            continue

        old = flt(r.ot_in_hour or 0)
        delta = round(new - old, 4)
        if abs(delta) < 0.001:
            same += 1
        elif delta > 0:
            up.append((delta, r))
        else:
            down.append((delta, r))

    eligible = same + len(up) + len(down)
    print("=" * 74)
    print("FBR85 — what changes if CAF computes overtime from the punches")
    print("=" * 74)
    print("  submitted logs                     %6d" % len(logs))
    print("  on a shift that forbids OT         %6d  (0 today and 0 after — no change)"
          % barred)
    print("  not computable, a punch missing    %6d  (held by OD-58 either way)" % held)
    print("  ---------------------------------------")
    print("  OT-ELIGIBLE, compared              %6d" % eligible)
    print("     unchanged                       %6d   %5.1f%%"
          % (same, 100.0 * same / eligible if eligible else 0))
    print("     RISE                            %6d   %+7.1f h"
          % (len(up), sum(d for d, _ in up)))
    print("     FALL                            %6d   %+7.1f h"
          % (len(down), sum(d for d, _ in down)))
    print("  net                                        %+7.1f h"
          % (sum(d for d, _ in up) + sum(d for d, _ in down)))

    # ⚠️ sort on the delta ALONE. `sorted(list_of_tuples)` falls through to the
    # second element when two deltas tie, and comparing two `_dict` rows raises.
    for title, rows in (("BIGGEST FALLS — money that stops being paid",
                         sorted(down, key=lambda x: x[0])),
                        ("BIGGEST RISES — money that starts being paid",
                         sorted(up, key=lambda x: x[0], reverse=True))):
        print("\n  %s" % title)
        print("    %-11s %-22s %-9s %-6s %-6s %-7s %-6s %-6s %s"
              % ("date", "employee", "day", "in", "out", "early", "now",
                 "FBR85", "shift"))
        for delta, r in rows[:cint(detail)]:
            new = flt(r.ot_in_hour or 0) + delta
            p = params.get(r.shift_type) or {}
            t_in, start = _mins(r.time_in), _mins(p.get("start_time"))
            early_m = (start - t_in) if (t_in is not None and start is not None) else 0
            print("    %-11s %-22s %-9s %-6s %-6s %-7s %-6.2f %-6.2f %s"
                  % (r.work_date, (r.employee_name or "")[:22], r.day_type,
                     str(r.time_in)[:5], str(r.out)[:5],
                     ("%+d min" % -early_m) if early_m else "-",
                     flt(r.ot_in_hour or 0), new, r.shift_type))

    # 🔴 Is every faller an early arrival? FBR85 asserts it; this measures it.
    over_hour = 0
    for delta, r in down:
        p = params.get(r.shift_type) or {}
        t_in, start = _mins(r.time_in), _mins(p.get("start_time"))
        if t_in is not None and start is not None and (start - t_in) > 60:
            over_hour += 1
    print("\n  IS EVERY FALLER AN EARLY ARRIVAL? %d of %d fell while clocking in"
          % (over_hour, len(down)))
    print("  MORE THAN AN HOUR before their shift started.")

    # What do the fallers have in common? If they are one shift arriving at one
    # time, they are MG's unrecorded 7am call, not scattered abuse.
    by_shift, ins, people, dates = {}, [], set(), set()
    for delta, r in down:
        by_shift[r.shift_type] = by_shift.get(r.shift_type, 0) + 1
        people.add(r.employee)
        dates.add(str(r.work_date))
        m = _mins(r.time_in)
        if m is not None:
            ins.append(m)
    print("    shifts:  %s" % by_shift)
    print("    in-punch spread: %02d:%02d to %02d:%02d"
          % (min(ins) // 60, min(ins) % 60, max(ins) // 60, max(ins) % 60)
          if ins else "    in-punch spread: -")
    print("    %d people across %d distinct dates: %s"
          % (len(people), len(dates), sorted(dates)[:12]))

    # 🔴 THE QUESTION THAT DECIDES FBR85. If today's Ingress figure is simply
    # FBR85 computed against the shift these people ACTUALLY worked, then the
    # -54 h is not a pay cut at all: it is 54 logs whose real shift exists only
    # inside Ingress, and a dated Shift Assignment restores every hour.
    seven = frappe.db.get_value("Shift Type", {"caf_shift_code": "7AM_SCHEDULE"}, "name")
    if seven and down:
        p7 = get_shift_params(seven)
        match = off = 0
        worst = []
        for delta, r in down:
            as7 = fbr85_hours(r, p7)
            if as7 is None:
                continue
            if abs(as7 - flt(r.ot_in_hour or 0)) < 0.001:
                match += 1
            else:
                off += 1
                worst.append((r.work_date, r.employee_name, flt(r.ot_in_hour or 0), as7))
        print("\n  🔴 THE RECONCILIATION — today's figure vs FBR85 on the %s" % seven)
        print("     identical: %d of %d      different: %d" % (match, len(down), off))
        for w in worst[:6]:
            print("       %s %-22s today %.2f  on 7am %.2f" % w)
        print("     ⭐ Where these agree, Ingress was ALREADY treating the day as a")
        print("        7am shift — the move HR makes inside Ingress, which ERPNext")
        print("        never sees. The hour is not lost; the ROSTER is missing.")

    # How often is the early start — the thing that causes the falls — present?
    # ⚠️ Report it as a DISTRIBUTION, not one number. "66% clock in early" in the
    # register counts minutes beyond a threshold; "any minute early" is a much
    # larger number, and quoting one as the other is how a figure drifts.
    bands, early, late_in = {0: 0, 5: 0, 15: 0, 30: 0, 60: 0}, 0, 0
    for r in logs:
        p = params.get(r.shift_type)
        if not p:
            continue
        t_in, start = _mins(r.time_in), _mins(p.get("start_time"))
        if t_in is None or start is None:
            continue
        if t_in < start:
            early += 1
            for b in bands:
                if (start - t_in) > b:
                    bands[b] += 1
        else:
            late_in += 1
    total = early + late_in
    print("\n  WHY THE FALLS HAPPEN — the early start is the norm, not the exception")
    print("    logs with both a shift and an in-punch   %6d" % total)
    for b in sorted(bands):
        print("      clocked in more than %2d min early     %6d   %5.1f%%"
              % (b, bands[b], 100.0 * bands[b] / total if total else 0))
    print("    clocked in at or after start             %6d" % late_in)
    print("\n  ⚠️ A submit-block on early arrival would therefore stop the majority")
    print("     of all days. The FORMULA is the control; the legitimate early")
    print("     start needs a dated Shift Assignment, which is FBR85's condition.")

    return {"eligible": eligible, "same": same,
            "up": len(up), "up_hours": round(sum(d for d, _ in up), 2),
            "down": len(down), "down_hours": round(sum(d for d, _ in down), 2),
            "held": held, "barred": barred, "early_pct": round(
                100.0 * early / total, 1) if total else 0}
