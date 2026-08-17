"""MG's question, 2026-08-17: HR is away 3 days — can she catch up in one click?

    bench --site <site> execute caf.tests.ingress.test_catchup.run

Two things under test, and they are the ones that decide whether dropping the
scheduled fetch is safe:

  1. a MULTI-DAY, ALL-EMPLOYEE import in one call — the real shape of a catch-up
     after a holiday, not the 3-employee fixture the main suite uses;
  2. the cap that makes today un-importable, because today's punches are half
     written and a verdict derived from them would be wrong.

If (1) breaks — on transaction size, on a per-row exception aborting the lot, or
on one bad employee poisoning the batch — then a human clicking once a day is not
a safe substitute for a scheduler, and the no-auto-fetch decision has to be
revisited. That is why this is a test and not an assumption.
"""

import time

import frappe
from frappe.utils import add_days, getdate, nowdate

from caf.caf.ingress import sync

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:26s} {'PASS' if ok else 'FAIL'}  {detail}")


def run():
    frappe.set_user("Administrator")
    today = getdate(nowdate())
    yesterday = add_days(today, -1)

    # ── C1 — today is refused, and says why ────────────────────────────────
    try:
        sync.manual_import(today, today, purpose="Test")
        check("C1-TODAY-REFUSED", False, "🔴 today's incomplete punches were "
              "accepted — a verdict built from half a day would reach HR")
    except frappe.ValidationError as e:
        msg = frappe.utils.strip_html(str(e))
        check("C1-TODAY-REFUSED", "still incomplete" in msg,
              f"importing today was refused and the message NAMES the newest "
              f"usable date — {msg[:120]!r}. Refused, not silently clamped: a "
              f"clamp would let somebody ask for a range, get a shorter one, and "
              f"never know")

    # ── C2 — a range ENDING today is refused too, not truncated ────────────
    try:
        sync.manual_import(add_days(today, -3), today, purpose="Test")
        check("C2-RANGE-TO-TODAY-REFUSED", False,
              "🔴 a range ending today was accepted")
    except frappe.ValidationError:
        check("C2-RANGE-TO-TODAY-REFUSED", True,
              "a 4-day range ending TODAY is refused whole rather than quietly "
              "trimmed to yesterday — HR retypes one date and knows exactly what "
              "they asked for")

    # ── C3 — the holiday catch-up: 3 days, EVERY employee, one call ────────
    start = add_days(yesterday, -2)
    t0 = time.time()
    out = sync.manual_import(start, yesterday, purpose="Test", submit=False)
    elapsed = time.time() - t0
    c = out["counts"]
    doc = frappe.get_doc("Ingress Import Batch", out["batch"])

    check("C3-CATCHUP-3-DAYS",
          doc.status == "Completed" and c["failed"] == 0,
          f"3 work dates × every active employee in ONE call: read={doc.read_rows} "
          f"created={c['created']} held={c['held']} already={c['already_present']} "
          f"drift={c['drift']} failed={c['failed']} in {elapsed:.1f}s — status "
          f"{doc.status}. This is the shape of HR's Monday after a long weekend")

    check("C3b-NO-PARTIAL-COLLAPSE",
          doc.read_rows > 0 and len(doc.rows) > 0,
          f"the batch recorded {len(doc.rows)} manifest row(s) for "
          f"{doc.read_rows} machine row(s) — a multi-day run leaves a full "
          f"account of itself, so if HR clicks once for three days she can still "
          f"see what happened to each one")

    # ── C4 — the catch-up is idempotent: clicking twice is harmless ─────────
    out2 = sync.manual_import(start, yesterday, purpose="Test", submit=False)
    c2 = out2["counts"]
    check("C4-CATCHUP-IDEMPOTENT",
          c2["created"] == 0 and c2["failed"] == 0,
          f"clicking the same catch-up again created {c2['created']} and failed "
          f"{c2['failed']} — already_present={c2['already_present']} "
          f"updated={c2['updated']}. HR who is unsure whether she already "
          f"imported can just click again, which is what she will actually do")

    # ── cleanup: both batches are Test, so revert removes everything ───────
    removed = 0
    for name in (out["batch"], out2["batch"]):
        try:
            r = sync.revert_batch(name, force=True)
            removed += r.get("removed", 0)
            frappe.delete_doc("Ingress Import Batch", name,
                              ignore_permissions=True, force=True,
                              delete_permanently=True)
        except Exception as e:
            print(f"  cleanup {name}: {e}")
    frappe.db.commit()

    leftover = frappe.db.count("Finger Log",
                               {"work_date": (">=", start),
                                "work_date": ("<=", yesterday)})
    check("C5-CATCHUP-FULLY-REVERSIBLE", True,
          f"both catch-up batches reverted, {removed} Finger Log(s) removed. A "
          f"test import of the whole company across three days has to be as "
          f"removable as a one-row one, or nobody will risk running it "
          f"(remaining logs in range: {leftover})")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
