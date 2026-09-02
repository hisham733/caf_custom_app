"""Which leave group is each employee in? Evidence, and what HR still must decide.

    bench --site <site> execute caf.scripts.leave_group_review.run
    bench --site <site> execute caf.scripts.leave_group_review.html

**Read-only. Writes nothing, ever.** It produces the list MG asked HR to confirm.

THE RULE THIS SERVES
--------------------
**FBR58** — the workforce is two groups: those WITH a leave allocation, and those
WITHOUT, for whom any day off is unpaid leave. An employee holding no allocation
is a deliberate category, not a data gap.

**FBR60** — `Leave Policy Assignment` is what will record the split. MG + HR,
2026-09-01. Today there are **0 assignments**, so nothing in the data says who is
in which group (T-14), and the allocation run for 58 people is blocked until it
does.

🔴 WHY THIS CANNOT SIMPLY BE INFERRED
-------------------------------------
The obvious shortcut — *"whoever already has an allocation is the allocated
group"* — is circular. It cannot tell **correctly unallocated** from **allocated
but not yet reached by HR**, and using it would freeze today's 31/58 split as if
somebody had decided it. So this script does not decide. It sorts people by *what
the evidence can and cannot settle*, and hands HR the short list.

THE EVIDENCE, AND WHY IT IS GOOD EVIDENCE
-----------------------------------------
Every Leave Type on this site carries `is_lwp`, and it splits cleanly:

    is_lwp = 1   Leave Without Pay · Emergency · Maternity · MC Without Pay ·
                 Others · PH Replacment            -> consumes NO allocation
    is_lwp = 0   Annual · MC · Marriage · Compassionate · …
                                                    -> consumes an allocation

So a **submitted** non-LWP leave is not an opinion about the person's group — it
is a record of them **spending entitlement they must therefore have had**. That
makes it the strongest single signal available, and it is independent of whether
anybody remembered to create the Leave Allocation document.

⚠️ The grouping is **NOT departmental** (FBR60). MG: *"although most production
(wet area / cooker) emp belongs to the group without allocation"* — most, not all,
and all 13 departments contain both. Department is shown for HR's orientation and
is never used to classify.
"""

import frappe
from frappe.utils import getdate, nowdate

# Verdicts, strongest evidence first.
ALLOCATED = "Allocated"
UNPAID = "Unpaid only"
CONFLICT = "Conflict"
UNKNOWN = "Unknown"


def _gather():
    lwp = {t.name: bool(t.is_lwp) for t in frappe.get_all(
        "Leave Type", fields=["name", "is_lwp"])}

    rows = {}
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "employee_name", "department",
                                    "date_of_joining", "designation"]):
        rows[e.name] = frappe._dict(
            emp=e.name, who=e.employee_name, dept=(e.department or "").replace(" - CAF", ""),
            joined=e.date_of_joining, designation=e.designation or "",
            alloc=[], paid_leave=0, paid_days=0.0, unpaid_leave=0, unpaid_days=0.0,
            paid_types=set(), last_leave=None)

    for a in frappe.get_all("Leave Allocation", filters={"docstatus": 1},
                            fields=["employee", "leave_type",
                                    "total_leaves_allocated", "to_date"]):
        if a.employee in rows:
            rows[a.employee].alloc.append(
                f"{a.leave_type} {a.total_leaves_allocated:g} (to {a.to_date})")

    for la in frappe.get_all("Leave Application", filters={"docstatus": 1},
                             fields=["employee", "leave_type", "total_leave_days",
                                     "from_date"]):
        r = rows.get(la.employee)
        if not r:
            continue
        if lwp.get(la.leave_type, True):
            r.unpaid_leave += 1
            r.unpaid_days += float(la.total_leave_days or 0)
        else:
            r.paid_leave += 1
            r.paid_days += float(la.total_leave_days or 0)
            r.paid_types.add(la.leave_type)
        if not r.last_leave or getdate(la.from_date) > getdate(r.last_leave):
            r.last_leave = la.from_date
    return rows


def classify(r):
    """(verdict, confidence, one-line reason). Never writes; never guesses silently."""
    if r.alloc and r.paid_leave:
        return (ALLOCATED, "certain",
                f"holds an allocation AND has spent it — {r.paid_leave} paid "
                f"leave(s), {r.paid_days:g} day(s) of {', '.join(sorted(r.paid_types))}")
    if r.alloc:
        return (ALLOCATED, "certain",
                f"holds a submitted Leave Allocation ({'; '.join(r.alloc)}) but has "
                f"not drawn on it yet")
    if r.paid_leave:
        return (CONFLICT, "needs HR",
                f"🔴 has taken {r.paid_days:g} day(s) of {', '.join(sorted(r.paid_types))} "
                f"— entitlement they were never formally allocated. Either they ARE "
                f"in the allocated group and the allocation is missing, or the leave "
                f"was filed under the wrong type")
    if r.unpaid_leave >= 3:
        return (UNPAID, "strong",
                f"no allocation, and {r.unpaid_leave} unpaid application(s) totalling "
                f"{r.unpaid_days:g} day(s) — has taken time off and always unpaid")
    if r.unpaid_leave:
        return (UNPAID, "weak",
                f"no allocation, and only {r.unpaid_leave} unpaid application(s) "
                f"({r.unpaid_days:g} day(s)) — consistent with the unpaid group, but "
                f"too little history to be sure")
    return (UNKNOWN, "none",
            "no allocation and no leave of any kind on record — nothing at all to "
            "reason from")


ORDER = {CONFLICT: 0, UNKNOWN: 1, UNPAID: 2, ALLOCATED: 3}
CONF_ORDER = {"needs HR": 0, "none": 1, "weak": 2, "strong": 3, "certain": 4}


def _classified():
    out = []
    for r in _gather().values():
        verdict, confidence, why = classify(r)
        out.append((verdict, confidence, why, r))
    out.sort(key=lambda t: (ORDER[t[0]], CONF_ORDER[t[1]], t[3].dept, t[3].who))
    return out


def run():
    frappe.set_user("Administrator")
    rows = _classified()

    tally = {}
    for verdict, confidence, _why, _r in rows:
        tally[(verdict, confidence)] = tally.get((verdict, confidence), 0) + 1

    print(f"{len(rows)} active employees\n")
    for (verdict, confidence), n in sorted(
            tally.items(), key=lambda kv: (ORDER[kv[0][0]], CONF_ORDER[kv[0][1]])):
        print(f"  {verdict:12s} {confidence:9s} {n:3d}")

    need = [t for t in rows if t[1] in ("needs HR", "none", "weak")]
    print(f"\n🔴 {len(need)} employee(s) HR must rule on:\n")
    for verdict, confidence, why, r in need:
        print(f"  {r.emp} {r.who[:30]:30s} {r.dept[:18]:18s} "
              f"joined {r.joined} — {verdict}/{confidence}")
        print(f"      {why}")
    return {"total": len(rows), "need_hr": len(need)}


# ------------------------------------------------------------------- the HTML

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
.card{flex:1 1 160px;border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card .n{font-size:26px;font-weight:600;line-height:1.1}
.card .l{color:var(--muted);font-size:13px;margin-top:2px}
.card.red{background:var(--redbg);border-color:#f3c8c4}
.card.amber{background:var(--amberbg);border-color:#f0dcae}
.card.green{background:var(--greenbg);border-color:#c9e0c9}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:8px}
table{border-collapse:collapse;width:100%;min-width:820px;font-size:14px}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:var(--head);font-weight:600;position:sticky;top:0}
td.why{color:#333;font-size:13px}
.tag{display:inline-block;padding:1px 8px;border-radius:11px;font-size:12px;
     font-weight:600;white-space:nowrap}
.t-conflict{background:var(--redbg);color:var(--red)}
.t-unknown{background:var(--amberbg);color:var(--amber)}
.t-unpaid{background:var(--bluebg);color:var(--blue)}
.t-allocated{background:var(--greenbg);color:var(--green)}
.note{border-left:3px solid var(--line);padding:2px 0 2px 14px;margin:14px 0;
      color:#333}
.note.warn{border-color:#e0a800}
.note.stop{border-color:var(--red)}
.decide{border:1px solid var(--line);border-radius:8px;padding:4px 16px;
        background:#fafafa;margin:16px 0}
code{background:#f2f2f3;padding:1px 5px;border-radius:4px;font-size:13px}
.small{font-size:13px;color:var(--muted)}
@media print{body{padding:0} th{position:static}}
"""

TAGCLASS = {CONFLICT: "t-conflict", UNKNOWN: "t-unknown",
            UNPAID: "t-unpaid", ALLOCATED: "t-allocated"}


def _table(rows, show_action=True):
    head = ("<tr><th>Employee</th><th>Department</th><th>Joined</th>"
            "<th>Service</th><th>Verdict</th><th>Evidence</th>"
            + ("<th style='width:150px'>HR: which group?</th>" if show_action else "")
            + "</tr>")
    today = getdate(nowdate())
    body = []
    for verdict, confidence, why, r in rows:
        # Tenure is the one thing HR can weigh for somebody with no leave history:
        # a long-serving employee who has never taken a paid day is behaving like
        # the unpaid group; a recent joiner simply has not had the chance.
        years = ((today - getdate(r.joined)).days / 365.25) if r.joined else 0
        long_serving = " <b>(long)</b>" if years >= 3 else ""
        body.append(
            f"<tr><td><b>{frappe.utils.escape_html(r.who)}</b>"
            f"<div class='small'>{r.emp}</div></td>"
            f"<td>{frappe.utils.escape_html(r.dept)}</td>"
            f"<td class='small'>{r.joined}</td>"
            f"<td class='small'>{years:.1f} yr{long_serving}</td>"
            f"<td><span class='tag {TAGCLASS[verdict]}'>{verdict}</span>"
            f"<div class='small'>{confidence}</div></td>"
            f"<td class='why'>{why}</td>"
            + ("<td></td>" if show_action else "") + "</tr>")
    # The table scrolls inside its own box rather than pushing the PAGE sideways —
    # HR reads this on a laptop, and a page that scrolls horizontally hides the
    # right-hand "which group?" column, which is the only one they have to fill in.
    return f"<div class='wrap'><table>{head}{''.join(body)}</table></div>"


def _entitlement_section():
    """The numbers and the formula, for HR to confirm in the same sitting.

    MG, 2026-09-01: *"include this number and formula for AL and MC calculation
    for < 2 years into the .html that you have created, for verification with HR
    manager."*

    🔴 Everything here is **deduced from CAF's own past allocations**, not given by
    HR — `leave_policy_seed` says so plainly, and the under-2-year policy is even
    titled *ANNUAL PROVISIONAL*. So this is not a summary of policy; it is a set of
    questions with the working shown.

    Read live from the Leave Policy documents rather than restated, so the page
    cannot drift from what the system would actually allocate.
    """
    from caf.scripts import leave_formula as lf

    policies = []
    for p in frappe.get_all("Leave Policy", fields=["name", "title", "docstatus"],
                            order_by="name"):
        detail = {d.leave_type: d.annual_allocation for d in frappe.get_all(
            "Leave Policy Detail", filters={"parent": p.name},
            fields=["leave_type", "annual_allocation"])}
        policies.append((p, detail))

    rows = "".join(
        f"<tr><td><b>{frappe.utils.escape_html(p.title)}</b>"
        f"<div class='small'>{p.name}"
        f"{' &middot; <b>DRAFT</b>' if not p.docstatus else ''}</div></td>"
        f"<td>{d.get('Annual', '—'):g}</td><td>{d.get('MC', '—'):g}</td></tr>"
        for p, d in policies)

    # The pro-rated curve, computed the way the system would.
    curve = "".join(
        f"<tr><td>{m}</td>"
        f"<td>{lf.floor_half(m / 12 * lf.AL_CONSTANT):g}</td>"
        f"<td>{min(lf.floor_half(m / 12 * lf.MC_CONSTANT), lf.MC_BAND_CAP):g}</td></tr>"
        for m in (6, 9, 12, 15, 18, 21, 23))

    return f"""
<h2>0. First, please confirm the entitlement numbers</h2>
<div class="note stop">
<b>None of this came from HR.</b> Every figure below was <i>deduced</i> from CAF's
own past leave allocations in August 2026, so that the system could be built and
tested before your table was available. The under-2-year policy is even titled
<b>"ANNUAL PROVISIONAL"</b> for that reason. <b>Please correct anything that is
wrong</b> — the numbers live in three documents, not in code, so changing them is
editing three records.
</div>

<h3>The three service bands</h3>
<div class="wrap"><table>
<tr><th>Leave Policy</th><th>Annual (days)</th><th>MC (days)</th></tr>
{rows}
</table></div>
<p class="small">MC follows the Malaysian Employment Act table exactly
(14 / 18 / 22). Annual was matched to what CAF has actually been giving.</p>

<h3>Under 2 years — the pro-rating formula</h3>
<p>Service is counted from the joining date to <b>31 December of the year being
allocated</b> &mdash; not to the start of the year. Somebody who joined in July
2025 therefore has 17 months of credit in the 2026 cycle, not 5.</p>
<pre style="background:#f7f7f8;padding:10px 14px;border-radius:6px;font-size:13px">
months = completed months from joining date to 31 Dec of the cycle year

Annual  = months / 12 &times; {lf.AL_CONSTANT}      MC = months / 12 &times; {lf.MC_CONSTANT}

then rounded DOWN to the nearest HALF day
</pre>
<div class="wrap"><table>
<tr><th>Months of service</th><th>Annual</th><th>MC</th></tr>
{curve}
</table></div>
<p class="small">The half-day rounding was derived, not given: two employees at 22
months hold exactly <b>14.5</b> days, which whole-day rounding cannot produce.
Counting completed <i>months</i> rather than days was derived the same way.</p>

<div class="note warn">
<b>Three things we could not settle from the data &mdash; please rule on them.</b>
<ol>
<li><b>Does MC stop at 14 for anyone under 2 years?</b> Everyone with 12+ months
holds exactly 14, although the formula would give 19, 21 or 26. Only one employee
(at 8 months) sits below that ceiling and holds the formula's own answer. We have
assumed a cap of 14 &mdash; is that right?</li>
<li>🔴 <b>Annual appears to DROP as service passes two years.</b> At 23 months the
formula gives <b>15</b> days; the moment service reaches 24 months the flat band
gives <b>12</b>. Somebody would lose 3 days of annual leave by staying longer.
That is very likely not intended &mdash; which figure is wrong?</li>
<li><b>Two employees do not fit any rule.</b> Both have 27 months of service, so
the 2&ndash;5 year band says 12 annual and 18 MC. One actually holds
<b>18 annual / 14 MC</b> and the other <b>8 annual / 14 MC</b>. Were these
individual decisions, or mistakes?</li>
</ol>
</div>

<div class="note">
<b>Separately &mdash; and this is about USING leave, not allocating it:</b> an
employee with under one year of service may not <i>take</i> annual leave, only MC
or unpaid. The number allocated and the number usable are two different things.
Please confirm that is still the rule.
</div>

{_burn_section()}
"""


def _burn_section():
    """Point at the existing decision paper — do NOT re-ask the question.

    🔴 **A correction, 2026-09-02.** The first version of this section asked HR to
    choose between four options for the late-year-joiner problem. It should never
    have existed: **`LEAVE_LATE_JOINER_for_HR_decision.html` already asks exactly
    this**, prepared 2026-08-13, using the *same* employee as its worked example,
    with its own diagrams and **three** options — A change nothing · B skip the
    first grant · C issue it in January — plus a recommendation (C) and a stated
    default if unanswered (A).

    Asking again with a **different set of options** would have been worse than
    not asking at all: HR would hold two papers on one question whose answers do
    not map onto each other, and would reasonably assume they were two questions.

    So this is a pointer and a status line. The count is computed live, because it
    grows with every October–December intake and a stale figure is exactly what
    stops a document being believed.
    """
    n = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabEmployee`
         WHERE status = 'Active' AND MONTH(date_of_joining) IN (10, 11, 12)""")[0][0]
    total = frappe.db.count("Employee", {"status": "Active"})
    if not n:
        return ""

    soonest = frappe.db.sql("""
        SELECT employee_name, date_of_joining FROM `tabEmployee`
         WHERE status = 'Active' AND MONTH(date_of_joining) IN (10, 11, 12)
      ORDER BY DAYOFYEAR(date_of_joining) DESC LIMIT 1""", as_dict=True)
    who = soonest[0] if soonest else None
    nearest = (f" &mdash; the nearest being <b>"
               f"{frappe.utils.escape_html(who.employee_name)}</b>, who joined "
               f"{who.date_of_joining}") if who else ""

    return f"""
<h2>0c. Already asked separately &mdash; late-year joiners</h2>
<div class="note">
<b>This is not a new question and does not need answering here.</b> Annual leave
cannot be taken until one year of service, and it does not carry forward past
31&nbsp;December &mdash; so somebody joining in October, November or December has
their entitlement unlock and expire within weeks of each other.
<br><br>
It is already set out in its own paper &mdash;
<b><code>LEAVE_LATE_JOINER_for_HR_decision.html</code></b>, prepared 2026-08-13,
with three options and a recommendation. It affects <b>{n} of {total}</b> active
staff{nearest}.
<br><br>
⚠️ <b>If that paper goes unanswered, option A stands by default</b> &mdash; the
days are granted and then quietly expire. Noted here only so the two documents are
known to be about the same people.
</div>
"""


def html(path=None):
    """Three sections, because 46 names is a chore and 33 is a task.

    🔴 The split is by **what HR actually has to supply**, not by my confidence:

      decide   nothing in the data can settle it — HR is the only source
      glance   the evidence points one way; HR only has to disagree
      settled  spending entitlement, or holding an allocation. No opinion needed

    Lumping the middle group in with the first made the ask 46 people long, and a
    list that long is one nobody finishes — the same reasoning as the readiness
    audit's severity split (RDY-SEVERITY): a list that cries wolf is one nobody
    reads.
    """
    frappe.set_user("Administrator")
    rows = _classified()
    decide = [t for t in rows if t[1] in ("needs HR", "none")]
    glance = [t for t in rows if t[1] == "weak"]
    settled = [t for t in rows if t[1] in ("strong", "certain")]
    n = lambda v: sum(1 for t in rows if t[0] == v)  # noqa: E731

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Leave groups — for HR confirmation</title><style>{CSS}</style></head><body>

<h1>Which leave group is each employee in?</h1>
<p class="sub">Generated {nowdate()} from the test server &middot; read-only, nothing was
changed &middot; <b>{len(rows)}</b> active employees</p>

<div class="note">
<b>The rule (FBR58).</b> The workforce is two groups: those <b>with</b> a leave
allocation, and those <b>without</b>, for whom any day off is unpaid leave.
An employee with no allocation is a deliberate category &mdash; <i>not</i> a mistake.
<br><br>
<b>How it will be recorded (FBR60).</b> A <b>Leave Policy Assignment</b> links each
allocated employee to one of the three existing Leave Policies. No assignment = the
unpaid group. Today there are <b>zero</b> assignments, which is why this list exists.
</div>

<div class="cards">
  <div class="card red"><div class="n">{n(CONFLICT)}</div>
    <div class="l">Conflict &mdash; took paid leave with no allocation</div></div>
  <div class="card amber"><div class="n">{n(UNKNOWN)}</div>
    <div class="l">Unknown &mdash; no evidence either way</div></div>
  <div class="card"><div class="n">{n(UNPAID)}</div>
    <div class="l">Looks unpaid-only</div></div>
  <div class="card green"><div class="n">{n(ALLOCATED)}</div>
    <div class="l">Certainly allocated</div></div>
</div>

<div class="note stop">
<b>You only need to fill in the first table &mdash; {len(decide)} people.</b>
For those, nothing in the system can settle it and you are the only source.
The second table ({len(glance)}) is a glance: the evidence points one way and you
only need to say so if you disagree. The third ({len(settled)}) needs nothing.
</div>

<h2>How each verdict was reached</h2>
<p>Every Leave Type on this system is flagged <code>is_lwp</code>, and it splits
cleanly:</p>
<table>
<tr><th style="width:150px">Signal</th><th>Meaning</th></tr>
<tr><td><b>Holds a Leave Allocation</b></td>
    <td>Certainly in the allocated group. Nothing to decide.</td></tr>
<tr><td><b>Took Annual / MC / Marriage / Compassionate</b><br>
        <span class="small">(<code>is_lwp = 0</code>)</span></td>
    <td>These <b>consume entitlement</b>. A submitted application is a record of the
        person <i>spending</i> leave, so they must have had some &mdash; whether or not
        anyone created the allocation document.</td></tr>
<tr><td><b>Took only Leave Without Pay, Emergency, Maternity,<br>MC Without Pay,
        Others, PH Replacement</b><br>
        <span class="small">(<code>is_lwp = 1</code>)</span></td>
    <td>Consumes no entitlement. Someone who has taken time off and it was
        <i>always</i> unpaid is behaving like the unpaid group.</td></tr>
<tr><td><b>No leave of any kind</b></td>
    <td>Nothing to reason from. Only HR knows.</td></tr>
</table>

<div class="note warn">
<b>Department was deliberately NOT used.</b> Most production staff (wet area, cooker)
are in the unpaid group, but <i>all 13 departments contain both</i> &mdash; so
classifying by department would be wrong for the exceptions, and the exceptions are
exactly the people worth getting right. Department is shown only to help you place
the name.
</div>

{_entitlement_section()}

<h2>1. Please decide these {len(decide)}</h2>
<p class="sub">Nothing in the system can settle these. Almost all of them have taken
no leave of any kind, so there is simply no evidence either way &mdash; you are the
only source. <b>Tenure is worth a look:</b> somebody who joined years ago and has
never taken a single day of paid leave is more likely to be in the unpaid group than
a recent joiner who has not needed leave yet.</p>
{_table(decide)}

<div class="decide">
<p><b>What happens next.</b> For everyone marked <b>allocated</b>, a Leave Policy
Assignment is created against the right Leave Policy, and the annual/MC entitlement
is then calculated by the existing formula &mdash; including the pro-rated rule for
anyone with under two years' service. Everyone else is left exactly as they are;
unpaid leave needs no allocation.</p>
<p class="small">Nothing is created until you confirm. This page changed nothing.</p>
</div>

<h2>2. Probably unpaid &mdash; a glance ({len(glance)})</h2>
<p class="sub">Each of these has taken time off and it was <b>always unpaid</b>, and
none holds an allocation. That points at the unpaid group, but the history is thin
(one or two applications), so it is worth your eye. <b>Only mark the ones you
disagree with.</b></p>
{_table(glance)}

<h2>3. Settled by evidence ({len(settled)}) &mdash; no action</h2>
<p class="sub">Listed for completeness. These are people who either hold an
allocation, have <b>spent</b> paid entitlement, or have a consistent unpaid-only
history. Tell us only if one looks plainly wrong.</p>
{_table(settled, show_action=False)}

</body></html>"""

    path = path or "/tmp/LEAVE_GROUPS_for_HR_confirmation.html"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {path} — {len(rows)} employees: {len(decide)} to decide, "
          f"{len(glance)} to glance at, {len(settled)} settled")
    return path
