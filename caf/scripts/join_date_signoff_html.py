"""The joining-date sign-off page for HR — all active employees, three sources.

    bench --site <site> execute caf.scripts.join_date_signoff_html.write

MG, 2026-09-03: *"the logical step is to get HR Manager to manually sign off…
make a new .html with the full 80++ list and highlight the ones that are vague to
confirm (where Ingress, emp.join_date and the first log all conflict)."*

🔴 WHY THIS PAGE EXISTS RATHER THAN A COPY FROM INGRESS
-------------------------------------------------------
HR has confirmed she updated `ingress.user.IssueDate` to the joining date, and
the plan is to push ERPNext's dates to production. Both are reasonable. The page
exists because **`IssueDate` is not always a joining date, for reasons that have
nothing to do with HR's care**:

  · **FBR49** — `attendance` is materialised only when somebody RUNS a date range
    in Ingress. For some employees `IssueDate` ends up equal to the first
    *materialised* day, which can be months after they joined.
    Measured 2026-09-03: **Nur Syamimi** (ERP 2025-03-17 vs Ingress 2025-08-01)
    and **Nur Aida Basirah** (ERP 2025-08-04 vs Ingress 2025-12-01).
  · **2022-03-01** is the day Ingress was INSTALLED, written onto everybody
    already employed. For those people Ingress has nothing to say at all.
  · a replaced device resets the tap history — `810 Md Sultan` joined 2018 and
    his earliest tap is 2022-04-13.

So the page shows **all three sources side by side** and asks HR only about the
rows where they disagree. Everything that agrees is listed for completeness and
needs one signature, not 89 decisions.

⚠️ READ-ONLY. It writes an HTML file and never touches the site.
"""

import os

import frappe
from frappe.utils import getdate

from caf.caf.ingress import source as src

OUT = ("/workspace/development/frappe-bench/apps/caf/"
       "JOIN_DATE_for_HR_signoff.html")

INSTALL_DAY = "2022-03-01"      # the day Ingress was installed on all existing staff

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e2e2e2;--head:#f7f7f8;
      --red:#b3261e;--redbg:#fdecea;--amber:#8a5a00;--amberbg:#fff6e5;
      --green:#1b5e20;--greenbg:#eaf4ea;--blue:#0b4f9e;--bluebg:#eaf1fb}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--bg);color:var(--fg);
     font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
h1{font-size:23px;margin:0 0 4px} h2{font-size:18px;margin:34px 0 8px}
.sub{color:var(--muted);margin:0 0 22px}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0 26px}
.card{flex:1 1 150px;border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card .n{font-size:26px;font-weight:600;line-height:1.1}
.card .l{color:var(--muted);font-size:13px;margin-top:2px}
.card.red{background:var(--redbg);border-color:#f3c8c4}
.card.amber{background:var(--amberbg);border-color:#f0dcae}
.card.green{background:var(--greenbg);border-color:#c9e0c9}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:8px}
table{border-collapse:collapse;width:100%;min-width:900px;font-size:14px}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:var(--head);font-weight:600;position:sticky;top:0}
td.why{color:#333;font-size:13px}
td.d{white-space:nowrap;font-variant-numeric:tabular-nums}
.hit{background:var(--redbg);font-weight:600}
.ok{color:var(--muted)}
.tag{display:inline-block;padding:1px 8px;border-radius:11px;font-size:12px;
     font-weight:600;white-space:nowrap}
.t-conflict{background:var(--redbg);color:var(--red)}
.t-mute{background:var(--amberbg);color:var(--amber)}
.t-agree{background:var(--greenbg);color:var(--green)}
.note{border-left:3px solid var(--line);padding:2px 0 2px 14px;margin:14px 0;color:#333}
.note.warn{border-color:#e0a800}
.note.stop{border-color:var(--red)}
.decide{border:1px solid var(--line);border-radius:8px;padding:4px 16px;
        background:#fafafa;margin:16px 0}
.sign{border:2px solid var(--line);border-radius:8px;padding:14px 18px;margin:26px 0}
.sign .line{display:inline-block;border-bottom:1px solid #999;min-width:230px;
            margin:0 10px}
code{background:#f2f2f3;padding:1px 5px;border-radius:4px;font-size:13px}
.small{font-size:13px;color:var(--muted)}
@media print{body{padding:0} th{position:static}}
"""


def _ingress_rows():
    """{userid: (IssueDate, CreateDate, first_raw_tap)} straight from the machine."""
    reader = src.get_source()
    out = {}
    with reader._cursor() as cur:
        cur.execute("SELECT userid, IssueDate, CreateDate FROM `user`")
        for uid, issue, created in cur.fetchall():
            out[str(uid)] = [issue, created, None]
        # 🔴 auditdata is the honest witness — the raw tap, never touched by an
        # HR edit. One grouped query rather than 89 round trips.
        cur.execute("SELECT userid, MIN(checktime) FROM auditdata GROUP BY userid")
        for uid, first in cur.fetchall():
            if str(uid) in out:
                out[str(uid)][2] = first
    return out


def _d(v):
    if not v:
        return None
    try:
        return getdate(v)
    except Exception:
        return None


def classify():
    """One row per active employee, with the verdict HR is being asked about."""
    ing = _ingress_rows()
    rows = []
    for e in frappe.get_all(
            "Employee", filters={"status": "Active"},
            fields=["name", "employee_name", "date_of_joining",
                    "attendance_device_id", "department"],
            order_by="employee_name"):
        tag = e.attendance_device_id and str(e.attendance_device_id) or ""
        issue, created, tap = (ing.get(tag) or [None, None, None])
        erp, issue, created, tap = (_d(e.date_of_joining), _d(issue),
                                    _d(created), _d(tap))

        if not tag or tag not in ing:
            klass, why = "mute", ("No Ingress account is linked to this employee, "
                                  "so the machine has nothing to say. ERPNext is "
                                  "the only source.")
        elif issue and str(issue) == INSTALL_DAY:
            klass, why = "mute", (f"Ingress says {INSTALL_DAY} — the day Ingress "
                                  f"was installed. It was written onto everyone "
                                  f"already employed, so it is not a joining date.")
        elif not erp:
            klass, why = "conflict", "ERPNext has no joining date at all."
        elif issue and erp == issue:
            klass, why = "agree", "ERPNext and Ingress agree."
        elif not issue:
            klass, why = "mute", "Ingress holds no issue date for this account."
        else:
            gap = abs((erp - issue).days)
            if tap and erp == tap:
                klass = "conflict"
                why = (f"ERPNext matches the machine's FIRST TAP exactly; Ingress "
                       f"is {gap} days later and looks like the first day somebody "
                       f"processed in Ingress, not a joining date.")
            elif tap and issue == tap:
                klass = "conflict"
                why = (f"Ingress matches the machine's FIRST TAP exactly; ERPNext "
                       f"is {gap} days out.")
            else:
                klass = "conflict"
                why = f"The two disagree by {gap} days and the taps settle neither."
        rows.append({"emp": e.name, "who": e.employee_name, "dept": e.department,
                     "tag": tag, "erp": erp, "issue": issue, "created": created,
                     "tap": tap, "klass": klass, "why": why})
    return rows


def _cell(value, highlight=False):
    if value is None:
        return '<td class="d ok">—</td>'
    cls = "d hit" if highlight else "d"
    return f'<td class="{cls}">{value}</td>'


def _table(rows, show_why=True):
    head = ("<div class='wrap'><table><tr><th>Employee</th><th>Device</th>"
            "<th>ERPNext<br>joining date</th><th>Ingress<br>IssueDate</th>"
            "<th>Ingress<br>account created</th><th>First finger<br>tap</th>"
            + ("<th>What the difference is</th>" if show_why else "") + "</tr>")
    body = []
    for r in rows:
        clash = r["klass"] == "conflict"
        body.append(
            "<tr>"
            f"<td>{frappe.utils.escape_html(r['who'] or r['emp'])}</td>"
            f"<td class='d ok'>{r['tag'] or '—'}</td>"
            + _cell(r["erp"], clash)
            + _cell(r["issue"], clash)
            + _cell(r["created"])
            + _cell(r["tap"])
            + (f"<td class='why'>{r['why']}</td>" if show_why else "")
            + "</tr>")
    return head + "".join(body) + "</table></div>"


def write(path=None):
    frappe.set_user("Administrator")
    rows = classify()
    conflict = [r for r in rows if r["klass"] == "conflict"]
    mute = [r for r in rows if r["klass"] == "mute"]
    agree = [r for r in rows if r["klass"] == "agree"]

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Joining dates — for HR sign-off</title><style>{CSS}</style></head><body>

<h1>Joining dates — please check and sign off</h1>
<p class="sub">All {len(rows)} active employees &middot; ERPNext, Ingress and the
fingerprint machine compared side by side &middot; generated
{frappe.utils.nowdate()}</p>

<div class="cards">
  <div class="card red"><div class="n">{len(conflict)}</div>
    <div class="l">need your decision</div></div>
  <div class="card amber"><div class="n">{len(mute)}</div>
    <div class="l">Ingress cannot help</div></div>
  <div class="card green"><div class="n">{len(agree)}</div>
    <div class="l">all sources agree</div></div>
</div>

<div class="note stop"><b>Why we are asking, when you have already checked
Ingress.</b> You confirmed that <code>IssueDate</code> in Ingress has been set to
each person's joining date, and for most people the two now agree exactly. But
<code>IssueDate</code> is not <i>only</i> written when somebody joins, and there
are three situations where it says something else through no fault of anyone:
<ul>
<li><b>The first day somebody ran the reports.</b> Ingress only builds a day's
attendance when a person asks it to. For a few employees <code>IssueDate</code>
ended up equal to that first processed day, which can be months after they
started.</li>
<li><b>1 March 2022</b> — the day Ingress was installed. It was written onto
everybody who already worked here, so for those people it is an installation
date, not a joining date.</li>
<li><b>A replaced reader.</b> When a device is swapped the old taps do not come
across, so the machine's earliest tap can be years after the person joined.</li>
</ul>
That is why the table shows the <b>first finger tap</b> as well: it is the one
value nobody can edit, so where it agrees with a date, that date is very likely
right.</div>

<h2>1 &middot; Need your decision — {len(conflict)}</h2>
<p class="sub">The three sources disagree. The highlighted cells are the two that
differ; please tick the one that is the real joining date, or write the correct
one.</p>
{_table(conflict) if conflict else "<p class='note'>None — every linked employee agrees.</p>"}

<div class="decide"><p><b>For each row above, please mark:</b> is the ERPNext date
correct, the Ingress date correct, or neither? If neither, write the right one.
<br><span class="small">A joining date decides how much annual and medical leave
someone is entitled to this year, and the exact day their first year of service
completes &mdash; which is the day they may start taking annual leave. A date
that is a few months out changes both.</span></p></div>

<h2>2 &middot; Ingress cannot help with these — {len(mute)}</h2>
<p class="sub">Either no Ingress account is linked, or Ingress holds the
installation date. <b>ERPNext is the only source</b>, so please confirm these
dates from your own records.</p>
{_table(mute) if mute else "<p class='note'>None.</p>"}

<h2>3 &middot; Everything agrees — {len(agree)}</h2>
<p class="sub">ERPNext and Ingress hold the same date. Listed so nothing is
hidden; no decision needed unless one looks wrong to you.</p>
{_table(agree, show_why=False) if agree else "<p class='note'>None.</p>"}

<div class="sign">
<p><b>Sign-off.</b> I confirm the joining dates above are correct, and that the
ones marked in section 1 have been decided as noted.</p>
<p>Name <span class="line"></span> &nbsp; Signature <span class="line"></span>
&nbsp; Date <span class="line" style="min-width:130px"></span></p>
</div>

<div class="note warn"><b>What happens next.</b> Once signed, these dates are
copied to the production server, replacing what is there now. From that point
Ingress has no further say &mdash; the joining date is kept in ERPNext only, and
changing it is an ERPNext job.</div>

</body></html>"""

    path = path or OUT
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {path}")
    print(f"  need a decision : {len(conflict)}")
    for r in conflict:
        print(f"     {r['who']:<34} ERP {r['erp']}  Ingress {r['issue']}  "
              f"tap {r['tap']}")
    print(f"  Ingress mute    : {len(mute)}")
    print(f"  agree           : {len(agree)}")
    return {"conflict": len(conflict), "mute": len(mute), "agree": len(agree)}
