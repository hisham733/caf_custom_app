"""The shapes the DESK actually sends — which the other suites never reproduced.

    bench --site <site> execute caf.tests.ingress.test_desk_payloads.run

🔴 Why this file exists. MG opened the import dialog on 2026-08-18, left *Limit to*
blank — the normal daily case — and got:

    json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

The MAIN path was broken while every narrower one worked, and the full gate was
green throughout. The reason is uncomfortable and worth keeping: every existing
test passes `employees` as a real Python list, or omits it so the value is `None`.
Neither is what the browser sends. Frappe's form-encoded transport turns the JS
`null` into the empty string `""`, and `frappe.parse_json("")` raises.

So these assertions deliberately use the WIRE shapes — strings, empties and all —
rather than the convenient Python ones. A test that only ever calls a function the
way the tests call it cannot find this class of bug.
"""

import frappe

from caf.caf.doctype.ingress_import_batch.ingress_import_batch import _as_employee_list

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:26s} {'PASS' if ok else 'FAIL'}  {detail}")


def run():
    frappe.set_user("Administrator")

    # ── the exact payload that broke ────────────────────────────────────────
    cases = [
        ("empty string  (Limit to left blank — THE BUG)", "", None),
        ("the literal 'null'", "null", None),
        ("empty JSON array", "[]", None),
        ("None (key omitted)", None, None),
        ("whitespace only", "   ", None),
        ("JSON array of one", '["HR-EMP-00006"]', ["HR-EMP-00006"]),
        ("JSON array of two", '["HR-EMP-00006","HR-EMP-00008"]',
         ["HR-EMP-00006", "HR-EMP-00008"]),
        ("a bare unwrapped id", "HR-EMP-00006", ["HR-EMP-00006"]),
        ("a real python list", ["HR-EMP-00006"], ["HR-EMP-00006"]),
        ("list with blanks in it", ["HR-EMP-00006", "", "  "], ["HR-EMP-00006"]),
    ]
    bad = []
    for label, sent, expected in cases:
        try:
            got = _as_employee_list(sent)
        except Exception as e:
            got = f"RAISED {type(e).__name__}: {e}"
        if got != expected:
            bad.append(f"{label}: sent {sent!r} → {got!r}, wanted {expected!r}")

    check("DP1-EMPLOYEE-SHAPES", not bad,
          f"all {len(cases)} wire shapes normalise correctly — empty string, "
          f"'null', '[]', whitespace, JSON arrays, a bare id and real lists. "
          f"The empty string is the one that reached MG: the dialog sends JS "
          f"`null`, the transport makes it `''`, and parse_json('') raises"
          if not bad else f"🔴 {bad}")

    # ── the checkbox, which is just as string-shaped ────────────────────────
    from frappe.utils import cint
    flag_cases = [("1", 1), (1, 1), ("0", 0), (0, 0), ("", 0), (None, 0), (True, 1)]
    flag_bad = [f"{s!r}→{cint(s)} wanted {w}" for s, w in flag_cases if cint(s) != w]
    check("DP2-CHECKBOX-SHAPES", not flag_bad,
          f"`submit` survives every shape a checkbox arrives in {flag_cases} — "
          f"cint, not int(), because int('') raises exactly as loudly as the "
          f"JSON bug did"
          if not flag_bad else f"🔴 {flag_bad}")

    # ── end to end through the whitelisted endpoint, blank Limit-to ─────────
    from caf.caf.doctype.ingress_import_batch.ingress_import_batch import (
        run_manual_import,
    )
    from frappe.utils import add_days, getdate, nowdate

    day = add_days(getdate(nowdate()), -1)
    made = None
    try:
        out = run_manual_import(from_date=str(day), to_date=str(day),
                                employees="", submit="0", purpose="Test")
        made = out.get("batch")
        ok, why = bool(made), f"batch {made} created, read {out['counts']['read_rows']} row(s)"
    except Exception as e:
        msg = frappe.utils.strip_html(str(e))
        # An unreachable machine is a legitimate outcome here and not this
        # test's business — the point is that it got PAST argument parsing.
        ok = "unreachable" in msg
        why = f"reached the source and failed there, not in parsing — {msg[:80]}"
    check("DP3-BLANK-LIMIT-TO-WORKS", ok,
          f"the real endpoint accepts the desk's blank-field payload "
          f"(employees='', submit='0') — {why}. This is the exact call that "
          f"raised JSONDecodeError for MG")

    if made:
        from caf.caf.ingress.sync import revert_batch
        try:
            revert_batch(made, force=True)
            frappe.delete_doc("Ingress Import Batch", made, ignore_permissions=True,
                              force=True, delete_permanently=True)
            frappe.db.commit()
        except Exception as e:
            print(f"  cleanup: {e}")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
