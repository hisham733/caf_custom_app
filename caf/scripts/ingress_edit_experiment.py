"""T-57 — the Ingress overwrite experiment: capture the baseline, then the after.

    bench --site <site> execute caf.scripts.ingress_edit_experiment.before
    …MG makes the four edits inside the Ingress application…
    bench --site <site> execute caf.scripts.ingress_edit_experiment.after

READ ONLY on both sides. It never writes to Ingress and never writes to ERPNext;
it prints, and `before()` saves a JSON snapshot so `after()` can diff it.

WHY IT EXISTS
-------------
The 2026-08-17 experiment established **which flag marks an edit** — `_c`, not
`_x`. That answer is already in `ingress/source.py`. ⚠️ What it never captured was
a **baseline**, so nothing could be diffed afterwards, and it never tested the
case that now matters most.

🔴 **The new question: is a SUBMITTED Finger Log protected?** Under FBR85 the
punches stop being a record and become the input to pay, so an Ingress edit on a
day already submitted must be REPORTED, never silently applied.

THE SUBJECTS — measured, not remembered
---------------------------------------
    Mun Geet Ow Yong      attendance_device_id 1017   8:30am In or Out
    Chen Xiao Natalie     attendance_device_id  442   8am In and Out no Sat

⚠️ **"Miat Fatt" does not exist as an employee on this site.** No name matches;
the third subject of the original experiment cannot be reused.

⭐ Both sit on **unusual punch rules** (one-punch and two-punch shifts), which is
where the importer's edge cases live — they were well chosen.
"""

import json
import os

import frappe

SNAP = "/tmp/caf_ingress_experiment_baseline.json"

SUBJECTS = [
    ("Mun Geet Ow Yong", 1017),
    ("Chen Xiao Natalie", 442),
]

ING_COLS = ["att_in", "att_break", "att_resume", "att_out",
            "in_o", "break_o", "resume_o", "out_o",
            "in_c", "break_c", "resume_c", "out_c",
            "in_x", "break_x", "resume_x", "out_x",
            "othour", "workhour", "hasmisspunch", "lastupdate"]

ERP_COLS = ["name", "docstatus", "time_in", "break", "resume", "out",
            "caf_work_hours", "short", "overtime", "ot_in_hour", "final_ot",
            "day_type", "shift_type", "caf_not_full_day", "caf_hr_review"]


def _conn():
    import pymysql
    s = frappe.get_doc("Ingress Sync Settings")
    return pymysql.connect(
        host=s.host, port=s.port, user=s.db_user,
        password=s.get_password("db_password"), database=s.db_name,
        connect_timeout=10, read_timeout=180, charset="utf8mb4")


def _dates(cur, userid, limit=6):
    """Recent days the person ACTUALLY worked.

    ⚠️ Ingress pre-creates empty `attendance` rows for FUTURE dates — a bare
    `ORDER BY date DESC` returns late October 2026 with every column null and no
    Finger Log, which is not a baseline of anything. Bound it to the past AND
    require a real in-punch.
    """
    cur.execute("""SELECT date FROM attendance
                   WHERE userid = %s
                     AND date <= CURDATE()
                     AND att_in IS NOT NULL AND att_in <> '00:00:00'
                   ORDER BY date DESC LIMIT %s""", (userid, int(limit)))
    return [r[0] for r in cur.fetchall()]


def _capture():
    conn = _conn()
    cur = conn.cursor()
    snap = {}
    for name, userid in SUBJECTS:
        for d in _dates(cur, userid):
            key = "%s|%s" % (userid, d)
            cur.execute("SELECT %s FROM attendance WHERE userid=%%s AND date=%%s"
                        % ", ".join("`%s`" % c for c in ING_COLS), (userid, d))
            row = cur.fetchone()
            ing = dict(zip(ING_COLS, [str(v) for v in row])) if row else None

            cur.execute("""SELECT checktime, checktype FROM auditdata
                           WHERE userid=%s AND DATE(checktime)=%s
                           ORDER BY checktime""", (userid, d))
            taps = [(str(t), ct) for t, ct in cur.fetchall()]

            fl = frappe.db.get_value(
                "Finger Log",
                {"employee": frappe.db.get_value(
                    "Employee", {"attendance_device_id": userid}, "name"),
                 "work_date": d},
                ERP_COLS, as_dict=True)

            snap[key] = {"who": name, "userid": userid, "date": str(d),
                         "ingress": ing, "raw_taps": taps,
                         "erp": {k: str(v) for k, v in (fl or {}).items()}}
    conn.close()
    return snap


def _show(snap, title):
    print("=" * 78)
    print(title)
    print("=" * 78)
    for key in sorted(snap):
        s = snap[key]
        ing, erp = s["ingress"] or {}, s["erp"] or {}
        print("\n  %s · %s  (device %s)" % (s["who"], s["date"], s["userid"]))
        print("     raw taps      : %s" % (s["raw_taps"] or "(none)"))
        print("     INGRESS  in=%-9s break=%-9s resume=%-9s out=%-9s"
              % (ing.get("att_in"), ing.get("att_break"),
                 ing.get("att_resume"), ing.get("att_out")))
        print("              _o   in=%-9s break=%-9s resume=%-9s out=%-9s"
              % (ing.get("in_o"), ing.get("break_o"),
                 ing.get("resume_o"), ing.get("out_o")))
        print("              _c   in=%-9s break=%-9s resume=%-9s out=%-9s"
              % (ing.get("in_c"), ing.get("break_c"),
                 ing.get("resume_c"), ing.get("out_c")))
        print("              _x   in=%-9s break=%-9s resume=%-9s out=%-9s"
              % (ing.get("in_x"), ing.get("break_x"),
                 ing.get("resume_x"), ing.get("out_x")))
        print("              othour=%s workhour=%s lastupdate=%s"
              % (ing.get("othour"), ing.get("workhour"), ing.get("lastupdate")))
        if erp:
            print("     ERPNEXT  %s  docstatus=%s  in=%s break=%s resume=%s out=%s"
                  % (erp.get("name"), erp.get("docstatus"), erp.get("time_in"),
                     erp.get("break"), erp.get("resume"), erp.get("out")))
            print("              work=%s short=%s overtime=%s ot_in_hour=%s final_ot=%s"
                  % (erp.get("caf_work_hours"), erp.get("short"),
                     erp.get("overtime"), erp.get("ot_in_hour"),
                     erp.get("final_ot")))
        else:
            print("     ERPNEXT  (no Finger Log for this day)")


def before():
    """Capture and SAVE the baseline. Run this BEFORE touching Ingress."""
    snap = _capture()
    with open(SNAP, "w") as fh:
        json.dump(snap, fh, indent=1)
    _show(snap, "BASELINE — captured before any edit")
    print("\n  saved to %s  (%d person-days)" % (SNAP, len(snap)))
    print("\n  ⭐ Now make the edits in the Ingress application, then run:")
    print("     bench --site <site> execute caf.scripts.ingress_edit_experiment.after")
    return {"captured": len(snap), "file": SNAP}


def after():
    """Capture again and DIFF against the baseline."""
    if not os.path.exists(SNAP):
        frappe.throw("No baseline at %s — run before() first." % SNAP)
    with open(SNAP) as fh:
        base = json.load(fh)
    now = _capture()
    _show(now, "AFTER — captured following the Ingress edits")

    print("\n" + "=" * 78)
    print("WHAT CHANGED")
    print("=" * 78)
    any_change = False
    for key in sorted(set(base) | set(now)):
        b, n = base.get(key, {}), now.get(key, {})
        for side in ("ingress", "erp"):
            bb, nn = (b.get(side) or {}), (n.get(side) or {})
            for f in sorted(set(bb) | set(nn)):
                if bb.get(f) != nn.get(f):
                    any_change = True
                    print("   %s · %-8s %-12s %r  ->  %r"
                          % (key, side, f, bb.get(f), nn.get(f)))
        # ⚠️ Compare as LISTS. json.dump turns every tuple into a list, so a
        # baseline read back from disk holds [['t', 4]] while a fresh capture
        # holds [('t', 4)] — and a naive `!=` reports every single day as
        # "RAW TAPS changed" when nothing did. That false positive was in the
        # first run of this script; it is the diff's bug, not a finding.
        b_taps = [list(t) for t in (b.get("raw_taps") or [])]
        n_taps = [list(t) for t in (n.get("raw_taps") or [])]
        if b_taps != n_taps:
            any_change = True
            print("   %s · RAW TAPS changed — %s -> %s" % (key, b_taps, n_taps))
    if not any_change:
        print("   nothing changed on either side.")
    print("\n  🔴 The row that matters: did ERPNEXT change for a day whose")
    print("     Finger Log was already docstatus = 1? It must NOT have.")
