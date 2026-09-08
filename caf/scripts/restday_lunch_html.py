"""Rest-day overtime and the lunch deduction — one question for HR. OD-94.

    bench --site <site> execute caf.scripts.restday_lunch_html.write

MG, 2026-09-08/09: *"on a restday, if Mr A comes to work but he only works for 3
hours (less than half a day) and there is no lunch-in and lunch-out punched,
should it be minus the lunch duration stated in shift_type? Create .html to
discuss and sign off with HR manager. My guess is no."*

WHY IT NEEDS HR AND NOT US
--------------------------
The arithmetic is settled — FBR85 says rest-day and holiday work is
`(out − in) − the lunch actually taken`. **The gap is what "actually taken"
means when nobody punched a lunch**, and that is a pay policy, not a formula.

⚠️ It is not academic. Measured on this site: **410 submitted rest-day logs, 40
carrying overtime, 299.5 hours.** Every one of those 40 is a Saturday or Sunday
somebody was paid for, and the rule below decides whether each was paid an hour
more or an hour less.

⚠️ READ-ONLY. Writes an HTML file and never touches the site.
"""

import os
from datetime import date

import frappe
from frappe.utils import cint

from caf.scripts.join_date_signoff_html import CSS

OUT = ("/workspace/development/frappe-bench/apps/caf/"
       "RESTDAY_LUNCH_for_HR_decision.html")

DAY = 24 * 60


def _m(v):
    return int(v.total_seconds() // 60) if v else None


def _hm(mins):
    if mins is None:
        return "—"
    return f"{mins // 60}h {mins % 60:02d}m" if mins % 60 else f"{mins // 60}h"


def _real_cases(limit=12):
    """Actual rest-day days with overtime, and what each option would pay."""
    rows = frappe.db.sql("""
        SELECT fl.name, fl.employee, fl.work_date, fl.day_type,
               fl.time_in, fl.`break` AS br, fl.resume, fl.`out`,
               fl.ot_in_hour, e.employee_name,
               st.name AS shift, st.caf_lunch_minutes, st.start_time, st.end_time,
               st.caf_ot_gate_minutes, st.caf_ot_round_minutes
          FROM `tabFinger Log` fl
          JOIN `tabShift Type` st ON st.name = fl.shift_type
          JOIN `tabEmployee` e ON e.name = fl.employee
         WHERE fl.docstatus = 1
           AND fl.day_type IN ('Restday', 'Holiday')
           AND fl.time_in IS NOT NULL AND fl.`out` IS NOT NULL
           AND fl.time_in != '00:00:00' AND fl.`out` != '00:00:00'
           AND st.caf_allow_ot = 1
         ORDER BY fl.work_date DESC""", as_dict=True)

    out = []
    for r in rows:
        i, o = _m(r.time_in), _m(r["out"])
        if i is None or o is None:
            continue
        if o <= i:
            o += DAY
        stint = o - i
        b, rs = _m(r.br), _m(r.resume)
        punched = (b and rs and rs > b)
        actual_lunch = (rs - b) if punched else None
        allow = cint(r.caf_lunch_minutes)
        net = (_m(r.end_time) - _m(r.start_time)) - allow if r.start_time else 0
        half = net / 2 if net else 0

        # the three readings
        a = stint - allow
        c = stint - (allow if stint > half else 0)
        if punched:
            a = c = stint - actual_lunch          # a punched lunch settles it
        b_opt = stint - (actual_lunch if punched else 0)

        def gated(raw):
            raw = max(0, raw)
            if raw < cint(r.caf_ot_gate_minutes):
                return 0.0
            step = cint(r.caf_ot_round_minutes)
            if step:
                raw -= raw % step
            return round(raw / 60.0, 2)

        out.append({
            "log": r.name, "who": r.employee_name, "date": r.work_date,
            "day_type": r.day_type, "shift": r.shift,
            "in": str(r.time_in)[:5], "out": str(r["out"])[:5],
            "stint": stint, "punched": punched, "actual_lunch": actual_lunch,
            "allow": allow, "half": half, "recorded": float(r.ot_in_hour or 0),
            "A": gated(a), "B": gated(b_opt), "C": gated(c),
        })
    out.sort(key=lambda x: x["stint"])
    short = [x for x in out if not x["punched"] and x["stint"] <= x["half"]]
    return out, short


EXTRA_CSS = """
.opt{border:1px solid var(--line);border-radius:8px;padding:14px 18px;margin:12px 0}
.opt h3{margin:0 0 4px;font-size:16px}
.opt.pick{border-color:#7aa7dd;background:var(--bluebg)}
.big{font-size:15px;font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.diff{background:var(--amberbg)}
"""


def write(path=None):
    path = path or OUT
    cases, short = _real_cases()

    n_rest = frappe.db.sql("SELECT COUNT(*) FROM `tabFinger Log` "
                           "WHERE docstatus=1 AND day_type='Restday'")[0][0]
    n_ot = len([c for c in cases if c["recorded"] > 0])
    hrs = round(sum(c["recorded"] for c in cases), 1)
    n_punched = len([c for c in cases if c["punched"]])

    # only the rows where the three options disagree are worth her time
    disagree = [c for c in cases if not (c["A"] == c["B"] == c["C"])]

    rows_html = "".join(
        f"<tr><td>{c['who']}<div class='small'>{c['date']} &middot; {c['day_type']} "
        f"&middot; {c['shift']}</div></td>"
        f"<td class='num'>{c['in']}–{c['out']}</td>"
        f"<td class='num'>{_hm(c['stint'])}</td>"
        f"<td class='num'>{'yes, ' + _hm(c['actual_lunch']) if c['punched'] else '<b>no</b>'}</td>"
        f"<td class='num{' diff' if c['A'] != c['B'] else ''}'>{c['A']}</td>"
        f"<td class='num{' diff' if c['B'] != c['A'] else ''}'>{c['B']}</td>"
        f"<td class='num{' diff' if c['C'] not in (c['A'], c['B']) or c['C'] != c['A'] else ''}'>{c['C']}</td>"
        f"<td class='num'>{c['recorded']}</td></tr>"
        for c in disagree[:20])

    tot_a = round(sum(c["A"] for c in cases), 1)
    tot_b = round(sum(c["B"] for c in cases), 1)
    tot_c = round(sum(c["C"] for c in cases), 1)

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CAF — Rest-day work and the lunch hour</title>
<style>{CSS}{EXTRA_CSS}</style></head><body>

<h1>Working on a rest day — do we still deduct the lunch hour?</h1>
<p class="sub">Prepared for Chen Xiao Natalie &middot; {date.today():%-d %B %Y}
&middot; one question, three options</p>

<div class="cards">
  <div class="card"><div class="n">{n_rest}</div>
    <div class="l">rest days worked and recorded</div></div>
  <div class="card amber"><div class="n">{n_ot}</div>
    <div class="l">of those paid overtime</div></div>
  <div class="card"><div class="n">{hrs}</div>
    <div class="l">hours paid on rest days</div></div>
  <div class="card red"><div class="n">{len(cases) - n_punched}</div>
    <div class="l">where nobody clocked a lunch break</div></div>
</div>

<h2>1 &middot; The question, in one paragraph</h2>
<p>When somebody works on a <b>rest day</b> or a <b>public holiday</b>, the
whole day is overtime — there is no normal working day to serve first. You
confirmed that rule. What it does not say is what to do about <b>lunch</b>.</p>
<div class="note">
On a normal working day the system deducts the lunch hour the shift allows,
whether or not anybody clocked it. <b>On a rest day that can be unfair in either
direction:</b>
<ul>
<li>Somebody who comes in for <b>three hours</b> on a Saturday morning almost
    certainly did not take an hour for lunch — but the system would deduct one,
    and pay them for two.</li>
<li>Somebody who works a <b>full nine hours</b> on a Sunday almost certainly did
    take a break — but if nobody clocked it, the system would pay for all nine.</li>
</ul>
</div>

<h2>2 &middot; The three ways to answer it</h2>

<div class="opt">
<h3>Option A &mdash; always deduct the shift's lunch hour</h3>
<p>Treat a rest day exactly like a working day. Simple and consistent.</p>
<p class="small">🔴 A three-hour Saturday morning pays <b>two hours</b>.</p>
</div>

<div class="opt pick">
<h3>Option C &mdash; deduct it only if the day was long enough to have had one
<span class="pill" style="background:#fff">MG's suggestion</span></h3>
<p>Deduct the lunch hour only when the stint is longer than <b>half a normal
working day</b>. Below that, deduct nothing.</p>
<p class="small">A three-hour Saturday morning pays <b>three hours</b>.
A nine-hour Sunday pays <b>eight</b>.</p>
</div>

<div class="opt">
<h3>Option B &mdash; only ever deduct a lunch that was actually clocked</h3>
<p>If the lunch punches are there, deduct exactly what they show. If not, deduct
nothing at all.</p>
<p class="small">A three-hour Saturday pays <b>three hours</b>; a nine-hour
Sunday also pays <b>nine</b>. ⚠️ This one rewards forgetting to clock lunch.</p>
</div>

<h2>3 &middot; What each option would have cost, on your real records</h2>
<p>These are the {len(cases)} rest days already recorded on shifts that allow
overtime. The totals are what each rule would have paid across all of them.</p>
<div class="wrap"><table style="min-width:560px">
<tr><th>Rule</th><th>Total overtime paid</th><th>Against what was actually paid</th></tr>
<tr><td><b>A</b> — always deduct</td><td class="num">{tot_a} h</td>
    <td class="num">{tot_a - hrs:+.1f} h</td></tr>
<tr><td><b>C</b> — deduct only on a long day</td><td class="num">{tot_c} h</td>
    <td class="num">{tot_c - hrs:+.1f} h</td></tr>
<tr><td><b>B</b> — only a clocked lunch</td><td class="num">{tot_b} h</td>
    <td class="num">{tot_b - hrs:+.1f} h</td></tr>
<tr><td class="ok">what was actually paid</td><td class="num">{hrs} h</td>
    <td class="num">—</td></tr>
</table></div>

<h2>4 &middot; The days where the three rules disagree</h2>
<p>Most days are unaffected. These {len(disagree)} are the ones where the choice
changes the number — shaded cells are where the options differ.</p>
<div class="wrap"><table style="min-width:880px">
<tr><th>Employee</th><th>Clocked</th><th>On site</th><th>Lunch clocked?</th>
    <th>A</th><th>C</th><th>B</th><th>Paid</th></tr>
{rows_html or "<tr><td colspan='8'>None — the three rules agree on every recorded day.</td></tr>"}
</table></div>
{"<p class='small'>Showing the first 20 of " + str(len(disagree)) + ".</p>" if len(disagree) > 20 else ""}

<div class="decide">
<h3>Please tick one</h3>
<p>&nbsp;&nbsp;☐ &nbsp;<b>A</b> — always deduct the lunch hour on a rest day<br>
&nbsp;&nbsp;☐ &nbsp;<b>C</b> — deduct it only when the day is longer than half a
normal day<br>
&nbsp;&nbsp;☐ &nbsp;<b>B</b> — deduct only a lunch that was actually clocked</p>
<p class="small">If you pick C, we also need the cut-off. The suggestion is
<b>half of the normal working day</b> for that shift — for an 8:00–16:30 shift
with an hour for lunch, that is 3 hours 45 minutes.</p>
</div>

<div class="sign">
<p><b>Signed off by</b> <span class="line"></span>
&nbsp;&nbsp;<b>Date</b> <span class="line" style="min-width:140px"></span></p>
<p class="small">This decision affects rest days and public holidays only.
Normal working days are unchanged — the lunch the shift allows is always
deducted there.</p>
</div>

<p class="small">Generated by <code>caf.scripts.restday_lunch_html.write</code>
from the live test server.</p>
</body></html>"""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"wrote {path}")
    print(f"  rest days recorded          : {n_rest}")
    print(f"  on OT-allowed shifts        : {len(cases)}")
    print(f"  with a lunch actually clocked: {n_punched}")
    print(f"  short stints, no lunch clocked: {len(short)}")
    print(f"  rows where the rules disagree : {len(disagree)}")
    print(f"  totals — A {tot_a} h · C {tot_c} h · B {tot_b} h · "
          f"actually paid {hrs} h")
    return {"cases": len(cases), "disagree": len(disagree),
            "A": tot_a, "B": tot_b, "C": tot_c, "paid": hrs}
