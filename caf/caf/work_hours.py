"""Worked hours from the punches — OD-59.

⚠️ `work` is NOT elapsed time. It is **the scheduled shift actually served**:

    work  = min(out, shift_end) − max(in, shift_start) − lunch      clamped to [0, net]
    short = net − work
    net   = (shift_end − shift_start) − caf_lunch_minutes

Anything outside the shift window is **overtime**, never `work` — which is exactly
why `work + short = net` holds to the minute, and why that pair is the import's
own checksum.

MEASURED (plan §3.9.5a): this reproduces Ingress' own `workhour` **exactly on
96.0%** of the 23,422 rows that carry both punches, 98.7% within 15 minutes.
The naive `(out − in) − lunch` matched **10 rows out of 24,963** — if you find
yourself writing elapsed time, this is the mistake you are repeating.

WHAT IT CANNOT DO, AND WHY THAT IS CORRECT
------------------------------------------
It returns `None` when `time_in` or `out` is missing. Ingress substitutes
`net/2` or `0` there, but that is a **policy for a missing punch**, not a
computation — and **FDR4** forbids inferring a decision from an absent
observation. Those rows are `caf_not_full_day` and go to HR (OD-58).
"""

import datetime

import frappe
from frappe.utils import cint

DAY = 24 * 60


def to_minutes(value):
    """Minutes since midnight from a Frappe Time (timedelta), a string, or a time."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.timedelta):
        return int(value.total_seconds() // 60)
    if isinstance(value, datetime.time):
        return value.hour * 60 + value.minute
    if isinstance(value, str):
        parts = value.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            return None
    return None


def has_punch(value):
    """A punch is present only if it is set AND not the all-zero sentinel.

    ⚠️ The importer writes '00:00:00', never NULL — testing for NULL is the trap
    that cost this project a withdrawn decision (OD-49). Treat 00:00 as absent.
    """
    m = to_minutes(value)
    return m is not None and m != 0


def net_minutes(params) -> int:
    """The shift's contracted minutes: (end − start) − lunch."""
    start, end = to_minutes(params.get("start_time")), to_minutes(params.get("end_time"))
    if start is None or end is None:
        return 0
    if end <= start:                       # a night shift crossing midnight
        end += DAY
    return max(0, end - start - cint(params.get("caf_lunch_minutes")))


def compute(time_in, break_, resume, out, params):
    """Return (work_hours, short_hours) in DECIMAL hours, or (None, None).

    `None` means "not computable" — the caller must not invent a number.
    """
    start, end = to_minutes(params.get("start_time")), to_minutes(params.get("end_time"))
    i, o = to_minutes(time_in), to_minutes(out)

    if start is None or end is None or not has_punch(time_in) or not has_punch(out):
        return None, None

    if end <= start:
        end += DAY
    if o <= i:                             # tapped out after midnight — FBR28
        o += DAY

    net = max(0, end - start - cint(params.get("caf_lunch_minutes")))

    # Only the part of the punch interval that overlaps the scheduled shift.
    served = min(o, end) - max(i, start)
    if served <= 0:
        return 0.0, round(net / 60.0, 4)

    # The ACTUAL lunch when both punches exist, otherwise the shift's allowance.
    # Measured: the residual mismatches were people who took a LONGER lunch than
    # the allowance, and Ingress deducts what they actually took.
    b, r = to_minutes(break_), to_minutes(resume)
    if has_punch(break_) and has_punch(resume) and r > b:
        lunch = r - b
    else:
        lunch = cint(params.get("caf_lunch_minutes"))

    work = max(0, min(served - lunch, net))
    return round(work / 60.0, 4), round((net - work) / 60.0, 4)


def required_punches(params) -> tuple:
    """Which punches this shift must have for a day to be COMPLETE — OD-58.

    The lunch pair is required only where the shift actually has a lunch:
    `special` and `8:30am no Sat` carry `caf_lunch_minutes = 0`, and demanding a
    lunch punch there would manufacture a false miss-punch on every single row.
    """
    if cint(params.get("caf_lunch_minutes")) > 0:
        return ("time_in", "break", "resume", "out")
    return ("time_in", "out")


def is_all_zero(doc) -> bool:
    """The ABSENT row: nobody punched at all.

    Complete *by absence* — it is the observation that he did not come, and it is
    what FBR37 counts. It must never be treated as an incomplete record.
    """
    return not any(has_punch(doc.get(f)) for f in ("time_in", "break", "resume", "out"))


def missing_punches(doc, params) -> list:
    """The punches this shift needed and did not get. Empty means complete."""
    if is_all_zero(doc):
        return []
    return [f for f in required_punches(params) if not has_punch(doc.get(f))]
