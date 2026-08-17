# Copyright (c) 2026, CAF and contributors
# For license information, please see license.txt

"""Reading the machine — two sources, one row shape.

Ingress is a LOG. It is not a system of record for anything CAF decides, and this
module is where that boundary is kept: it yields punches and nothing else, so no
caller downstream has the option of importing the machine's opinion.

THE ONE RULE THAT MATTERS MOST (carried from Chunk 3, unchanged)
---------------------------------------------------------------
🔴 `day_type` and `shift_type` are NEVER read. Ingress' `daytype` and `sche1` play
no part in the target design (OD-45) — the shift comes from a Shift Assignment
covering the date, else `Employee.default_shift`, and the day type is resolved
from that shift's working week. `workhour` and `shorthour` are likewise derived by
`FingerLog.validate()`, not imported (OD-59), and `leavetype` belongs to the Leave
Application (FDR4).

TWO SOURCES
-----------
    LiveSource      the Ingress MySQL over the LAN — the real thing
    SnapshotSource  a gzipped CSV export — what Chunk 3 read, kept so the
                    importer still works off-LAN and so tests can run without
                    the machine

Both yield the SAME normalised dict, so `sync.py` cannot tell them apart. That is
the point: the test suite proves parity (I1) and everything above this line is
then source-agnostic.

🔴 THE THREE-COLUMN MODEL — settled by a controlled HR edit, 2026-08-17
----------------------------------------------------------------------
Ingress stores each punch three ways, and the roles are now measured rather than
inferred (full evidence: INGRESS_EDIT_CAPABILITY.md E-9):

    att_in   the PRESENTED value — **this is what ERP imports**
    in_o     the ORIGINAL, preserved when the app overwrites a device reading
    in_c     0 = came from a raw device tap · 1 = written by the Ingress app
    in_x     ⚠️ NOT the edit marker. An HR edit does not touch it.

HR edited four rows through the Ingress app (behind its edit password) and the
result was unambiguous: `att_out` 17:58 → 19:45, `out_o` **kept 17:58**, `out_c`
0 → **1**, and `out_x` stayed **0**.

Two traps therefore, not one:
  · `_x` looks like the override flag and is not — watching it means never seeing
    an edit at all;
  · `att_in <> in_o` is not an edit marker either — the machine also rewrites
    presented values (enrolment-day normalisation, ~19 rows a year), so comparing
    the two columns manufactures alarms on rows nobody touched.

The raw device taps in `auditdata` were **unchanged** by all four edits, which is
what lets `attendance` be treated as the single place an amendment lands.
"""

import csv
import gzip
from datetime import date, datetime

import frappe
from frappe import _
from frappe.utils import getdate

# Ingress column -> normalised key. The punches only.
PUNCHES = {
    "att_in": "time_in",
    "att_break": "break",
    "att_resume": "resume",
    "att_out": "out",
}

# 🔴 The flag that marks a punch as NOT a raw device reading. **`_c`, not `_x`** —
# established by a controlled HR edit on 2026-08-17 (four rows, in the Ingress app,
# behind its edit password):
#
#     att_out  17:58 -> 19:45     the new value
#     out_o    17:58 -> 17:58     the original, PRESERVED
#     out_x        0 -> 0         never moved
#     out_c        0 -> 1         <-- this is the marker
#
# `machineInfo.md` documents `_c` the other way round ("1 = Ingress auto-computed,
# 0 = manually entered"). That is wrong, or at least backwards for the fields a
# person can touch. The coherent reading, which fits BOTH the edit test and the
# population (96% of punched 2026 rows carry `in_c = 0`):
#
#     _c = 0  the value came from a raw device tap
#     _c = 1  the value was written by the Ingress application
#
# So `_c = 1` is broader than "a human did it" — it also catches the machine's own
# enrolment-day normalisation (E-3a). Either way it means **this is not what the
# device recorded**, which is exactly what a person looking at the row needs to
# know. `_x` is left alone deliberately: 15 rows in 289,617 carry it, an HR punch
# edit does not set it, and what it does mean is still unknown.
EDIT_FLAGS = {
    "in_c": "time_in",
    "break_c": "break",
    "resume_c": "resume",
    "out_c": "out",
}

# 🔴 NEVER read these. Listed so the omission is visible rather than accidental.
NEVER_IMPORT = {
    "daytype": "day_type is resolved from the shift — OD-45",
    "sche1": "shift_type is resolved from Shift Assignment / default_shift — OD-45",
    "workhour": "caf_work_hours is derived — OD-59",
    "shorthour": "short is derived — OD-59",
    "leavetype": "leave_type belongs to the Leave Application — FDR4",
}


# ────────────────────────────────────────────────────────────── normalising

def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _time(value):
    """A punch, or the all-zero sentinel when the machine recorded nothing.

    ⚠️ Returns '00:00:00', NOT None — deliberately, and this is load-bearing. The
    whole absence path keys on the all-zero row; testing `time_in IS NULL` is the
    trap that produced a withdrawn decision (OD-49) after returning 0 of 21,363.
    """
    if value is None:
        return "00:00:00"
    value = str(value).strip()
    if not value:
        return "00:00:00"
    parts = value.split(":")
    if len(parts) == 2:
        parts.append("00")
    try:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(float(parts[2])):02d}"
    except (ValueError, IndexError):
        return "00:00:00"


def _float(value):
    try:
        return float(str(value or "0").strip() or 0)
    except ValueError:
        return 0.0


def _int(value):
    try:
        return int(float(str(value or "0").strip() or 0))
    except ValueError:
        return 0


def normalise(raw: dict) -> dict | None:
    """One machine row -> the shape `sync.py` consumes. None if it has no date."""
    day = _date(raw.get("date"))
    if not day:
        return None

    row = {
        "ftag_id": str(raw.get("userid") or "").strip(),
        "work_date": day,
        "overtime": _float(raw.get("othour")),
        "hasmisspunch": _int(raw.get("hasmisspunch")),
        "lastupdate": raw.get("lastupdate"),
    }
    for src, key in PUNCHES.items():
        row[key] = _time(raw.get(src))

    # `_x` is the only reliable human-edit marker (see module docstring).
    row["edited"] = sorted({field for flag, field in EDIT_FLAGS.items()
                            if _int(raw.get(flag)) == 1})
    return row


def is_all_zero(row: dict) -> bool:
    """The absence shape: rostered, never punched."""
    return all(row.get(k) in (None, "", "00:00:00")
               for k in ("time_in", "break", "resume", "out"))


# ────────────────────────────────────────────────────────────────── sources

class BaseSource:
    label = "?"

    def describe(self) -> str:
        raise NotImplementedError

    def read(self, from_date, to_date, ftag_ids=None, include_absent=True):
        raise NotImplementedError


class LiveSource(BaseSource):
    """The Ingress MySQL over the LAN. Read-only, always.

    Failure is a normal operational state (§6.5 blocker 7): the machine is on a
    PC in the office and the network is not ours. What must never happen is a
    run that fails QUIETLY — so every error here raises, the caller marks the
    batch Failed, and somebody is told.
    """

    label = "live"

    def __init__(self, settings):
        self.s = settings

    def describe(self) -> str:
        with self._cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*), MAX(lastupdate) FROM attendance")
            count, last = cur.fetchone()
        return (f"{self.s.db_user}@{self.s.host}:{self.s.port}/{self.s.db_name} "
                f"MySQL {version} — {count:,} attendance rows, last update {last}")

    def _cursor(self):
        import pymysql

        class _Ctx:
            def __init__(ctx):
                ctx.conn = pymysql.connect(
                    host=self.s.host, port=self.s.port, user=self.s.db_user,
                    password=self.s.db_password, database=self.s.db_name,
                    connect_timeout=10, read_timeout=120, charset="utf8mb4")

            def __enter__(ctx):
                ctx.cur = ctx.conn.cursor()
                # Belt and braces. CAF never writes to the machine, and saying so
                # in the session is cheaper than trusting every future caller.
                try:
                    ctx.cur.execute("SET SESSION TRANSACTION READ ONLY")
                except Exception:
                    pass        # MySQL 5.5 predates it; the grant is the real lock
                return ctx.cur

            def __exit__(ctx, *exc):
                ctx.cur.close()
                ctx.conn.close()

        return _Ctx()

    def read_revised_since(self, since, ftag_ids=None):
        """Every row the machine has TOUCHED since `since`, at any work date.

        🔴 This is how an amendment reaches ERP, and a work-date window cannot
        do it. HR amends a punch in the Ingress app by overwriting the same
        `attendance` row (there is no amendment table — E-7); the only thing
        that moves is `lastupdate`. Measured 2026-08-17: **543 rows with a work
        date older than a month were revised during August**, one of them 191
        days after it was created. A D-4..D-1 fetch would never have seen a
        single one of them.

        ⚠️ `since` must come from the MACHINE's clock (`MAX(lastupdate)` of the
        previous run), not ERPNext's — they are different hosts.
        """
        where = ["a.lastupdate > %s", "u.SuspendedDate IS NULL"]
        args = [str(since)]
        if ftag_ids:
            where.append("a.userid IN ({})".format(", ".join(["%s"] * len(ftag_ids))))
            args.extend([str(f) for f in ftag_ids])

        sql = f"""
            SELECT a.userid, a.date, a.att_in, a.att_break, a.att_resume,
                   a.att_out, a.othour, a.hasmisspunch,
                   a.in_c, a.break_c, a.resume_c, a.out_c, a.lastupdate
            FROM attendance a
            JOIN `user` u ON a.userid = u.userid
            WHERE {' AND '.join(where)}
            ORDER BY a.lastupdate, a.date, a.userid
        """
        cols = ["userid", "date", "att_in", "att_break", "att_resume", "att_out",
                # `_c`, not `_x` — EDIT_FLAGS keys these, and a mismatch here is
                # silent: the column simply arrives as None and every row reports
                # "not adjusted". Caught 2026-08-17 while building the amendment
                # check, AFTER the suite went green — the synthetic fixtures set
                # these keys directly, so only the LIVE path was broken.
                "othour", "hasmisspunch", "in_c", "break_c", "resume_c", "out_c",
                "lastupdate"]
        with self._cursor() as cur:
            cur.execute(sql, args)
            for record in cur.fetchall():
                row = normalise(dict(zip(cols, record)))
                if row:
                    yield row

    def clock(self):
        """The machine's own `MAX(lastupdate)` — the watermark for the next run.

        Taken from the machine, never from ERPNext: reading `now()` on this host
        and comparing it against timestamps written on another one loses every
        row updated in the gap between the two clocks.
        """
        with self._cursor() as cur:
            cur.execute("SELECT MAX(lastupdate) FROM attendance")
            return cur.fetchone()[0]

    def read(self, from_date, to_date, ftag_ids=None, include_absent=True):
        # 🔴 `include_absent` decides whether the all-zero row comes through, and
        # getting it wrong is silent. §6.3's original proposal filtered
        # `att_in IS NOT NULL`, which would have dropped EVERY absence — and the
        # absence is the point of the design, not noise (3,993 of them exist).
        # It is off only when reading forward, where the rows are unpunched
        # roster placeholders for days that have not happened.
        where = ["a.date BETWEEN %s AND %s", "u.SuspendedDate IS NULL"]
        args = [str(from_date), str(to_date)]

        if not include_absent:
            where.append("(a.att_in <> '' OR a.hasmisspunch = 1)")

        if ftag_ids:
            where.append("a.userid IN ({})".format(
                ", ".join(["%s"] * len(ftag_ids))))
            args.extend([str(f) for f in ftag_ids])

        sql = f"""
            SELECT a.userid, a.date, a.att_in, a.att_break, a.att_resume,
                   a.att_out, a.othour, a.hasmisspunch,
                   a.in_c, a.break_c, a.resume_c, a.out_c, a.lastupdate
            FROM attendance a
            JOIN `user` u ON a.userid = u.userid
            WHERE {' AND '.join(where)}
            ORDER BY a.date, a.userid
        """
        cols = ["userid", "date", "att_in", "att_break", "att_resume", "att_out",
                # `_c`, not `_x` — EDIT_FLAGS keys these, and a mismatch here is
                # silent: the column simply arrives as None and every row reports
                # "not adjusted". Caught 2026-08-17 while building the amendment
                # check, AFTER the suite went green — the synthetic fixtures set
                # these keys directly, so only the LIVE path was broken.
                "othour", "hasmisspunch", "in_c", "break_c", "resume_c", "out_c",
                "lastupdate"]

        with self._cursor() as cur:
            cur.execute(sql, args)
            for record in cur.fetchall():
                row = normalise(dict(zip(cols, record)))
                if row:
                    yield row


class SnapshotSource(BaseSource):
    """A gzipped CSV export of the same table. What Chunk 3 read.

    Kept for two reasons that are both real: the laptop is not always on the CAF
    LAN, and a test that depends on a machine in an office is a test that fails
    for reasons unrelated to the code.
    """

    label = "snapshot"

    def __init__(self, path):
        self.path = path

    def describe(self) -> str:
        import os
        if not os.path.exists(self.path):
            frappe.throw(_("Snapshot not found at {0}").format(self.path))
        return f"{self.path} — {os.path.getsize(self.path):,} bytes"

    def clock(self):
        """A CSV has no clock. Callers must fall back to a date window."""
        return None

    def read_revised_since(self, since, ftag_ids=None):
        """A snapshot is a single instant — there is nothing to compare against.

        Raising rather than returning nothing on purpose: a silent empty result
        would let a reconciliation pass "succeed" having examined no rows, which
        is the failure shape this whole feature exists to remove.
        """
        frappe.throw(_(
            "Revision sweeps need the live machine — a CSV snapshot carries no "
            "lastupdate history. Switch Ingress Sync Settings to Live MySQL."))

    def read(self, from_date, to_date, ftag_ids=None, include_absent=True):
        from_date, to_date = getdate(from_date), getdate(to_date)
        wanted = {str(f) for f in ftag_ids} if ftag_ids else None

        with gzip.open(self.path, "rt", encoding="utf-8", errors="replace") as fh:
            for raw in csv.DictReader(fh):
                row = normalise(raw)
                if not row:
                    continue
                if not (from_date <= row["work_date"] <= to_date):
                    continue
                if wanted and row["ftag_id"] not in wanted:
                    continue
                if not include_absent and is_all_zero(row) and not row["hasmisspunch"]:
                    continue
                yield row


def get_source(mode: str = None, settings=None) -> BaseSource:
    """The configured source, or the one named — used by the parity test (I1)."""
    from caf.caf.doctype.ingress_sync_settings.ingress_sync_settings import get_settings

    settings = settings or get_settings()
    mode = mode or settings.source_mode

    if mode == "Snapshot CSV":
        return SnapshotSource(settings.snapshot_path)
    if mode == "Live MySQL":
        return LiveSource(settings)
    frappe.throw(_("Unknown Ingress source mode: {0}").format(mode))
