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


# The three shapes a working day may take — MG, 2026-08-22. Stored on
# `Shift Type.caf_required_punches`.
PUNCH_FULL = "In + Out + Lunch pair"
PUNCH_IN_OUT = "In + Out only"
PUNCH_EITHER = "In OR Out only"


def required_punches(params) -> tuple:
    """Which punches this shift must have for a day to be COMPLETE — OD-58.

    🔴 Read from `caf_required_punches`, NOT from `caf_lunch_minutes` any more.

    That field used to answer two different questions with one number — *"how much
    lunch do I deduct?"* and *"must there be a lunch punch?"* — and for 8 employees
    the answers differ: they take lunch, they simply never tap for it. The only way
    to say the second was `caf_lunch_minutes = 0`, which also stopped the
    DEDUCTION and inflated their hours by an hour a day.

    Cost of the old shape, measured: 214 days held across those 8, none able to
    become an Attendance record, and a worklist so full of them that the six
    genuine miss-punches inside it were invisible.

    ⚠️ The fallback is `caf_lunch_minutes` for any shift where the new field is
    unset — every existing shift keeps behaving exactly as before until somebody
    chooses otherwise.
    """
    rule = (params.get("caf_required_punches") or "").strip()

    if rule == PUNCH_EITHER:
        # Handled by the caller: one punch is enough to PASS, but neither
        # `compute()` nor anything else can measure such a day — see
        # `is_single_punch_day`.
        return ()
    if rule == PUNCH_IN_OUT:
        return ("time_in", "out")
    if rule == PUNCH_FULL:
        return ("time_in", "break", "resume", "out")

    # Unset — the pre-2026-08-22 behaviour, kept so nothing changes by surprise.
    if cint(params.get("caf_lunch_minutes")) > 0:
        return ("time_in", "break", "resume", "out")
    return ("time_in", "out")


def is_single_punch_shift(params) -> bool:
    """Does this shift credit a whole day from one tap?"""
    return (params.get("caf_required_punches") or "").strip() == PUNCH_EITHER


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

    # "In OR Out only": ANY single punch completes the day. `required_punches`
    # returns () for this rule, so the comprehension below would call it complete
    # even on an all-zero row — which `is_all_zero` above has already handled, but
    # the intent is worth stating rather than relying on ordering.
    if is_single_punch_shift(params):
        return [] if any(has_punch(doc.get(f))
                         for f in ("time_in", "break", "resume", "out")) \
            else ["a punch"]

    return [f for f in required_punches(params) if not has_punch(doc.get(f))]
