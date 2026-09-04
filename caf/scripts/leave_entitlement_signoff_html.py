"""The leave-entitlement sign-off page — what HR is actually agreeing to.

    bench --site <site> execute caf.scripts.leave_entitlement_signoff_html.write

MG, 2026-09-04: *"although HR manager has verbally confirm, i recommend to create
a doc with clear illustration or example to indicate what she has sign off …
however need to clearly indicate the effect of formula, and several related
business rule."*

WHY A VERBAL CONFIRMATION IS NOT ENOUGH HERE
--------------------------------------------
HR confirmed four things on 2026-09-04, and every one of them is a sentence whose
CONSEQUENCE is a number she has not seen:

  1. three service bands, three policies, plus a formula under two years
  2. medical caps at 14 for anyone under two years
  3. under one year of service, annual leave may not be taken at all
  4. annual DROPS at the two-year transition — *"as bonus or interest due to the
     no apply on first year policy"*

Rule 3 and rule 4 interact in a way nobody has written down: an employee who
joins in December is allocated annual leave **on their anniversary, in the
December of the following year**, with two weeks of the cycle left to take it —
and CAF carries nothing over. That is not a bug in the formula; it is what the
four rules say when you run them together. It has to be on the page HR signs,
because it is the part she will be asked about in January.

⚠️ READ-ONLY. Writes an HTML file and never touches the site.

WHAT IS COMPUTED VS WHAT IS QUOTED
----------------------------------
Every number in the worked examples is produced by `caf.scripts.leave_formula`
and `caf.caf.leave_allocation` — the same code that will do the allocation — so
the page cannot drift from the build. The band table and the four rules are
quoted from HR. Anything the data disagrees with is in its own section rather
than smoothed over.
"""

import os
from datetime import date

import frappe
from frappe.utils import getdate

from caf.caf.leave_allocation import ANNUAL, MEDICAL, anniversary, entitlement_for
from caf.scripts.leave_formula import completed_months, entitlement
from caf.scripts.join_date_signoff_html import CSS

OUT = ("/workspace/development/frappe-bench/apps/caf/"
       "LEAVE_ENTITLEMENT_for_HR_signoff.html")

CYCLE = 2026

# The four archetypes MG asked for: early / mid / late joiner, and the band
# transition itself. Traced across three cycles each, because one cycle cannot
# show a rule whose whole point is what happens in the NEXT one.
ARCHETYPES = [
    ("Joins early in the year", "2026-01-05", [2026, 2027, 2028],
     "The common case. Almost a full year of service in the joining cycle, and "
     "still no annual leave in it."),
    ("Joins mid-year", "2026-07-01", [2026, 2027, 2028],
     "Half a year of service. Medical is pro-rated from the joining day; annual "
     "does not start until the anniversary, part-way through the NEXT cycle."),
    ("Joins late in the year", "2026-12-15", [2026, 2027, 2028],
     "🔴 The case that needs a decision. Nothing at all in the joining cycle, "
     "and the first annual allocation lands 16 days before it expires."),
    ("Already 23 months of service", "2025-01-20", [2026, 2027, 2028],
     "The two-year transition, close up. This is where annual DROPS."),
]


def _fmt(x):
    if x is None:
        return "—"
    return f"{x:g}"


def _trace(doj, cycle):
    """One cycle for one joining date: what is allocated, and what is usable."""
    doj = getdate(doj)
    rows = entitlement_for(doj, cycle)
    months = completed_months(doj, date(cycle, 12, 31))
    band = entitlement(doj, cycle)["rule"]
    anniv = anniversary(doj)

    al = rows.get(ANNUAL)
    mc = rows.get(MEDICAL)

    # "Usable days" is the point of the whole page: an allocation that opens on
    # 15 December is not 8 days of leave, it is 8 days and 16 days to take them.
    if al:
        window = (date(cycle, 12, 31) - getdate(al["from_date"])).days + 1
        al_note = (f"{al['days']:g} days, usable from "
                   f"{getdate(al['from_date']).strftime('%-d %b')} "
                   f"— {window} days of the cycle left")
        if window < 60:
            al_note = f"🔴 {al_note}"
    else:
        al_note = ("none — the first anniversary falls after this cycle ends, "
                   "so no annual row is created at all")

    if mc:
        mc_note = (f"{mc['days']:g} days, usable from "
                   f"{getdate(mc['from_date']).strftime('%-d %b')}")
    else:
        mc_note = "none — service is under one completed month at cycle end"

    return {
        "cycle": cycle, "months": months, "band": band, "anniversary": anniv,
        "al_days": al["days"] if al else None, "al_note": al_note,
        "mc_days": mc["days"] if mc else None, "mc_note": mc_note,
    }


def _band_table():
    pol = {}
    for p in frappe.get_all("Leave Policy", fields=["name", "title", "docstatus"]):
        pol[p.title] = p
    out = []
    for title, span, al, mc in (
            ("CAF Service under 2 years (ANNUAL PROVISIONAL)", "0 – 23 months",
             "months ÷ 12 × 8, rounded DOWN to the half day",
             "months ÷ 12 × 14, rounded DOWN to the half day, never above 14"),
            ("CAF Service 2 to 5 years", "24 – 59 months", "12", "18"),
            ("CAF Service over 5 years", "60 months and over", "16", "22")):
        p = pol.get(title)
        out.append((title, span, al, mc,
                    p.name if p else "🔴 NOT ON THIS SITE",
                    "draft" if p and not p.docstatus else ("submitted" if p else "—")))
    return out


def _mismatches(cycle=CYCLE):
    """Employees whose RECORDED allocation disagrees with the rule HR confirmed.

    These are not errors in the formula and they are not accusations. They are
    the rows where the hand-entered number and the stated rule differ, and the
    only person who can say which is right is HR.
    """
    from caf.scripts.leave_formula import rows as formula_rows
    out = []
    for r in formula_rows(cycle):
        for kind, calc, actual in ((ANNUAL, r["al_formula"], r["al_actual"]),
                                   (MEDICAL, r["mc_formula"], r["mc_actual"])):
            if actual is None:
                continue
            if abs(float(actual) - float(calc)) >= 0.01:
                out.append({
                    "name": r["name"], "joined": r["joined"], "months": r["months"],
                    "band": r["rule"], "kind": kind,
                    "calc": calc, "actual": actual,
                    "diff": float(actual) - float(calc),
                    "status": r["status"],
                })
    out.sort(key=lambda x: (x["months"], x["name"]))
    return out


def _group_counts():
    have = {r[0] for r in frappe.db.sql(
        "SELECT DISTINCT employee FROM `tabLeave Allocation` "
        "WHERE docstatus=1 AND YEAR(from_date)=%s", CYCLE)}
    act = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")
    return len(act), len([e for e in act if e in have]), len([e for e in act if e not in have])


# HR named these seven on 2026-09-04 as employees WITH entitlement who currently
# hold no allocation. Everyone else outside the current allocation set has none.
HR_GROUP_B_ADDITIONS = [
    "Nur Salsabila Binti Mohd Kalam Izad",
    "Intan Nadira Shahira   Binti  Abdullah",
    "Hairunnissa'a  Binti Noor Azmi",
    "Nur Elyana Syafiqah  Binti  Saimi",
    "Tinagaraj A/L Morgan",
    "Muhammad Jamil  Bin  Mansur",
    "Nur Alia Safaraz Binti Zulkifli",
]


def _additions():
    out = []
    for nm in HR_GROUP_B_ADDITIONS:
        e = frappe.db.sql(
            "SELECT name, employee_name, date_of_joining, department, status "
            "FROM tabEmployee WHERE employee_name=%s", (nm,), as_dict=True)
        if not e:
            out.append({"name": nm, "employee": "🔴 NOT MATCHED", "joined": None,
                        "months": None, "al": None, "mc": None, "dept": "", "status": ""})
            continue
        e = e[0]
        rows = entitlement_for(e.date_of_joining, CYCLE)
        out.append({
            "name": e.employee_name, "employee": e.name,
            "joined": e.date_of_joining, "dept": e.department or "",
            "status": e.status,
            "months": completed_months(e.date_of_joining, date(CYCLE, 12, 31)),
            "al": rows.get(ANNUAL), "mc": rows.get(MEDICAL),
        })
    return out


# ─────────────────────────────────────────────────────────────────── rendering
def _cycle_bar(doj, cycle):
    """A one-line calendar strip: when in the cycle each allowance opens."""
    doj = getdate(doj)
    rows = entitlement_for(doj, cycle)
    marks = []
    for label, row, colour in (("Annual", rows.get(ANNUAL), "#0b4f9e"),
                               ("Medical", rows.get(MEDICAL), "#1b5e20")):
        if not row:
            continue
        start = getdate(row["from_date"])
        pct = (start - date(cycle, 1, 1)).days / 365 * 100
        marks.append(
            f'<div class="mk" style="left:{pct:.1f}%;border-color:{colour}">'
            f'<span style="color:{colour}">{label} {row["days"]:g}d</span></div>')
    if not marks:
        return ('<div class="bar"><div class="empty">nothing opens in this '
                'cycle</div></div>')
    return f'<div class="bar">{"".join(marks)}</div>'


EXTRA_CSS = """
.bar{position:relative;height:34px;background:linear-gradient(90deg,#f3f5f8,#eef1f5);
     border:1px solid var(--line);border-radius:5px;margin:6px 0 2px}
.bar .mk{position:absolute;top:-2px;height:38px;border-left:2px solid;padding-left:5px}
.bar .mk span{font-size:11.5px;font-weight:600;white-space:nowrap;
              position:relative;top:9px}
.bar .empty{font-size:12px;color:var(--muted);padding:9px 10px}
.months{display:flex;font-size:10.5px;color:var(--muted);margin:0 0 14px}
.months div{flex:1;text-align:center}
.arch{border:1px solid var(--line);border-radius:8px;padding:14px 18px;margin:16px 0}
.arch h3{margin:0 0 2px;font-size:16px}
.arch .lead{color:var(--muted);font-size:13.5px;margin:0 0 12px}
.up{color:var(--green);font-weight:600}
.down{color:var(--red);font-weight:600}
"""

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def write(path=None):
    path = path or OUT
    n_active, n_have, n_none = _group_counts()
    mism = _mismatches()
    adds = _additions()

    # ── the four archetypes ────────────────────────────────────────────────
    arch_html = []
    for title, doj, cycles, lead in ARCHETYPES:
        traces = [_trace(doj, c) for c in cycles]
        bars = []
        for c in cycles:
            bars.append(
                f'<div class="small" style="margin-top:10px"><b>{c} cycle</b> '
                f'&middot; 1 Jan – 31 Dec</div>'
                + _cycle_bar(doj, c)
                + '<div class="months">'
                + "".join(f"<div>{m}</div>" for m in MONTHS) + "</div>")

        body = ["<tr><th>Cycle</th><th>Completed months<br>at 31 Dec</th>"
                "<th>Band</th><th>Annual — allocated and usable</th>"
                "<th>Medical — allocated and usable</th></tr>"]
        prev_al = None
        for t in traces:
            arrow = ""
            if prev_al is not None and t["al_days"] is not None:
                d = t["al_days"] - prev_al
                if d < 0:
                    arrow = f' <span class="down">▼ {d:g}</span>'
                elif d > 0:
                    arrow = f' <span class="up">▲ +{d:g}</span>'
            prev_al = t["al_days"] if t["al_days"] is not None else prev_al
            body.append(
                f"<tr><td class='d'><b>{t['cycle']}</b></td>"
                f"<td class='d'>{t['months']}</td>"
                f"<td class='d'>{t['band']}</td>"
                f"<td>{_fmt(t['al_days'])}{arrow}<div class='small'>{t['al_note']}</div></td>"
                f"<td>{_fmt(t['mc_days'])}<div class='small'>{t['mc_note']}</div></td></tr>")

        arch_html.append(
            f'<div class="arch"><h3>{title}</h3>'
            f'<p class="lead">Joining date <b>{getdate(doj).strftime("%-d %B %Y")}</b>'
            f' &middot; first anniversary '
            f'<b>{anniversary(doj).strftime("%-d %B %Y")}</b><br>{lead}</p>'
            f'<div class="wrap"><table style="min-width:820px">'
            + "".join(body) + "</table></div>"
            + "".join(bars) + "</div>")

    # ── bands ──────────────────────────────────────────────────────────────
    band_rows = "".join(
        f"<tr><td><b>{t}</b><div class='small'>{pol} &middot; {st}</div></td>"
        f"<td class='d'>{span}</td><td>{al}</td><td>{mc}</td></tr>"
        for t, span, al, mc, pol, st in _band_table())

    # ── mismatches ─────────────────────────────────────────────────────────
    if mism:
        mm = "".join(
            f"<tr><td>{m['name']}<div class='small'>{m['status']} &middot; "
            f"joined {m['joined']} &middot; {m['months']} months &middot; "
            f"{m['band']}</div></td>"
            f"<td class='d'>{m['kind']}</td>"
            f"<td class='d'>{_fmt(m['calc'])}</td>"
            f"<td class='d hit'>{_fmt(m['actual'])}</td>"
            f"<td class='d'>{m['diff']:+g}</td></tr>"
            for m in mism)
        mism_html = (
            "<div class='wrap'><table style='min-width:760px'>"
            "<tr><th>Employee</th><th>Leave</th><th>The rule gives</th>"
            "<th>ERPNext holds</th><th>Difference</th></tr>" + mm + "</table></div>")
    else:
        mism_html = "<p class='note'>None — every recorded allocation matches the rule.</p>"

    # ── the seven ──────────────────────────────────────────────────────────
    add_rows = "".join(
        f"<tr><td>{a['name']}<div class='small'>{a['employee']} &middot; "
        f"{a['dept']} &middot; {a['status']}</div></td>"
        f"<td class='d'>{a['joined']}</td>"
        f"<td class='d'>{a['months'] if a['months'] is not None else '—'}</td>"
        f"<td class='d'>{_fmt(a['al']['days']) if a['al'] else 'none this cycle'}</td>"
        f"<td class='d'>{_fmt(a['mc']['days']) if a['mc'] else 'none this cycle'}</td></tr>"
        for a in adds)

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CAF — Leave entitlement, for HR sign-off</title>
<style>{CSS}{EXTRA_CSS}</style></head><body>

<h1>Leave entitlement — what the rules produce</h1>
<p class="sub">Prepared for Chen Xiao Natalie &middot; {date.today():%-d %B %Y}
&middot; confirms the answers given on 4 September 2026</p>

<div class="cards">
  <div class="card green"><div class="n">{n_have}</div>
    <div class="l">active employees who hold a {CYCLE} allocation today</div></div>
  <div class="card amber"><div class="n">{len(adds)}</div>
    <div class="l">you named as entitled but holding nothing yet</div></div>
  <div class="card"><div class="n">{n_none - len(adds)}</div>
    <div class="l">confirmed as having no leave entitlement</div></div>
  <div class="card red"><div class="n">{len(mism)}</div>
    <div class="l">recorded numbers that differ from the rule</div></div>
</div>

<div class="note">
<b>What this page is for.</b> You confirmed four things verbally. Each one is a
short sentence with a long consequence, and this page shows the consequence in
days so that what you are signing is the <i>effect</i>, not the wording.
Nothing here has been applied to anybody's leave — the allocation run has not
been armed.
</div>

<h2>1 &middot; The CAF leave cycle</h2>
<p>One cycle for everybody: <b>1 January to 31 December</b>. Two dates decide
what a person gets in it.</p>
<div class="wrap"><table style="min-width:700px">
<tr><th>Date</th><th>What happens</th></tr>
<tr><td class="d"><b>1 January</b></td>
    <td>The cycle opens. ERPNext creates the year's Leave Allocations. Medical
        leave becomes usable immediately for anyone already employed.</td></tr>
<tr><td class="d"><b>the employee's<br>joining anniversary</b></td>
    <td>Annual leave becomes usable — <b>not before</b>. For somebody in their
        first year this date falls in the NEXT cycle, so they have no annual
        leave at all this year.</td></tr>
<tr><td class="d"><b>31 December</b></td>
    <td>The cycle closes and <b>every unused day is lost</b>. CAF carries
        nothing over, at any length of service.</td></tr>
<tr><td class="d"><b>1 November</b></td>
    <td>ERPNext prepares the next year — the holiday list for you to fill in,
        the leave period, and the twelve appraisal cycles — and sends you a
        reminder. It does not decide anything on its own.</td></tr>
</table></div>

<h2>2 &middot; The three bands you confirmed</h2>
<p>Service is measured from the joining date to <b>31 December of the cycle
being allocated</b> — the end of the year, not the start of it. Somebody who
joined in July 2025 therefore has 17 months of service for the 2026 cycle, not
five.</p>
<div class="wrap"><table style="min-width:820px">
<tr><th>Band / Leave Policy</th><th>Service at 31 Dec</th>
    <th>Annual</th><th>Medical</th></tr>
{band_rows}
</table></div>
<div class="note warn">
<b>Medical caps at 14 below two years.</b> You confirmed this on 4 September:
<i>"prorate formula up to 12 months, after that constant cap at 14 days till end
of 2 years period. After 2 years switch to another band."</i> That is what the
build does. Before this it was recorded only as something the data appeared to
show, with a note that it needed confirming — it is now a rule.
</div>

<h2>3 &middot; Four people, three years each</h2>
<p>Same rules, four different joining dates. The bar under each cycle shows
<b>when in the year</b> each allowance opens — an allocation that opens in
December is not the same as one that opens in January, because nothing carries
over.</p>
{"".join(arch_html)}

<div class="note stop">
<b>🔴 The late-December joiner is the case that still needs your decision.</b>
Look at the third example. In the cycle they join, they get nothing at all. In
the following cycle they are allocated <b>8 annual days on 15 December</b> —
and the cycle ends on the 31st. Sixteen days to take eight days of leave, after
which they expire.
<br><br>
This is not a mistake in the formula. It is what the four rules say together:
annual opens on the anniversary, the cycle ends on 31 December, and nothing
carries over. <code>LEAVE_LATE_JOINER_for_HR_decision.html</code> asked about
this on 13 August and has not been answered. <b>While it is unanswered, the
days expire.</b>
</div>

<h2>4 &middot; Why annual DROPS at two years</h2>
<p>You confirmed this is intended: <i>"yes, will drop when transition from under
2 years band to 2 to 5 band … as bonus or interest due to the no apply on first
year policy."</i> The fourth example above shows it. In numbers, at the moment
of transition:</p>
<div class="wrap"><table style="min-width:640px">
<tr><th>Service at 31 Dec</th><th>Annual</th><th>Medical</th><th>What changed</th></tr>
<tr><td class="d">23 months</td><td class="d">15</td><td class="d">14</td>
    <td>still on the under-2-years formula (23 ÷ 12 × 8 = 15.33, rounded down
        to 15)</td></tr>
<tr><td class="d">24 months</td><td class="d"><span class="down">12</span></td>
    <td class="d"><span class="up">18</span></td>
    <td>the flat 2-to-5-years band takes over: annual <b>falls by 3</b>,
        medical <b>rises by 4</b></td></tr>
</table></div>
<div class="note">
The reason the under-2-years number can exceed the band is that the formula
multiplies by <b>8</b> and keeps counting past twelve months, so at 23 months it
has reached 15. That is the "interest" — it compensates for the first year, in
which annual leave was allocated on paper but could not be taken.
</div>

<h2>5 &middot; The seven you named</h2>
<p>On 4 September you confirmed these employees have leave entitlement, and that
everyone else currently without an allocation has none. These are the numbers
the rules give them for {CYCLE}, if we proceed.</p>
<div class="wrap"><table style="min-width:820px">
<tr><th>Employee</th><th>Joined</th><th>Months at 31 Dec</th>
    <th>Annual {CYCLE}</th><th>Medical {CYCLE}</th></tr>
{add_rows}
</table></div>
<div class="note warn">
All seven joined during {CYCLE} or in January of it, so <b>none of them gets any
annual leave this year</b> — their first anniversary has not arrived. What they
receive now is medical leave, pro-rated from their joining date.
</div>

<h2>6 &middot; {len(mism)} recorded numbers that differ from the rule</h2>
<p>These are allocations already in ERPNext, entered by hand, that do not match
what the rules produce. They are shown so you can say which is right — the rule
or the record. <b>Nothing has been changed.</b></p>
{mism_html}

<div class="decide">
<h3>Please mark each one</h3>
<p>For every row above: is the <b>recorded</b> number correct (and the rule needs
an exception), or is the <b>rule</b> correct (and the record should be
corrected)?</p>
</div>

<h2>7 &middot; What you are signing</h2>
<div class="wrap"><table style="min-width:760px">
<tr><th></th><th>The statement</th><th>Where it shows up</th></tr>
<tr><td class="d">1</td><td>Three service bands — under 2 years, 2 to 5 years,
    over 5 years — with three matching Leave Policies.</td>
    <td>section 2</td></tr>
<tr><td class="d">2</td><td>Under two years, annual and medical are pro-rated by
    completed months, rounded down to the half day.</td><td>section 2</td></tr>
<tr><td class="d">3</td><td>Medical is capped at <b>14 days</b> for anyone under
    two years, however long they have served.</td><td>section 2</td></tr>
<tr><td class="d">4</td><td>An employee with under <b>one year</b> of service may
    not take annual leave — only medical or unpaid.</td>
    <td>sections 1 and 3</td></tr>
<tr><td class="d">5</td><td>Annual <b>falls</b> from up to 15 days to 12 at the
    two-year transition, and that is intended.</td><td>section 4</td></tr>
<tr><td class="d">6</td><td><b>Nothing carries over.</b> Unused days are lost on
    31 December.</td><td>section 1</td></tr>
<tr><td class="d">7</td><td>The seven employees in section 5 are entitled;
    everyone else currently without an allocation is not.</td>
    <td>section 5</td></tr>
</table></div>

<div class="sign">
<p><b>Signed off by</b> <span class="line"></span>
&nbsp;&nbsp;<b>Date</b> <span class="line" style="min-width:140px"></span></p>
<p class="small">Still open, and not covered by this signature: the late-December
joiner (section 3), and the {len(mism)} rows in section 6.</p>
</div>

<p class="small">Generated by
<code>caf.scripts.leave_entitlement_signoff_html.write</code> from the live test
server. Every number in sections 3, 5 and 6 is produced by the same code that
will perform the allocation.</p>
</body></html>"""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"wrote {path}")
    print(f"  active                    : {n_active}")
    print(f"  hold a {CYCLE} allocation   : {n_have}")
    print(f"  named by HR as entitled   : {len(adds)}")
    print(f"  confirmed NOT entitled    : {n_none - len(adds)}")
    print(f"  rule/record mismatches    : {len(mism)}")
    for m in mism:
        print(f"    {m['name'][:34]:34s} {m['kind']:7s} rule {m['calc']:>5} "
              f"vs record {m['actual']:>5}  ({m['diff']:+g})")
    return {"mismatches": len(mism), "additions": len(adds)}
