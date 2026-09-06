"""The Shift Type sign-off page — T-28 items 4 and 5, in one document.

    bench --site <site> execute caf.scripts.shift_signoff_html.write

MG, 2026-09-07: *"list propose group and naming of shift_type · list emp assign
at each shift · ready for HR manager to sign off."*

WHY ITEMS 4 AND 5 SHARE ONE PAGE, WHEN T-28 SAYS "ONE SUBJECT, ONE SIGNATURE"
-----------------------------------------------------------------------------
Because they are one subject. A shift's parameters mean nothing to HR in the
abstract — *"8:00–16:30, lunch 60, OT off, In + Out + Lunch pair"* is a row she
cannot check. **The same row with "Rajaindran works this" attached is a claim she
can confirm or deny from memory.** Splitting them would produce two pages neither
of which can be verified.

⚠️ This is the opposite of the join-date page, where 89 rows each needed the same
one-line check. Here there are 16 groups and 89 people, and the people are what
make the groups legible.

WHAT THIS PAGE IS FOR, PRECISELY
--------------------------------
It is the gate before T-31's export. Getting the names right on this server is
worth doing **because a fixture import matches on NAME and overwrites** — so
whatever these shifts are called here is what production will be asked to
become. A name that is wrong now is a wrong name on 89 people's payroll later.

🔴 AND IT CANNOT BE THE WHOLE OF THE EXPORT PLAN
-------------------------------------------------
Exporting Shift Types moves the SHIFTS. It does not move anybody onto them:
`Employee.default_shift` is **data, not a fixture**, and `bench migrate` never
touches it. So after a clean export, production holds the right shifts with
nobody assigned. The assignment is a separate, deliberate data step — which is
the other half of what this page is signing off.

⚠️ READ-ONLY. Writes an HTML file and never touches the site.
"""

import os
from datetime import date

import frappe

from caf.scripts.join_date_signoff_html import CSS

OUT = ("/workspace/development/frappe-bench/apps/caf/"
       "SHIFT_TYPE_for_HR_signoff.html")

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_LABEL = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# How many departed employees to name per shift before summarising the rest.
LEFT_CAP = 6

# 🔴 Names that are one keystroke apart, or that describe themselves in two
# different languages. Each is a real export hazard, not a style note — see the
# page text for why.
HAZARDS = {
    ("Special 8-5", "special"):
        "One capital letter apart, and they are <b>not variants of each other</b>: "
        "<code>Special 8-5</code> is 8:00–17:00 Monday to Saturday with overtime; "
        "<code>special</code> is 9:00–18:00 Monday to Friday with no lunch break. "
        "In an alphabetical list they sit next to each other. "
        "<code>special</code> is the Managing Director's shift.",
    ("8:30am Schedule", "8.30am Roster"):
        "A dot instead of a colon, and <b>30 minutes' difference in the end "
        "time</b> — 17:30 against 17:00. Also different on overtime.",
    ("8-4.30 no OT", "8am In or Out"):
        "<b>Identical on every parameter except the punch rule</b>, and neither "
        "name mentions it. One name describes the hours and the overtime rule, "
        "the other describes the hours and the punch rule — two naming "
        "conventions inside one group.",
}

PUNCH_PLAIN = {
    "In + Out + Lunch pair": "must clock in, out, and both sides of lunch",
    "In + Out only": "must clock in and out; lunch is not clocked",
    "In OR Out only": "one clocking is enough for the day to count",
}

EXTRA_CSS = """
.grp{border:1px solid var(--line);border-radius:8px;margin:14px 0;overflow:hidden}
.grp>h3{margin:0;padding:10px 16px;background:var(--head);font-size:15px;
        border-bottom:1px solid var(--line)}
.grp .params{padding:8px 16px;font-size:13px;color:#333;
             border-bottom:1px solid var(--line);background:#fcfcfd}
.grp .params b{color:var(--fg)}
.grp .shift{padding:10px 16px;border-bottom:1px solid var(--line)}
.grp .shift:last-child{border-bottom:0}
.grp .shift .nm{font-weight:600;font-size:14.5px}
.grp .shift .meta{color:var(--muted);font-size:12.5px;margin-top:1px}
.people{margin:7px 0 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:5px}
.people li{font-size:12.5px;background:#f4f5f7;border:1px solid var(--line);
           border-radius:11px;padding:1px 9px}
.people li.left{opacity:.45;text-decoration:line-through}
.pill{display:inline-block;font-size:11.5px;font-weight:600;border-radius:10px;
      padding:1px 8px;margin-left:6px}
.pill.pair{background:var(--bluebg);color:var(--blue)}
.pill.empty{background:var(--amberbg);color:var(--amber)}
.pill.big{background:var(--greenbg);color:var(--green)}
.wk{font-variant-numeric:tabular-nums;letter-spacing:.5px;font-size:12.5px}
.wk .on{color:var(--fg);font-weight:600}
.wk .off{color:#c9c9c9}
"""


def _rows():
    out = []
    for r in frappe.get_all(
            "Shift Type",
            fields=["name", "caf_shift_code", "start_time", "end_time",
                    "caf_lunch_minutes", "caf_allow_ot", "caf_ot_gate_minutes",
                    "caf_ot_round_minutes", "caf_required_punches",
                    "caf_alt_sat", "caf_sat_mirror", "caf_sat_anchor",
                    "caf_sat_anchor_date", "holiday_list"]
                   + [f"caf_work_{d}" for d in DAYS],
            order_by="start_time, end_time, name"):
        emps = frappe.get_all(
            "Employee", filters={"default_shift": r.name},
            fields=["name", "employee_name", "department", "status",
                    "attendance_device_id"],
            order_by="status, employee_name")
        r["employees"] = emps
        r["active"] = [e for e in emps if e.status == "Active"]
        r["assignments"] = frappe.db.count(
            "Shift Assignment", {"shift_type": r.name, "docstatus": 1})
        out.append(r)
    return out


def _key(r):
    days = tuple(bool(r.get(f"caf_work_{d}")) for d in DAYS)
    return (str(r.start_time), str(r.end_time), r.caf_lunch_minutes,
            r.caf_allow_ot, days, r.caf_required_punches, bool(r.caf_alt_sat))


def _hhmm(t):
    """`Time` comes back as a timedelta, whose str() is 'H:MM:SS' — a naive
    [:5] slice therefore yields '6:00:' for single-digit hours."""
    if t is None:
        return "—"
    s = str(t)
    h, m = (s.split(":") + ["0", "0"])[:2]
    return f"{int(h):02d}:{int(m):02d}"


def _week(days):
    """⚠️ Colour alone must not carry this. HR will print the page, and a grey
    letter and a black letter are the same letter in greyscale — so a non-working
    day is rendered as a dash, which survives any medium."""
    return "".join(
        f'<span class="{"on" if on else "off"}">'
        f'{DAY_LABEL[i][:1] if on else "–"}</span>'
        for i, on in enumerate(days))


def write(path=None):
    path = path or OUT
    rows = _rows()

    groups = {}
    for r in rows:
        groups.setdefault(_key(r), []).append(r)

    n_active = frappe.db.count("Employee", {"status": "Active"})
    placed = sum(len(r["active"]) for r in rows)
    unplaced = n_active - placed
    empty = [r for r in rows if not r["employees"]]
    hist = [r for r in rows if r["employees"] and not r["active"]]

    blocks = []
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        st, en, lunch, ot, days, punches, alt = key
        act = sum(len(m["active"]) for m in members)

        pills = ""
        if alt:
            pills = '<span class="pill pair">alternating pair</span>'
        elif act == 0:
            pills = '<span class="pill empty">nobody works this</span>'
        elif act >= 20:
            pills = f'<span class="pill big">{act} people</span>'

        shifts = []
        for m in members:
            # ⚠️ Every ACTIVE name, always — those are what HR is checking.
            # Leavers are capped: `8am Schedule` carries 104 of them, and a wall
            # of struck-through names buries the 65 people the page is about.
            gone = [e for e in m["employees"] if e.status != "Active"]
            people = "".join(
                f'<li>{e.employee_name}</li>' for e in m["active"])
            people += "".join(
                f'<li class="left">{e.employee_name}</li>' for e in gone[:LEFT_CAP])
            if len(gone) > LEFT_CAP:
                people += (f'<li class="left">+{len(gone) - LEFT_CAP} more who '
                           f'have left</li>')
            extra = []
            if m.caf_alt_sat:
                extra.append(f"rests/works <b>{m.caf_sat_anchor}</b> on the anchor "
                             f"Saturday ({m.caf_sat_anchor_date}); mirror of "
                             f"<b>{m.caf_sat_mirror}</b>")
            if m["assignments"]:
                extra.append(f"{m['assignments']} dated Shift Assignment(s) "
                             f"override this")
            shifts.append(
                f'<div class="shift">'
                f'<div class="nm">{m.name}</div>'
                f'<div class="meta">code <code>{m.caf_shift_code}</code> '
                f'&middot; holiday list <b>{m.holiday_list or "—"}</b> '
                f'&middot; {len(m["active"])} active of {len(m["employees"])}'
                + ("<br>" + " &middot; ".join(extra) if extra else "") + "</div>"
                + (f'<ul class="people">{people}</ul>' if people else
                   '<div class="small" style="margin-top:5px">no employee is on '
                   'this shift</div>')
                + "</div>")

        ot_txt = ("overtime <b>allowed</b>" if ot else "overtime <b>not allowed</b>")
        blocks.append(
            f'<div class="grp"><h3>{_hhmm(st)} – {_hhmm(en)}{pills}</h3>'
            f'<div class="params">'
            f'<span class="wk">{_week(days)}</span> &nbsp;&middot;&nbsp; '
            f'lunch <b>{lunch} min</b> &nbsp;&middot;&nbsp; {ot_txt} '
            f'&nbsp;&middot;&nbsp; {PUNCH_PLAIN.get(punches, punches)}'
            f'</div>' + "".join(shifts) + "</div>")

    haz = "".join(
        f"<tr><td><b>{a}</b><br><b>{b}</b></td><td class='why'>{why}</td></tr>"
        for (a, b), why in HAZARDS.items()
        if frappe.db.exists("Shift Type", a) and frappe.db.exists("Shift Type", b))

    dupes = [v for v in groups.values() if len(v) > 1]
    dupe_txt = "".join(
        f"<li><b>{' + '.join(m.name for m in v)}</b> — "
        f"{'an alternating pair, which is correct: they are identical by design and differ only in which Saturdays they rest' if v[0].caf_alt_sat else '🔴 identical parameters and NOT a pair — one of them is redundant'}</li>"
        for v in dupes)

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CAF — Shift Types and who is on them, for HR sign-off</title>
<style>{CSS}{EXTRA_CSS}</style></head><body>

<h1>Shift Types — the rules, and who works them</h1>
<p class="sub">Prepared for Chen Xiao Natalie &middot; {date.today():%-d %B %Y}
&middot; T-28 items 4 and 5</p>

<div class="cards">
  <div class="card"><div class="n">{len(rows)}</div>
    <div class="l">shift types</div></div>
  <div class="card green"><div class="n">{len(groups)}</div>
    <div class="l">genuinely different sets of rules</div></div>
  <div class="card"><div class="n">{placed}</div>
    <div class="l">active employees placed on a shift</div></div>
  <div class="card {'red' if unplaced else ''}"><div class="n">{unplaced}</div>
    <div class="l">active employees with no shift</div></div>
  <div class="card amber"><div class="n">{len(empty) + len(hist)}</div>
    <div class="l">shifts nobody currently works</div></div>
</div>

<div class="note">
<b>What this page is for.</b> These shift definitions are about to be copied from
the test server to the live server. Once copied, <b>they replace whatever the
live server currently holds under the same name</b> — so a shift called the wrong
thing here becomes the wrong thing on everybody's real hours. Please read each
group below and confirm two things: the <b>rules</b> are right, and the
<b>people</b> on them are right.
<br><br>
Nothing has been changed. Nothing will be copied until this page comes back.
</div>

<h2>1 &middot; How to read a group</h2>
<p>The heading of each box is what actually decides somebody's day: the start and
end time, which days of the week are working days, the lunch deduction, whether
overtime is allowed, and how many times they must clock. <b>Every shift inside one
box behaves identically</b> — if two shifts share a box, they are the same rule
under two names.</p>
<div class="note">
<b>"How many times they must clock"</b> is the least obvious of these and it
matters most:
<ul>
<li><b>must clock in, out, and both sides of lunch</b> — four clockings. A missing
    one holds the day for you to correct.</li>
<li><b>must clock in and out</b> — two clockings; lunch is deducted automatically.</li>
<li><b>one clocking is enough</b> — the day counts on a single tap. This is for
    people who are frequently off-site.</li>
</ul>
</div>

<h2>2 &middot; {len(groups)} sets of rules, {len(rows)} shifts, {placed} people</h2>
{"".join(blocks)}

<h2>3 &middot; Shifts that share a rule</h2>
<ul>{dupe_txt or "<li>None — every shift has its own distinct rule.</li>"}</ul>

<h2>4 &middot; 🔴 Names that could be confused for one another</h2>
<p>These are not style comments. The copy to the live server <b>matches shifts by
name</b>, so a name that is easy to mistake is a way for the wrong rule to land on
the wrong people.</p>
<div class="wrap"><table style="min-width:760px">
<tr><th>The two names</th><th>Why it matters</th></tr>
{haz}
</table></div>

<div class="decide">
<h3>Please mark, for each pair above</h3>
<p>Is the current naming fine to keep, or should one of them be renamed?
<b>Renaming is safe</b> — the system updates every place the old name was used.
If you want a rename, write the new name next to it.</p>
</div>

<h2>5 &middot; What you are signing</h2>
<div class="wrap"><table style="min-width:760px">
<tr><th></th><th>The statement</th></tr>
<tr><td class="d">1</td><td>The <b>hours, working days, lunch deduction and
    overtime rule</b> shown for each group are correct.</td></tr>
<tr><td class="d">2</td><td>The <b>clocking requirement</b> for each group is
    correct — particularly the shifts where one tap is enough.</td></tr>
<tr><td class="d">3</td><td>The <b>people listed under each shift</b> are on the
    right shift. Names shown struck through have left the company.</td></tr>
<tr><td class="d">4</td><td>The shifts nobody works may be <b>left as they
    are</b> — they hold past records and are not being deleted.</td></tr>
<tr><td class="d">5</td><td>The <b>names</b> in section 4 are either fine as they
    are, or renamed as marked.</td></tr>
</table></div>

<div class="sign">
<p><b>Signed off by</b> <span class="line"></span>
&nbsp;&nbsp;<b>Date</b> <span class="line" style="min-width:140px"></span></p>
<p class="small">Two things this signature does <b>not</b> cover, because they are
not yours to decide: which shifts exist on the live server today (being measured
separately), and the alternating-Saturday calendar itself, which you confirmed on
12 August.</p>
</div>

<p class="small">Generated by <code>caf.scripts.shift_signoff_html.write</code>
from the live test server.</p>
</body></html>"""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"wrote {path}")
    print(f"  shift types            : {len(rows)}")
    print(f"  distinct rule groups   : {len(groups)}")
    print(f"  active employees placed: {placed} of {n_active} "
          f"(unplaced {unplaced})")
    print(f"  shifts with nobody     : {len(empty)} empty, {len(hist)} history-only")
    print(f"  naming hazards flagged : {len(HAZARDS)}")
    for v in dupes:
        print(f"  shared rule            : {[m.name for m in v]} "
              f"(alt pair={bool(v[0].caf_alt_sat)})")
    return {"groups": len(groups), "shifts": len(rows), "unplaced": unplaced}
