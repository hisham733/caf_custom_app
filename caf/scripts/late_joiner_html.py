"""OD-79 for HR — the late-year joiner's annual leave. Generates the HTML page.

Purpose : put ONE decision to HR in business language, with the numbers pulled
          live so the page cannot drift from the data.
Run     : bench --site <site> execute caf.scripts.late_joiner_html.write
          then  docker cp frappe:/tmp/LEAVE_LATE_JOINER_for_HR_decision.html .
Refs    : framework §6.15 · OD-79 · roadmap §9e · test LA-LATE

MG, 2026-08-13: *"create a .html to ask HR, ensure this .html has illustration."*
⚠️ **Illustrations are inline SVG, deliberately.** Mermaid `flowchart` with
`subgraph` did not render in MG's viewer, and an HR page must not depend on a
renderer at all — it is opened from a file, possibly printed.

Changelog
---------
1.0  2026-08-13  Initial — OD-79
"""

from datetime import date, timedelta

import frappe
from frappe.utils import getdate

from caf.caf.leave_allocation import late_opening_grants, start_for, ANNUAL
from caf.scripts.leave_formula import entitlement

CYCLE = 2026
OUT = f"/tmp/LEAVE_LATE_JOINER_for_HR_decision.html"

CSS = """
  :root{
    --bg:#ffffff; --fg:#1a1a1a; --muted:#5c5c5c; --line:#d8d8d8;
    --card:#f7f7f5; --accent:#8a3b00; --red:#a41b1b; --amber:#8a5a00;
    --green:#1d6b2f; --box:#fffdf5; --boxline:#c9a227; --dim:#c9c9c4;
  }
  @media (prefers-color-scheme: dark){
    :root{
      --bg:#161615; --fg:#eeeeec; --muted:#a5a59f; --line:#3a3a38;
      --card:#1f1f1e; --accent:#e0a06a; --red:#ef8080; --amber:#e0b64a;
      --green:#7ec98d; --box:#242320; --boxline:#7a6520; --dim:#4a4a46;
    }
  }
  *{box-sizing:border-box}
  body{margin:0;padding:2rem 1.25rem 5rem;background:var(--bg);color:var(--fg);
       font:16px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:60rem;margin:0 auto}
  h1{font-size:1.8rem;line-height:1.25;margin:0 0 .4rem}
  h2{font-size:1.25rem;margin:2.6rem 0 .6rem;padding-top:1.1rem;border-top:2px solid var(--line)}
  h3{font-size:1.05rem;margin:1.5rem 0 .4rem}
  p,li{margin:.55rem 0}
  .sub{color:var(--muted);margin:0 0 1.6rem;font-size:.95rem}
  .lead{background:var(--card);border-left:4px solid var(--accent);padding:1rem 1.2rem;
        border-radius:0 6px 6px 0;margin:1.5rem 0}
  table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.92rem}
  th,td{border:1px solid var(--line);padding:.42rem .6rem;text-align:left;vertical-align:top}
  th{background:var(--card);font-weight:600}
  td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
  .scroll{overflow-x:auto}
  .q{border:1px solid var(--line);border-radius:8px;padding:1.1rem 1.25rem;margin:1.4rem 0;
     background:var(--card)}
  .q h3{margin-top:0}
  .tag{display:inline-block;font-size:.72rem;font-weight:700;letter-spacing:.06em;
       padding:.16rem .5rem;border-radius:3px;margin-right:.5rem;vertical-align:.12em}
  .t-red{background:var(--red);color:#fff}
  .t-amb{background:var(--amber);color:#fff}
  .row{display:grid;grid-template-columns:9.5rem 1fr;gap:.3rem .9rem;margin:.7rem 0}
  .row b{color:var(--muted);font-weight:600;font-size:.86rem;text-transform:uppercase;
         letter-spacing:.03em}
  .ans{background:var(--box);border:1px dashed var(--boxline);border-radius:6px;
       padding:.85rem 1rem;margin-top:.9rem}
  .ans b{display:block;font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;
         color:var(--muted);margin-bottom:.5rem}
  .ans .lines{min-height:3.6em;border-bottom:1px solid var(--line);
              box-shadow:0 1.2em 0 -1px var(--line), 0 2.4em 0 -1px var(--line)}
  .sug{font-size:.9rem;color:var(--muted);margin-top:.55rem}
  .sug em{color:var(--green);font-style:normal;font-weight:600}
  .ok{color:var(--green);font-weight:600}
  .bad{color:var(--red);font-weight:600}
  .note{font-size:.9rem;color:var(--muted)}
  figure{margin:1.6rem 0;padding:1rem;background:var(--card);border:1px solid var(--line);
         border-radius:8px}
  figcaption{font-size:.88rem;color:var(--muted);margin-top:.7rem;text-align:center}
  svg{display:block;width:100%;height:auto}
  .pick{display:grid;grid-template-columns:repeat(3,1fr);gap:.9rem;margin:1.2rem 0}
  .pick div{border:1px solid var(--line);border-radius:8px;padding:.9rem;background:var(--bg)}
  .pick h4{margin:.1rem 0 .5rem;font-size:1rem}
  .pick .big{font-size:1.7rem;font-weight:700;font-variant-numeric:tabular-nums}
  @media (max-width:44rem){ .pick{grid-template-columns:1fr} }
  @media print{
    body{padding:0;font-size:11pt}
    .q{break-inside:avoid} table{break-inside:avoid} figure{break-inside:avoid}
    h2{break-after:avoid}
    :root{--bg:#fff;--fg:#000;--card:#f4f4f4;--box:#fffdf0;--dim:#ccc}
  }
"""


def workdays(emp, start, end):
    """Real working days for THIS employee, from the resolved shift.

    ⚠️ `resolve_day_type` returns a TUPLE. Comparing it to a string silently
    yields 0 for everybody, which is exactly what happened the first time and
    is why the label set is asserted below rather than trusted.
    """
    from caf.caf.shift_resolution import resolve_day_type
    n, d, seen = 0, getdate(start), set()
    end = getdate(end)
    while d <= end:
        r = resolve_day_type(emp, d)
        dt = r[0] if isinstance(r, (tuple, list)) else r
        seen.add(dt)
        if dt == "Workday":
            n += 1
        d += timedelta(days=1)
    if "Workday" not in seen:
        frappe.throw(f"resolve_day_type never returned 'Workday' for {emp} "
                     f"— saw {seen}. Refusing to publish a zero.")
    return n


def affected(cycle=CYCLE):
    rows = []
    for r in late_opening_grants(cycle):
        emp = frappe.db.get_value("Employee", {"employee_name": r["name"]}, "name")
        if not emp:
            continue
        doj = frappe.db.get_value("Employee", emp, "date_of_joining")
        wd = workdays(emp, r["opens"], f"{cycle}-12-31")
        nxt = entitlement(doj, cycle + 1)
        rows.append({**r, "employee": emp, "workdays": wd,
                     "next_al": nxt["al"], "next_rule": nxt["rule"],
                     "share": r["days"] / wd if wd else None})
    return rows


def joining_months():
    m = {}
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["date_of_joining"]):
        if e.date_of_joining:
            k = getdate(e.date_of_joining).month
            m[k] = m.get(k, 0) + 1
    return m


# ------------------------------------------------------------------ the SVGs
def svg_windows(name, doj, cycle, al_this, al_next):
    """MG's own mental model: two service windows, each ending 31 December."""
    x0, x1, w = 120, 940, 820
    return f"""
<svg viewBox="0 0 980 250" role="img" aria-label="Two service windows">
  <style>
    .lbl{{fill:var(--muted);font:13px sans-serif}}
    .val{{fill:var(--fg);font:600 13px sans-serif}}
    .yr{{fill:var(--muted);font:600 12px sans-serif;letter-spacing:.08em}}
    .bar1{{fill:var(--accent);opacity:.85}}
    .bar2{{fill:var(--accent);opacity:.55}}
    .ax{{stroke:var(--line);stroke-width:1}}
    .jn{{stroke:var(--red);stroke-width:2}}
  </style>
  <text x="0" y="20" class="val">{name} — joined {doj}</text>
  <line x1="{x0}" y1="40" x2="{x0}" y2="215" class="jn"/>
  <text x="{x0 + 5}" y="38" class="lbl" fill="var(--red)">joined</text>

  <text x="0" y="80" class="lbl">window for {cycle}</text>
  <rect x="{x0}" y="65" width="{int(w * 0.45)}" height="22" rx="3" class="bar1"/>
  <text x="{x0 + int(w * 0.45) + 8}" y="81" class="val">➜ 31 Dec {cycle}  =  AL {al_this:g}</text>

  <text x="0" y="130" class="lbl">window for {cycle + 1}</text>
  <rect x="{x0}" y="115" width="{int(w * 0.92)}" height="22" rx="3" class="bar2"/>
  <text x="{x0 + int(w * 0.92) + 8}" y="131" class="val">➜ AL {al_next:g}</text>

  <line x1="{x0}" y1="170" x2="{x1}" y2="170" class="ax"/>
  <line x1="{x0 + int(w * 0.45)}" y1="163" x2="{x0 + int(w * 0.45)}" y2="177" class="ax"/>
  <text x="{x0 + int(w * 0.2)}" y="192" class="yr">HR CYCLE {cycle}</text>
  <text x="{x0 + int(w * 0.62)}" y="192" class="yr">HR CYCLE {cycle + 1}</text>
  <text x="{x0}" y="215" class="lbl">The number is earned across the whole bar.</text>
</svg>"""


def svg_usable(name, opens, cycle, days, wd):
    """The same year, but showing WHEN the earned days can actually be taken."""
    x0, w = 120, 800
    frac = (date(cycle, 12, 31) - getdate(opens)).days / 365.0
    open_x = x0 + int(w * (1 - frac))
    return f"""
<svg viewBox="0 0 980 230" role="img" aria-label="When the leave can be taken">
  <style>
    .lbl{{fill:var(--muted);font:13px sans-serif}}
    .val{{fill:var(--fg);font:600 13px sans-serif}}
    .mo{{fill:var(--muted);font:11px sans-serif}}
    .mc{{fill:var(--green);opacity:.8}}
    .locked{{fill:var(--dim)}}
    .open{{fill:var(--red);opacity:.9}}
  </style>
  <text x="0" y="20" class="val">{name} — HR cycle {cycle}</text>

  <text x="0" y="62" class="lbl">MEDICAL</text>
  <rect x="{x0}" y="47" width="{w}" height="22" rx="3" class="mc"/>
  <text x="{x0 + 10}" y="63" fill="#fff" style="font:600 12px sans-serif">
    usable all year — no problem</text>

  <text x="0" y="112" class="lbl">ANNUAL</text>
  <rect x="{x0}" y="97" width="{open_x - x0}" height="22" rx="3" class="locked"/>
  <text x="{x0 + 10}" y="113" class="lbl">earned month by month — but cannot be taken yet</text>
  <rect x="{open_x}" y="97" width="{x0 + w - open_x}" height="22" rx="3" class="open"/>

  <text x="{open_x}" y="141" class="val" fill="var(--red)">▲ {opens}</text>
  <text x="{open_x}" y="160" class="val" fill="var(--red)">{days:g} days unlock here</text>
  <text x="{open_x}" y="178" class="lbl">only {wd} working days left before they expire</text>

  <line x1="{x0}" y1="200" x2="{x0 + w}" y2="200" stroke="var(--line)"/>
  {''.join(f'<text x="{x0 + int(w * i / 12) + 2}" y="216" class="mo">{m}</text>'
           for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                                  "Aug", "Sep", "Oct", "Nov", "Dec"]))}
</svg>"""


def build(cycle=CYCLE):
    rows = affected(cycle)
    worst = rows[0]
    months = joining_months()
    total = sum(months.values())
    q4 = sum(months.get(m, 0) for m in (10, 11, 12))
    doj = str(getdate(frappe.db.get_value("Employee", worst["employee"], "date_of_joining")))
    al_this = worst["days"]
    al_next = worst["next_al"]

    tbl = "".join(
        f"<tr><td>{r['name']}</td><td>{r['joined']}</td><td>{r['opens']}</td>"
        f"<td class='n'>{r['days']:g}</td><td class='n'>{r['workdays']}</td>"
        f"<td class='n'>{r['share'] * 100:.0f}%</td></tr>"
        for r in rows if r["unusable"] or r["workdays"] < 120)

    mo_rows = "".join(
        f"<tr><td>{date(2026, m, 1).strftime('%B')}</td><td class='n'>{months.get(m, 0)}</td>"
        f"<td>{'<span class=bad>affected</span>' if m in (10, 11, 12) else ''}</td></tr>"
        for m in range(1, 13))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CAF — Annual leave for staff who join late in the year: one decision</title>
<style>{CSS}</style>
</head>
<body><div class="wrap">

<h1>Annual leave for staff who join late in the year</h1>
<p class="sub">One decision for HR &middot; prepared {date.today()} &middot; affects
{q4} of {total} current staff</p>

<div class="lead">
<p><b>What is happening.</b> Under the entitlement rule we agreed, a new employee
earns annual leave from their joining date, but cannot <em>take</em> any annual
leave until they have completed one year of service. For most staff that works
perfectly. For someone who joins in October, November or December, their first
annual leave unlocks in October, November or December of the following year
&mdash; and because CAF has no carry&#8209;over, whatever they have not taken by
31&nbsp;December is lost.</p>
<p><b>What harm it causes.</b> {worst['name']} has earned <b>{al_this:g} days</b>
of annual leave. They become available on <b>{worst['opens']}</b> and expire on
31&nbsp;December. That leaves <b>{worst['workdays']} working days</b> in which to
take {al_this:g} days of leave &mdash; about
<b>{worst['share'] * 100:.0f}%</b> of the time remaining. In practice the leave
is earned but cannot be used.</p>
<p><b>What we need from you.</b> One choice, at the end of this page. Nothing has
been changed in the system; we are following the approved formula until you
decide.</p>
</div>

<h2>1. How the number is earned</h2>
<p>Entitlement is calculated over a <b>service window</b> that runs from the
joining date to <b>31 December of the cycle</b>. That is why someone who joined
part-way through last year still earns a meaningful figure this year.</p>

<figure>
{svg_windows(worst['name'], doj, cycle, al_this, al_next)}
<figcaption>The window for {cycle} gives {al_this:g} days. From {cycle + 1} they
reach two years of service and move onto the flat band
({al_next:g} days).</figcaption>
</figure>

<h2>2. Why the days cannot be used</h2>
<p>The earning is spread across the whole year. The <em>permission to take</em>
annual leave arrives only at the one-year mark.</p>

<figure>
{svg_usable(worst['name'], worst['opens'], cycle, al_this, worst['workdays'])}
<figcaption>Medical leave is not affected &mdash; it starts from the joining date
and is usable all year. Only annual leave has the one-year wait, and that wait
is what pushes the window off the end of the year.</figcaption>
</figure>

<h2>3. Who this affects</h2>
<div class="scroll"><table>
<thead><tr><th>Employee</th><th>Joined</th><th>Annual leave unlocks</th>
<th class="n">Days earned</th><th class="n">Working days left</th>
<th class="n">Share of remaining time</th></tr></thead>
<tbody>{tbl}</tbody></table></div>

<p>And it is not a one-off. Of {total} active staff, <b>{q4} joined between
October and December</b> &mdash; every one of them meets this in their second
year, and every future intake in that period will too.</p>

<div class="scroll"><table>
<thead><tr><th>Joining month</th><th class="n">Current staff</th><th></th></tr></thead>
<tbody>{mo_rows}</tbody></table></div>

<p class="note">Note: this situation has never arisen in the records &mdash; no
annual leave allocation at CAF has ever begun later than 31 August. So there is
no existing practice to follow, which is why we are asking rather than assuming.</p>

<h2>4. The three options</h2>

<div class="pick">
  <div><h4>A &middot; Change nothing</h4>
    <div class="big bad">{al_this:g} days</div>
    <p class="note">granted on {worst['opens']}, expire 31 Dec. She sees them on
    her balance and almost certainly cannot use them.</p></div>
  <div><h4>B &middot; Skip the first grant</h4>
    <div class="big">0 days</div>
    <p class="note">no annual leave in {cycle}; the flat band starts
    {cycle + 1}. Honest, but she never receives what she earned.</p></div>
  <div><h4>C &middot; Give it in January</h4>
    <div class="big ok">{al_this + al_next:g} days</div>
    <p class="note">the {al_this:g} earned days are issued on 1 January
    {cycle + 1} together with that year's {al_next:g} &mdash; a full year to use
    them.</p></div>
</div>

<div class="scroll"><table>
<thead><tr><th>Option</th><th class="n">What she actually receives</th>
<th>Does it break &ldquo;no carry-over&rdquo;?</th><th>The cost</th></tr></thead>
<tbody>
<tr><td><b>A</b> &mdash; change nothing</td><td class="n">{al_next:g}</td>
<td>No</td><td>Shows leave on her balance that quietly disappears. The worst of
the three for trust.</td></tr>
<tr><td><b>B</b> &mdash; skip the first grant</td><td class="n">{al_next:g}</td>
<td>No</td><td>She loses {al_this:g} days she earned. At least it is visible and
honest.</td></tr>
<tr><td><b>C</b> &mdash; issue it in January</td>
<td class="n"><b>{al_this + al_next:g}</b></td>
<td>No &mdash; nothing is carried forward. The grant is simply <em>issued
later</em>, and every allocation still sits inside its own year.</td>
<td>In {cycle + 1} she holds {al_this + al_next:g} days, which is more than a
five-year employee&rsquo;s 16 in a single year. It is correct, but it will look
unusual on a balance report.</td></tr>
</tbody></table></div>

<div class="q">
<h3><span class="tag t-red">DECISION</span> Which option should CAF adopt?</h3>
<div class="row"><b>Applies to</b><div>Any employee whose first annual leave
would unlock in the last months of a year &mdash; currently {q4} of
{total} staff, and every future intake in that period.</div></div>
<div class="row"><b>If unanswered</b><div>Option A stands, because it is what the
approved formula does today.</div></div>
<p class="sug">Suggested: <em>Option C</em> &mdash; it is the only one where the
employee receives what she earned, and it does not breach the no-carry-over rule
because nothing is carried: the grant is issued in January instead of December.
If the {al_this + al_next:g}-day figure is unacceptable, Option&nbsp;B is the
coherent alternative &mdash; but please choose it knowing it removes
{al_this:g} earned days.</p>
<div class="ans"><b>HR answer</b><div class="lines"></div></div>
</div>

<div class="q">
<h3><span class="tag t-amb">RELATED</span> Should the same apply to medical leave?</h3>
<p>Today medical leave starts on the <b>joining date</b>, so a new employee has
sick leave from day one and this problem never arises. We believe that is
correct and are not proposing any change &mdash; but it is stated here so the
difference between the two leave types is a deliberate decision rather than an
accident.</p>
<p class="sug">Suggested: <em>no change</em> &mdash; medical leave should remain
available from the joining date.</p>
<div class="ans"><b>HR answer</b><div class="lines"></div></div>
</div>

<p class="note">Prepared from the live records on {date.today()}. Figures
recalculated directly from each employee&rsquo;s joining date and working
calendar &mdash; working days exclude that person&rsquo;s rest days and public
holidays.</p>

</div></body></html>"""


def write(cycle=CYCLE):
    html = build(cycle)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {OUT}  ({len(html):,} bytes)")
    for r in affected(cycle):
        print(f"   {r['name'][:32]:32s} {r['opens']}  {r['days']:g} days  "
              f"{r['workdays']} working days")
    return OUT
