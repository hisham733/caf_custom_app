# Copyright (c) 2026, CAF and contributors
# For license information, please see license.txt

"""Look at ONE machine row, whole — for settling questions about what Ingress does.

Built 2026-08-17 for MG's amendment test: pick an employee and a work date, have
HR edit the punches in the Ingress app, and diff the row before against after.
The point is to answer *"which table does the amendment land in, and which column
should ERP read"* by measurement rather than inference.

It reads **every** column of `attendance` (76 of them) plus the raw device taps in
`auditdata`, because the interesting change is often in a column nobody thought
to select. `_o` / `_x` / `_c` triplets are grouped so a human can see them.

Read-only. Nothing here writes to the machine, ever.

    # before HR edits
    POST /api/method/caf.caf.ingress.inspect.snapshot
         {"ftag_id": "998", "work_date": "2026-08-15", "label": "before"}

    # after
    POST … {"ftag_id": "998", "work_date": "2026-08-15", "label": "after"}

    # what moved
    POST /api/method/caf.caf.ingress.inspect.diff
         {"ftag_id": "998", "work_date": "2026-08-15",
          "before": "before", "after": "after"}
"""

import json
import os

import frappe
from frappe import _

SNAP_DIR = "/tmp/ingress_snapshots"

# The columns that carry the story, in reading order. Everything else is dumped
# too — this list only decides what the diff shows FIRST.
PUNCH_TRIPLETS = [
    ("att_in", "in_o", "in_x", "in_c"),
    ("att_break", "break_o", "break_x", "break_c"),
    ("att_resume", "resume_o", "resume_x", "resume_c"),
    ("att_out", "out_o", "out_x", "out_c"),
    ("att_ot", "ot_o", "ot_x", "ot_c"),
    ("att_done", "done_o", "done_x", "done_c"),
]


def _live():
    from caf.caf.ingress.source import get_source

    src = get_source("Live MySQL")
    if not hasattr(src, "_cursor"):
        frappe.throw(_("Inspection needs the live machine, not a snapshot CSV."))
    return src


def read_row(ftag_id: str, work_date: str) -> dict:
    """Every column of the attendance row, plus the raw taps behind it."""
    src = _live()
    out = {"ftag_id": str(ftag_id), "work_date": str(work_date)}

    with src._cursor() as cur:
        cur.execute("""SELECT COLUMN_NAME FROM information_schema.columns
                       WHERE table_schema = %s AND table_name = 'attendance'
                       ORDER BY ordinal_position""", (src.s.db_name,))
        cols = [r[0] for r in cur.fetchall()]

        quoted = ", ".join(f"`{c}`" for c in cols)
        cur.execute(f"SELECT {quoted} FROM attendance WHERE userid = %s AND date = %s",
                    (str(ftag_id), str(work_date)))
        rows = cur.fetchall()
        out["attendance_row_count"] = len(rows)
        out["attendance"] = ({c: _s(v) for c, v in zip(cols, rows[0])}
                             if rows else None)

        # The raw device taps for that calendar day — the facts `attendance` is
        # derived from. If an HR edit ever touched these, that would be the
        # headline; measured so far, it does not.
        cur.execute("""SELECT checktime, checktype, serialno, verifycode, isvalid
                       FROM auditdata WHERE userid = %s AND DATE(checktime) = %s
                       ORDER BY checktime""", (str(ftag_id), str(work_date)))
        out["auditdata"] = [
            {"checktime": _s(a), "checktype": _s(b), "serialno": _s(c),
             "verifycode": _s(d), "isvalid": _s(e)}
            for a, b, c, d, e in cur.fetchall()]
        out["auditdata_count"] = len(out["auditdata"])

        # Is anything logged elsewhere? Asserted each run rather than assumed —
        # if FingerTec ever starts writing these, the test should notice.
        for tbl in ("log_update", "remark"):
            cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
            out[f"{tbl}_rows"] = cur.fetchone()[0]

    return out


def _s(v):
    """JSON-safe. Times come back as timedelta, dates as date."""
    if v is None:
        return None
    if hasattr(v, "total_seconds"):
        t = int(v.total_seconds())
        return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    if isinstance(v, (int, float, str)):
        return v
    return str(v)


@frappe.whitelist()
def audit_snapshot(label="before"):
    """The Ingress app's OWN login history — session-level attribution.

    🔴 This corrects an earlier conclusion in this project. `log_update` is empty,
    so the first read of the evidence was "an Ingress edit is not attributable at
    all". That was too quick: MG established 2026-08-17 that **editing a punch
    needs a special password**, which means an elevated login is involved — and
    `system_user_lastlogin` keeps 1,221 of them, with the account id, the IP, and
    the login/logout window.

    So an amendment CAN be tied to a session: which app account, from which
    machine, between which two times. What it cannot be tied to is a PERSON,
    because CAF has three app accounts (`admin`, `Fiza`, `Test`) and every login
    in the history is `admin` — shared. Session-level, not person-level.

    Correlate afterwards by checking which session window `attendance.lastupdate`
    falls inside. Combined with HR's own written note, that is full attribution.
    """
    frappe.only_for(("System Manager", "HR Manager"))
    src = _live()
    out = {}

    with src._cursor() as cur:
        # `attendanceview` is captured because it evidently records the LAST
        # attendance screen the account opened — admin's currently reads
        # "10,2026-08-15,2026-08-15::'12','22',…'385','442',…'1017',…" i.e. a
        # schedule, a date range and the userid list in view. If it moves when HR
        # edits, it is a second activity trace and a better one than a timestamp.
        cur.execute("""SELECT id, username, RolesID, activeFlag, Remark,
                              attendanceview, passwordUpdateOn
                       FROM system_user ORDER BY id""")
        out["system_user"] = [
            {"id": a, "username": b, "roles_id": c, "active": d, "remark": e,
             "attendanceview": _s(f), "password_updated_on": _s(g)}
            for a, b, c, d, e, f, g in cur.fetchall()]

        cur.execute("""SELECT id, userid, ipaddress, LoginTime, LogoutTime,
                              LogoutStatusFlag, Remark
                       FROM system_user_lastlogin ORDER BY id DESC LIMIT 20""")
        out["recent_logins"] = [
            {"id": a, "user_id": b, "ip": c, "login": _s(d), "logout": _s(e),
             "still_open": f == 1, "remark": g}
            for a, b, c, d, e, f, g in cur.fetchall()]

        for tbl in ("system_user_lastlogin", "log_client", "log_client_details",
                    "log_server", "event_activity", "log_update"):
            cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
            out[f"count_{tbl}"] = cur.fetchone()[0]

    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, f"audit_{label}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)
    out["saved"] = path
    return out


@frappe.whitelist()
def audit_diff(before="before", after="after"):
    """Which login sessions appeared between two audit snapshots."""
    frappe.only_for(("System Manager", "HR Manager"))

    def load(label):
        path = os.path.join(SNAP_DIR, f"audit_{label}.json")
        if not os.path.exists(path):
            frappe.throw(_("No audit snapshot at {0}").format(path))
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    b, a = load(before), load(after)
    seen = {r["id"] for r in b["recent_logins"]}
    new = [r for r in a["recent_logins"] if r["id"] not in seen]
    names = {u["id"]: u["username"] for u in a["system_user"]}
    for r in new:
        r["username"] = names.get(r["user_id"], "?")

    bview = {u["id"]: u.get("attendanceview") for u in b["system_user"]}
    view_moved = [
        {"account": u["username"], "before": bview.get(u["id"]),
         "after": u.get("attendanceview")}
        for u in a["system_user"]
        if u.get("attendanceview") != bview.get(u["id"])]

    return {
        "new_login_sessions": new,
        "attendanceview_moved": view_moved,
        "table_growth": {k: {"before": b.get(k), "after": a.get(k)}
                         for k in a if k.startswith("count_")
                         and b.get(k) != a.get(k)},
        "note": ("Match attendance.lastupdate against these windows to place the "
                 "edit in a session. Shared accounts mean this identifies the "
                 "ACCOUNT and the machine, never the individual."),
    }


@frappe.whitelist()
def snapshot(ftag_id, work_date, label="before"):
    """Read the row and keep it on disk so it survives across days."""
    frappe.only_for(("System Manager", "HR Manager"))
    data = read_row(ftag_id, work_date)

    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, f"{ftag_id}_{work_date}_{label}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)

    att = data["attendance"] or {}
    return {
        "saved": path,
        "attendance_row_count": data["attendance_row_count"],
        "auditdata_count": data["auditdata_count"],
        "log_update_rows": data["log_update_rows"],
        "remark_rows": data["remark_rows"],
        "punches": {p: att.get(p) for p, _o, _x, _c in PUNCH_TRIPLETS},
        "originals": {o: att.get(o) for _p, o, _x, _c in PUNCH_TRIPLETS},
        "override_flags": {x: att.get(x) for _p, _o, x, _c in PUNCH_TRIPLETS},
        "othour": att.get("othour"),
        "workhour": att.get("workhour"),
        "lastupdate": att.get("lastupdate"),
    }


@frappe.whitelist()
def diff(ftag_id, work_date, before="before", after="after"):
    """Every column that moved between two snapshots. This is the answer."""
    frappe.only_for(("System Manager", "HR Manager"))

    def load(label):
        path = os.path.join(SNAP_DIR, f"{ftag_id}_{work_date}_{label}.json")
        if not os.path.exists(path):
            frappe.throw(_("No {0} snapshot at {1}").format(label, path))
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    b, a = load(before), load(after)
    br, ar = b.get("attendance") or {}, a.get("attendance") or {}

    changed = {c: {"before": br.get(c), "after": ar.get(c)}
               for c in sorted(set(br) | set(ar))
               if br.get(c) != ar.get(c)}

    return {
        "attendance_columns_changed": changed,
        "attendance_row_count": {"before": b["attendance_row_count"],
                                 "after": a["attendance_row_count"]},
        # 🔴 If this moved, the amendment reached the RAW taps and everything the
        # design assumes about `attendance` being the only edited table is wrong.
        "auditdata_count": {"before": b["auditdata_count"],
                            "after": a["auditdata_count"]},
        "auditdata_changed": b["auditdata"] != a["auditdata"],
        "log_update_rows": {"before": b["log_update_rows"],
                            "after": a["log_update_rows"]},
        "remark_rows": {"before": b["remark_rows"], "after": a["remark_rows"]},
        "verdict": _verdict(changed, b, a),
    }


def _verdict(changed, b, a):
    """Say plainly what the evidence supports, so nobody has to re-derive it."""
    notes = []
    if not changed:
        notes.append("NOTHING CHANGED in the attendance row — either the edit was "
                     "not saved, or it landed somewhere this tool does not read.")
        return notes

    punch_cols = {p for p, _o, _x, _c in PUNCH_TRIPLETS}
    orig_cols = {o for _p, o, _x, _c in PUNCH_TRIPLETS}
    flag_cols = {x for _p, _o, x, _c in PUNCH_TRIPLETS}

    if punch_cols & set(changed):
        notes.append(f"PRESENTED value changed: {sorted(punch_cols & set(changed))} "
                     f"— this is what ERP imports.")
    if orig_cols & set(changed):
        notes.append(f"⚠️ ORIGINAL (_o) also changed: {sorted(orig_cols & set(changed))} "
                     f"— the machine did not preserve the pre-edit value, so `_o` "
                     f"cannot be trusted as an audit record.")
    else:
        notes.append("`_o` columns unchanged — the original punch survived the edit.")
    if flag_cols & set(changed):
        notes.append(f"OVERRIDE FLAG set: {sorted(flag_cols & set(changed))} — this "
                     f"is the reliable 'a human edited this' marker.")
    else:
        notes.append("⚠️ NO override flag was set — an HR edit is then "
                     "indistinguishable from a machine recomputation, and ERP "
                     "cannot tell them apart.")
    if b["auditdata"] != a["auditdata"]:
        notes.append("🔴 auditdata (RAW device taps) changed — the edit reached the "
                     "fact table, not just the derived summary.")
    else:
        notes.append("auditdata unchanged — the raw taps are untouched, as expected.")
    if a["log_update_rows"] > b["log_update_rows"]:
        notes.append("log_update gained rows — there IS an audit trail after all.")
    return notes
