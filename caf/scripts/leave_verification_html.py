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
            f'<td>{label[r["bucket"]]}</td><td class="small">{extra}</td>'
            f'<td class="ansbox"></td></tr>')

    doc = TEMPLATE.format(
        generated=date.today().strftime("%d %B %Y"),
        al_ok=al_ok, al_n=al_n, mc_ok=mc_ok, mc_n=mc_n,
        n_agree=n_agree, n_diff=n_diff, n_inst=n_inst, n_nolink=n_nolink,
        n_total=len(jr), rows1="\n".join(t1), rows2="\n".join(t2))

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
<p class="small">If either is wrong, say so — every figure in the next table depends on them.</p>
</div>

<h2>2 · Every 2026 entitlement, calculated against actual</h2>
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

<h2>3 · Joining dates — Ingress against ERPNext</h2>
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
<th>Status</th><th>Effect on 2026 leave</th><th>Correct date</th></tr></thead>
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
