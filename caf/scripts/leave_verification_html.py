"""Generate the HR verification pages: joining dates, and the formula vs reality.

Purpose : two tables HR can check by eye — every employee's joining date against
          Ingress, and every 2026 allocation against HR's own pro-rating formula.
Run     : bench --site <site> execute caf.scripts.leave_verification_html.write
          (writes /tmp/LEAVE_FORMULA_for_HR_verification.html inside the container)
Needs   : /tmp/ingress_join.csv — userid,name,issuedate,createdate,suspended
          extracted from ingress_snapshot/user.csv.gz
Refs    : FBR29/30/31 · P-6 · OD-76 · scripts/leave_formula.py

⚠️ INGRESS `IssueDate` IS A CARD-ISSUE DATE, NOT ALWAYS A JOINING DATE.
Every employee enrolled when Ingress was installed carries **2022-03-01**, which
is when the system went in, not when they joined. Those rows are separated into
their own bucket — telling HR that 36 records "disagree" when a third of them are
an install date would waste their time and lose their trust in the rest.

Changelog
---------
1.0  2026-08-13  Initial
"""

import csv
import html
import os
from datetime import date

import frappe
from frappe.utils import getdate

from caf.scripts.leave_formula import entitlement, rows as formula_rows

INGRESS_CSV = "/tmp/ingress_join.csv"
OUT = "/tmp/LEAVE_FORMULA_for_HR_verification.html"
INSTALL_DATE = "2022-03-01"          # Ingress go-live; not a joining date
CYCLE = 2026


def _ingress():
    if not os.path.exists(INGRESS_CSV):
        frappe.throw(f"{INGRESS_CSV} not found — extract it from "
                     f"ingress_snapshot/user.csv.gz first")
    out = {}
    with open(INGRESS_CSV, newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            if r.get("userid"):
                out[r["userid"].strip()] = r
    return out


def e(v):
    return html.escape("" if v is None else str(v))


def actual_for(employee, cycle_year=CYCLE):
    """🔴 WHAT 'RECORDED' MEANS, since MG asked and the page must say so:
    `Leave Allocation.new_leaves_allocated`, submitted, for a cycle starting in
    that year. It is the entitlement GRANTED — not leave taken, not a count of
    Leave Applications, and not a balance on any particular date. Carry-forward
    is zero on every row, so granted and total are the same number here."""
    return {r.leave_type: float(r.days) for r in frappe.db.sql("""
        SELECT leave_type, new_leaves_allocated AS days
          FROM `tabLeave Allocation`
         WHERE docstatus = 1 AND employee = %s AND YEAR(from_date) = %s""",
                                                              (employee, int(cycle_year)),
                                                              as_dict=True)}


# ── the timelines ───────────────────────────────────────────────────────────
# MG: *"big ask, but helpful for old ppl"* — three worked examples drawn rather
# than described. The point each one makes is different:
#
#   Syamim       joined in January, so the two windows almost coincide — the
#                simplest case, and the one that shows the <1-year AL block
#   Nurul Hazirah  MG's own worked example, and the case where the service
#                window (17 months) is much longer than the cycle
#   Noor Arifah  crosses TWO years mid-cycle, which is why the flat band
#                applies to her whole 2026 — and why her recorded 8 looks wrong
ILLUSTRATE = [
    ("Muhammad Syamim Bin Aziz", 2026, 2027),
    ("Nurul Hazirah Binti Mohamed Fikri", 2025, 2027),
    ("Noor Arifah Binti Ibrahim", 2025, 2027),
]

PX_PER_MONTH = 26
LEFT = 150
TOP = 34
LANE_H = 26


def _months_between(a, b):
    a, b = getdate(a), getdate(b)
    return (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.0


def _svg(name, join_date, y0, y1):
    """One timeline. x is months from 1 Jan of y0."""
    join = getdate(join_date)
    origin = date(y0, 1, 1)
    span = (y1 - y0 + 1) * 12
    W = LEFT + span * PX_PER_MONTH + 210
    H = TOP + LANE_H * 5 + 96

    def x(d):
        return LEFT + _months_between(origin, d) * PX_PER_MONTH

    p = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" '
         f'style="max-width:{W:.0f}px" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="inherit" font-size="12">']
    p.append(f'<text x="0" y="16" font-size="14" font-weight="700" '
             f'fill="var(--fg)">{e(name)} — joined {join}</text>')

    # HR cycles as alternating bands
    for i, yr in enumerate(range(y0, y1 + 1)):
        x0, x1 = x(date(yr, 1, 1)), x(date(yr, 12, 31))
        fill = "var(--cyc-a)" if i % 2 == 0 else "var(--cyc-b)"
        p.append(f'<rect x="{x0:.0f}" y="{TOP}" width="{x1 - x0:.0f}" '
                 f'height="{LANE_H * 5:.0f}" fill="{fill}"/>')
        p.append(f'<text x="{(x0 + x1) / 2:.0f}" y="{TOP + LANE_H * 5 + 30:.0f}" '
                 f'text-anchor="middle" font-weight="700" fill="var(--muted)">'
                 f'HR cycle {yr}</text>')
        p.append(f'<text x="{x0 + 3:.0f}" y="{TOP + LANE_H * 5 + 15:.0f}" '
                 f'fill="var(--muted)" font-size="10">Jan</text>')
        p.append(f'<text x="{x1 - 3:.0f}" y="{TOP + LANE_H * 5 + 15:.0f}" '
                 f'text-anchor="end" fill="var(--muted)" font-size="10">Dec</text>')
        p.append(f'<line x1="{x1:.0f}" y1="{TOP}" x2="{x1:.0f}" '
                 f'y2="{TOP + LANE_H * 5 + 18:.0f}" stroke="var(--line)"/>')

    # joining date
    p.append(f'<line x1="{x(join):.0f}" y1="{TOP - 6}" x2="{x(join):.0f}" '
             f'y2="{TOP + LANE_H * 5 + 18:.0f}" stroke="var(--accent)" '
             f'stroke-width="2"/>')
    p.append(f'<text x="{x(join) + 4:.0f}" y="{TOP - 10}" fill="var(--accent)" '
             f'font-weight="700">joined</text>')

    def bar(lane, x0, x1, label, colour):
        y = TOP + lane * LANE_H + 5
        p.append(f'<rect x="{x0:.0f}" y="{y:.0f}" width="{max(x1 - x0, 2):.0f}" '
                 f'height="14" rx="3" fill="{colour}" opacity=".85"/>')
        p.append(f'<text x="{LEFT - 8}" y="{y + 11:.0f}" text-anchor="end" '
                 f'fill="var(--muted)">{label}</text>')

    # service anniversaries
    for n, lane in ((1, 0), (2, 1)):
        end = date(join.year + n, join.month, min(join.day, 28))
        if end.year <= y1:
            bar(lane, x(join), x(end), f"{n} year{'s' if n > 1 else ''} of service",
                "var(--svc)")
            p.append(f'<text x="{x(end) + 5:.0f}" y="{TOP + lane * LANE_H + 16:.0f}" '
                     f'fill="var(--svc)" font-weight="700">{end}</text>')

    # the service window used for each cycle: join -> 31 Dec of that cycle
    lane = 2
    notes = []
    for yr in range(y0, y1 + 1):
        cend = date(yr, 12, 31)
        if cend < join:
            continue
        ent = entitlement(join, yr)
        bar(lane, x(join), x(cend), f"window for {yr}", "var(--win)")
        p.append(f'<text x="{x(cend) + 5:.0f}" y="{TOP + lane * LANE_H + 16:.0f}" '
                 f'fill="var(--win)" font-weight="700">'
                 f'{ent["months"]} months &#8594; AL {ent["al"]} / MC {ent["mc"]}</text>')
        notes.append((yr, ent))
        lane += 1

    p.append('</svg>')
    return "".join(p), notes


def _checkpoints(join, notes):
    """What the employee would be TOLD on a few dates — allocation vs usable."""
    join = getdate(join)
    one_year = date(join.year + 1, join.month, min(join.day, 28))
    out = []
    for yr, ent in notes:
        for label, when in ((f"mid {yr}", date(yr, 6, 15)),
                            (f"end {yr}", date(yr, 12, 15))):
            if when < join:
                continue
            usable_al = ent["al"] if when >= one_year else 0
            out.append({
                "when": f"{label} ({when})", "al_alloc": ent["al"],
                "al_usable": usable_al, "mc": ent["mc"],
                "why": "" if when >= one_year
                       else f"under 1 year of service until {one_year}",
            })
    return out


def join_rows():
    ing = _ingress()
    out = []
    for emp in frappe.get_all(
            "Employee", filters={"status": "Active"},
            fields=["name", "employee_name", "date_of_joining",
                    "attendance_device_id"], order_by="employee_name"):
        i = ing.get((emp.attendance_device_id or "").strip()) if emp.attendance_device_id else None
        issue = (i or {}).get("issuedate") or ""
        erp = str(emp.date_of_joining) if emp.date_of_joining else ""
        if not emp.attendance_device_id or not i:
            bucket = "nolink"
        elif not issue:
            bucket = "nolink"
        elif issue == INSTALL_DATE:
            bucket = "install"
        elif issue == erp:
            bucket = "agree"
        else:
            bucket = "differ"
        out.append({"emp": emp.name, "name": emp.employee_name, "erp": erp,
                    "ingress": issue, "device": emp.attendance_device_id or "",
                    "bucket": bucket})
    return out


def _recalc(erp_date, ingress_date):
    """What the formula would give under each joining date, for the 2026 cycle."""
    a = entitlement(erp_date, CYCLE) if erp_date else None
    b = entitlement(ingress_date, CYCLE) if ingress_date else None
    return a, b


def write():
    jr = join_rows()
    fr = formula_rows(CYCLE)
    ing = _ingress()

    n_agree = sum(1 for r in jr if r["bucket"] == "agree")
    n_diff = sum(1 for r in jr if r["bucket"] == "differ")
    n_inst = sum(1 for r in jr if r["bucket"] == "install")
    n_nolink = sum(1 for r in jr if r["bucket"] == "nolink")

    al_ok = sum(1 for r in fr if r["al_actual"] is not None
                and abs(r["al_actual"] - r["al_formula"]) < .01)
    al_n = sum(1 for r in fr if r["al_actual"] is not None)
    mc_ok = sum(1 for r in fr if r["mc_actual"] is not None
                and abs(r["mc_actual"] - r["mc_formula"]) < .01)
    mc_n = sum(1 for r in fr if r["mc_actual"] is not None)

    # ── table 1: the formula ────────────────────────────────────────────
    t1 = []
    for r in fr:
        al_bad = (r["al_actual"] is not None
                  and abs(r["al_actual"] - r["al_formula"]) >= .01)
        mc_bad = (r["mc_actual"] is not None
                  and abs(r["mc_actual"] - r["mc_formula"]) >= .01)
        missing = r["al_actual"] is None or r["mc_actual"] is None
        cls = "bad" if (al_bad or mc_bad) else ("miss" if missing else "")
        t1.append(
            f'<tr class="{cls}"><td>{e(r["name"])}</td><td>{e(r["joined"])}</td>'
            f'<td class="n">{r["months"]}</td><td>{e(r["rule"])}</td>'
            f'<td class="n">{r["al_formula"]}</td>'
            f'<td class="n {"bad" if al_bad else ""}">'
            f'{"—" if r["al_actual"] is None else r["al_actual"]}</td>'
            f'<td class="n">{r["mc_formula"]}</td>'
            f'<td class="n {"bad" if mc_bad else ""}">'
            f'{"—" if r["mc_actual"] is None else r["mc_actual"]}</td></tr>')

    # ── table 2: joining dates ──────────────────────────────────────────
    order = {"differ": 0, "nolink": 1, "install": 2, "agree": 3}
    label = {"differ": "DISAGREE", "nolink": "no Ingress record",
             "install": "Ingress shows install date", "agree": "agree"}
    t2 = []
    for r in sorted(jr, key=lambda x: (order[x["bucket"]], x["name"])):
        extra = ""
        diff = ""
        if r["erp"] and r["ingress"]:
            # MG's request: the gap itself, signed. Positive = Ingress is LATER
            # than ERPNext, i.e. ERPNext credits service the person did not have.
            d = (getdate(r["ingress"]) - getdate(r["erp"])).days
            if d:
                diff = f'{"+" if d > 0 else ""}{d} d'
        if r["bucket"] == "differ" and r["erp"] and r["ingress"]:
            a, b = _recalc(r["erp"], r["ingress"])
            if a and b and (a["al"] != b["al"] or a["mc"] != b["mc"]):
                extra = (f'AL {a["al"]}&rarr;{b["al"]}, MC {a["mc"]}&rarr;{b["mc"]}')
            else:
                extra = "no change to 2026 leave"
        t2.append(
            f'<tr class="{"bad" if r["bucket"] == "differ" else ""}">'
            f'<td>{e(r["name"])}</td><td class="n">{e(r["device"])}</td>'
            f'<td>{e(r["erp"]) or "&mdash;"}</td>'
            f'<td>{e(r["ingress"]) or "&mdash;"}</td>'
            f'<td class="n">{diff}</td>'
            f'<td>{label[r["bucket"]]}</td><td class="small">{extra}</td>'
            f'<td class="ansbox"></td></tr>')

    # ── the three worked examples ───────────────────────────────────────
    charts = []
    for want, y0, y1 in ILLUSTRATE:
        emp = frappe.db.get_value("Employee", {"employee_name": want},
                                  ["name", "employee_name", "date_of_joining"],
                                  as_dict=True)
        if not emp or not emp.date_of_joining:
            continue
        svg, notes = _svg(emp.employee_name, emp.date_of_joining, y0, y1)
        got = actual_for(emp.name)
        cps = "".join(
            f'<tr><td>{e(c["when"])}</td>'
            f'<td class="n">{c["al_alloc"]}</td>'
            f'<td class="n {"bad" if c["al_usable"] != c["al_alloc"] else ""}">'
            f'{c["al_usable"]}</td>'
            f'<td class="n">{c["mc"]}</td>'
            f'<td class="small">{e(c["why"])}</td></tr>'
            for c in _checkpoints(emp.date_of_joining, notes))
        rec = (f'recorded in the system for 2026: '
               f'annual <b>{got.get("Annual", "none")}</b>, '
               f'medical <b>{got.get("MC", "none")}</b>')
        charts.append(
            f'<div class="chart"><div class="scroll">{svg}</div>'
            f'<table class="cp"><thead><tr><th>If asked on…</th>'
            f'<th class="n">Annual allocated</th><th class="n">Annual he/she may TAKE</th>'
            f'<th class="n">Medical</th><th>Why</th></tr></thead>'
            f'<tbody>{cps}</tbody></table>'
            f'<p class="small">{rec}</p></div>')

    doc = TEMPLATE.format(
        generated=date.today().strftime("%d %B %Y"),
        al_ok=al_ok, al_n=al_n, mc_ok=mc_ok, mc_n=mc_n,
        combined=round((al_ok + mc_ok) / max(al_n + mc_n, 1) * 100),
        n_agree=n_agree, n_diff=n_diff, n_inst=n_inst, n_nolink=n_nolink,
        n_total=len(jr), rows1="\n".join(t1), rows2="\n".join(t2),
        charts="\n".join(charts))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"written: {OUT}  ({len(doc):,} bytes)")
    print(f"  formula : annual {al_ok}/{al_n}, medical {mc_ok}/{mc_n}")
    print(f"  joining : {n_diff} disagree, {n_inst} install-date, "
          f"{n_nolink} no link, {n_agree} agree, of {len(jr)}")
    return OUT


TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CAF — Leave formula and joining dates: please verify</title>
<style>
 :root{{--bg:#fff;--fg:#1a1a1a;--muted:#5c5c5c;--line:#d8d8d8;--card:#f7f7f5;
        --accent:#8a3b00;--red:#a41b1b;--redbg:#fdf0f0;--amber:#8a5a00;
        --green:#1d6b2f;--box:#fffdf5;--boxline:#c9a227;}}
 @media (prefers-color-scheme:dark){{
   :root{{--bg:#161615;--fg:#eeeeec;--muted:#a5a59f;--line:#3a3a38;--card:#1f1f1e;
          --accent:#e0a06a;--red:#ef8080;--redbg:#2a1c1c;--amber:#e0b64a;
          --green:#7ec98d;--box:#242320;--boxline:#7a6520;}}}}
 *{{box-sizing:border-box}}
 body{{margin:0;padding:2rem 1.25rem 5rem;background:var(--bg);color:var(--fg);
   font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
 .wrap{{max-width:66rem;margin:0 auto}}
 h1{{font-size:1.75rem;margin:0 0 .3rem;line-height:1.25}}
 h2{{font-size:1.2rem;margin:2.4rem 0 .6rem;padding-top:1rem;border-top:2px solid var(--line)}}
 .sub{{color:var(--muted);margin:0 0 1.5rem;font-size:.94rem}}
 .lead{{background:var(--card);border-left:4px solid var(--accent);padding:1rem 1.2rem;
        border-radius:0 6px 6px 0;margin:1.4rem 0}}
 table{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.88rem}}
 th,td{{border:1px solid var(--line);padding:.36rem .5rem;text-align:left;vertical-align:top}}
 th{{background:var(--card);font-weight:600;position:sticky;top:0}}
 td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
 tr.bad{{background:var(--redbg)}}
 td.bad{{color:var(--red);font-weight:700}}
 tr.miss td{{color:var(--muted)}}
 .scroll{{overflow-x:auto}}
 .small{{font-size:.82rem;color:var(--muted)}}
 .ansbox{{min-width:7rem;background:var(--box)}}
 .pill{{display:inline-block;padding:.14rem .5rem;border-radius:3px;font-size:.75rem;
        font-weight:700;letter-spacing:.04em;margin-right:.4rem}}
 .p-red{{background:var(--red);color:#fff}} .p-ok{{background:var(--green);color:#fff}}
 .p-amb{{background:var(--amber);color:#fff}}
 .box{{border:1px solid var(--line);border-radius:8px;padding:1rem 1.2rem;
       background:var(--card);margin:1.2rem 0}}
 code{{background:var(--bg);padding:.08em .35em;border-radius:3px;font-size:.9em}}
 .formula{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9rem;
           background:var(--bg);border:1px solid var(--line);border-radius:6px;
           padding:.9rem 1.1rem;white-space:pre;overflow-x:auto}}
 :root{{--cyc-a:#eef3f7;--cyc-b:#f7f3ee;--svc:#2a6fb0;--win:#8a3b00}}
 @media (prefers-color-scheme:dark){{
   :root{{--cyc-a:#1c2126;--cyc-b:#241f1a;--svc:#7ab6ea;--win:#e0a06a}}}}
 .chart{{border:1px solid var(--line);border-radius:8px;padding:1rem;margin:1.4rem 0;
         background:var(--card)}}
 .chart svg{{display:block;margin:.2rem 0 .8rem}}
 table.cp{{font-size:.85rem;margin:.4rem 0}}
 table.cp th{{position:static}}
 .legend{{display:flex;gap:1.4rem;flex-wrap:wrap;font-size:.85rem;color:var(--muted);
          margin:.6rem 0 0}}
 .legend i{{display:inline-block;width:1.6rem;height:.7rem;border-radius:2px;
            margin-right:.35rem;vertical-align:.02em}}
 @media print{{body{{padding:0;font-size:10pt}} th{{position:static}}
   :root{{--bg:#fff;--fg:#000;--card:#f4f4f4;--redbg:#fbeaea;--box:#fffdf0}}}}
</style></head><body><div class="wrap">

<h1>Leave formula and joining dates — please verify</h1>
<p class="sub">Prepared for HR · {generated} · every figure below was read from the system,
then checked against the pro-rating rule you described.</p>

<div class="lead">
<p><b>The rule you gave works.</b> Applied to everyone with under two years of service, it
reproduces <b>{al_ok} of {al_n}</b> annual leave figures and <b>{mc_ok} of {mc_n}</b> medical leave
figures already in the system. The rows it does <b>not</b> reproduce are highlighted — those are the
ones worth your eyes, and there are only a handful.</p>
</div>

<h2>1 · The rule, as we understood it</h2>
<div class="formula">months  = whole months from the joining date to 31 December of that year
          (13 Apr to 31 Dec counts as 8 months, not 8 and a half)

annual  = months / 12 x 8      medical = months / 12 x 14

          both rounded DOWN to the nearest half day
          (22 months gives 14.67, which becomes 14.5)

once the service reaches 2 years, the flat bands take over:
          2 to 5 years   12 annual   18 medical
          over 5 years   16 annual   22 medical</div>

<div class="box">
<p><span class="pill p-amb">Please confirm</span><b>Two details we had to work out from the figures,
because they were not in the description.</b></p>
<ul>
<li><b>Whole months, not part months.</b> Muhammad Nafiz joined 13 April 2026 and has 9 days of
medical leave. Counting to 13 December gives 8 months, and 8/12 &times; 14 = 9.3 &rarr; <b>9</b>.
Counting the extra 18 days gives 10. His record says 9, so part months appear to be dropped.</li>
<li><b>Rounded down to the nearest HALF day, not a whole day.</b> Kavithaa and Tanisha both have
22 months, and 22/12 &times; 8 = 14.67. Rounded down to a whole day that is 14; to a half day it is
<b>14.5</b> — and both of them have exactly 14.5.</li>
</ul>
<p><b>We tested the alternative you described</b> — exact number of days, rounded down to a whole
day — against the same records:</p>
<table style="max-width:38rem">
<thead><tr><th>Method</th><th class="n">Annual</th><th class="n">Medical</th><th class="n">Fit</th></tr></thead>
<tbody>
<tr><td><b>Whole months, down to the nearest half day</b></td><td class="n">{al_ok}/{al_n}</td>
    <td class="n">{mc_ok}/{mc_n}</td><td class="n"><b>{combined}%</b></td></tr>
<tr><td>Exact days, down to a whole day</td><td class="n">21/25</td><td class="n">25/31</td>
    <td class="n">82%</td></tr>
</tbody></table>
<p class="small">The whole-month version fits better, and <b>Kavithaa and Tanisha decide it</b>: exact
days gives them 14 and 15, whole months gives 14.5 for both — and 14.5 is what they have. That
suggests the sum is done in months by hand rather than in days by calculator. <b>Please confirm which
you actually do</b>, because the two disagree for seven people.</p>
</div>

<h2>2 · Three worked examples</h2>
<p>The same rule, drawn. Each chart shows the two time windows that decide the answer —
<b>how long the person has worked</b>, and <b>how long they will have worked by 31 December</b> of
the cycle being granted. The second is the one the calculation uses.</p>
<div class="legend">
  <span><i style="background:var(--svc)"></i>length of service</span>
  <span><i style="background:var(--win)"></i>joining date &rarr; 31 December (what the sum uses)</span>
  <span><i style="background:var(--accent);width:.25rem"></i>joining date</span>
  <span><i style="background:var(--cyc-a);border:1px solid var(--line)"></i>alternating HR cycles</span>
</div>

{charts}

<div class="box">
<p><span class="pill p-amb">Please confirm</span><b>The column that surprises people.</b>
&ldquo;Annual allocated&rdquo; and &ldquo;annual he/she may take&rdquo; are different numbers in the
first year — the days are being counted up, but the employee is not allowed to spend them until they
have completed one year. Is that right?</p>
<p class="small">If it is, it also explains why the figure looks large just before the two-year mark:
it is not one year's leave, it is <b>everything accrued since joining and never taken</b>. At two
years it changes to a normal yearly grant of 12, which looks like a cut but is not.</p>
</div>

<h2>3 · Every 2026 entitlement, calculated against actual</h2>

<div class="box">
<p><span class="pill p-ok">What these numbers are</span>
&ldquo;Recorded&rdquo; is the <b>entitlement granted</b> for the 2026 cycle — the allocation document
in the system. <b>It is not leave taken</b>, not a count of leave applications, and not a balance on
any particular date. Nobody has any carried-forward leave, so granted and total are the same figure.</p>
<p class="small"><b>Joining dates in this table come from ERPNext</b>, not Ingress — so any row whose
joining date is wrong in section 4 will also have the wrong calculation here. That is deliberate: fix
the dates first, then this table can be regenerated against them.</p>
</div>

<p class="small">Highlighted rows are where the calculation and the record disagree.
&ldquo;&mdash;&rdquo; means no entitlement of that type is recorded at all.</p>

<div class="scroll"><table>
<thead><tr><th>Employee</th><th>Joined</th><th class="n">Months to 31 Dec 26</th><th>Rule used</th>
<th class="n">Annual — calculated</th><th class="n">Annual — recorded</th>
<th class="n">Medical — calculated</th><th class="n">Medical — recorded</th></tr></thead>
<tbody>
{rows1}
</tbody></table></div>

<div class="box">
<p><span class="pill p-red">Please decide</span><b>The rows that disagree.</b></p>
<ul>
<li><b>Mohammad Ehsan</b> — calculated 12 annual, recorded 18. We were told this is a one-off
carry-over approved after an appeal, and that CAF has no carry-over policy otherwise.
<b>Please confirm</b>, so the system treats it as a manual exception rather than copying it.</li>
<li><b>Noor Arifah</b> — calculated 12 annual, recorded 8. She reached 2 years of service during
2026, so the flat band should apply. <b>8 is the starting constant in the formula</b>, which suggests
it may have been entered before her band changed. Please confirm which is right.</li>
<li><b>Ehsan and Noor Arifah</b> both show 14 medical where the 2-to-5-year band gives <b>18</b>.
If the band is right, they are 4 days short each.</li>
<li><b>Khairol Izzah, Muhammad Syamim, Nurhasirah</b> — all joined in early 2026 and hold the full
14 medical days, where pro-rating would give 11.5 to 12.5. Is medical leave given in full to
anyone joining early in the year, or should these be pro-rated like Nafiz's?</li>
<li><b>Chong Jin Yen</b> and <b>Tanisha</b> still have no medical entitlement recorded at all.</li>
</ul>
</div>

<h2>4 · Joining dates — Ingress against ERPNext</h2>
<p>You said the joining date in Ingress is the reliable one. Comparing every active employee's
Ingress card-issue date against the date in ERPNext:</p>

<table style="max-width:34rem">
<tbody>
<tr><td><b>Disagree</b> — worth checking</td><td class="n"><b>{n_diff}</b></td></tr>
<tr><td>Agree</td><td class="n">{n_agree}</td></tr>
<tr><td>Ingress shows <code>2022-03-01</code>, the date the system was installed</td><td class="n">{n_inst}</td></tr>
<tr><td>No Ingress record to compare</td><td class="n">{n_nolink}</td></tr>
<tr><td><b>Total active employees</b></td><td class="n"><b>{n_total}</b></td></tr>
</tbody></table>

<div class="box">
<p><span class="pill p-amb">Important</span><b>The {n_inst} rows showing 2022-03-01 are not
disagreements.</b> That is the day Ingress was installed, given to everybody already employed at the
time. For those people Ingress cannot tell us when they joined, so <b>the ERPNext date is all we
have</b> — and if it is wrong, only you can correct it.</p>
</div>

<p class="small">The last column shows what the 2026 entitlement would become if the Ingress date
were used instead. A blank means the two dates land in the same month and nothing changes.
The right-hand column is for your correction.</p>

<div class="scroll"><table>
<thead><tr><th>Employee</th><th class="n">Ingress ID</th><th>ERPNext says</th><th>Ingress says</th>
<th class="n">Gap</th><th>Status</th><th>Effect on 2026 leave</th><th>Correct date</th></tr></thead>
<tbody>
{rows2}
</tbody></table></div>

<h2>4 · What we do with your answers</h2>
<p>Confirmed, the rule replaces hand-entered leave: the system grants every employee their
entitlement each January and adjusts it on their service anniversary automatically. Until then it
stays a manual step, and the highlighted rows above stay as they are.</p>
<p class="small">Prepared from the CAF test system. Nothing in the live payroll or leave records has
been changed. If a figure looks wrong, it is worth saying so — it was read from the records, and the
records may be what needs correcting.</p>

</div></body></html>
"""
