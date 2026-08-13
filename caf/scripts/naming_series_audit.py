"""Audit every naming counter against the rows that already exist. PROTOCOL §D1.

Purpose : find naming-series counters that a bulk import left behind, BEFORE the
          next insert collides. §D1 is 🔴 #3 in the protocol's "five that cost the
          most", and it has now bitten this project twice.
Run     : bench --site <site> execute caf.scripts.naming_series_audit.audit
          bench --site <site> execute caf.scripts.naming_series_audit.fix
Refs    : PROTOCOL §D1/§D1b · frappe-dev-protocol skill §5 "zero-count rule"

🔴 WHY THIS EXISTS, AND WHY IT IS A SCRIPT AND NOT A NOTE
---------------------------------------------------------
Rows imported with **explicit names** never advance `tabSeries`. The counter
stays where it was, and the next document the app tries to create restarts at 1
and collides with an imported row — **from the desk UI as much as from a test**.

Found the first time on OT Approval (835 of 840 dates blocked). Found again
2026-08-13 on **Leave Allocation**: `HR-LAL-2026-` read **1** while **55** rows
existed, so the next 55 allocations would have failed with
`DuplicateEntryError`. Nobody could have been granted leave — and nothing says
so until somebody tries.

The skill's rule is *"after any bulk import, assert `tabSeries.current >=
max(suffix)` for every series key in use"*. A rule nobody can run is a rule that
gets skipped, so here it is as one command.

⚠️ `tabSeries` has **no `modified` column**, so it is raw SQL only — `get_value`
cannot read it (§D1b).

Changelog
---------
1.0  2026-08-13  Initial — after Leave Allocation collided
"""

import re

import frappe

SUFFIX = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)$")


def _series_doctypes():
    """Every DocType named by a series with a numeric tail.

    🔴 The first version filtered on `"#" in autoname` and MISSED THE ONE THAT
    STARTED THIS. Most doctypes — Leave Allocation included — carry
    `autoname = "naming_series:"` and keep the `.####` in the **field's
    options**, not in `autoname`. The audit reported a clean bill on the exact
    counter that was 54 short.

    §F2 wearing yet another hat: a check that finds nothing is worthless until
    you have proven it CAN find the thing you already know is there.
    """
    skip = ("field:", "prompt", "hash", "autoincrement", "uuid")
    out = []
    for d in frappe.get_all("DocType", filters={"issingle": 0, "istable": 0},
                            fields=["name", "autoname"]):
        auto = (d.get("autoname") or "").strip()
        if not auto or auto.lower().startswith(skip):
            continue
        out.append(d.name)
    return out


def _gaps():
    """[(doctype, prefix, current, max_used)] where the counter is behind."""
    out = []
    current = {r[0]: int(r[1]) for r in frappe.db.sql(
        "SELECT name, current FROM tabSeries")}

    for dt in _series_doctypes():
        table = f"tab{dt}"
        try:
            names = frappe.db.sql(f"SELECT name FROM `{table}`", pluck=True)
        except Exception:
            continue                       # table not created yet
        highest = {}
        for name in names:
            m = SUFFIX.match(name or "")
            if not m:
                continue
            prefix, num = m.group("prefix"), int(m.group("num"))
            if len(m.group("num")) < 3:
                continue                   # not a padded series tail
            # ⚠️ FALSE POSITIVES, and they were loud: `Data Import` names end in
            # a MICROSECOND stamp ("… on 2026-07-31 13:24:15.341225"), which
            # reads as a six-digit counter and reported 30 fictional gaps of
            # ~500,000 each. A real series prefix ends with `-`, or is already
            # in tabSeries. Anything else is a timestamp wearing a costume.
            if not prefix.endswith("-") and prefix not in current:
                continue
            highest[prefix] = max(highest.get(prefix, 0), num)
        for prefix, top in sorted(highest.items()):
            cur = current.get(prefix)
            if cur is None or cur < top:
                out.append((dt, prefix, cur, top))
    return out


def audit():
    """Read-only. Prints every counter that would collide on the next insert."""
    gaps = _gaps()
    if not gaps:
        print("No naming-series gaps. Every counter is at or above the rows in use.")
        return {"gaps": []}

    print(f"🔴 {len(gaps)} naming counter(s) BEHIND the rows that already exist.\n")
    print(f"{'DocType':32s} {'series':22s} {'current':>8s} {'max used':>9s} "
          f"{'collisions':>11s}")
    for dt, prefix, cur, top in gaps:
        shown = "MISSING" if cur is None else cur
        gap = top - (cur or 0)
        print(f"{dt:32s} {prefix:22s} {str(shown):>8s} {top:>9} {gap:>11}")
    print("\nThe next insert on each of these restarts inside the used range and "
          "fails with DuplicateEntryError — from the desk as much as from code.")
    print("Run `.fix` to advance them.")
    return {"gaps": gaps}


def fix():
    """Advance every behind counter to the highest name actually in use.

    ⚠️ Only ever moves a counter FORWARD. Lowering one would re-open the
    collision it is there to prevent.
    """
    gaps = _gaps()
    if not gaps:
        print("Nothing to fix.")
        return {"fixed": []}

    fixed = []
    for dt, prefix, cur, top in gaps:
        if cur is None:
            frappe.db.sql("INSERT INTO tabSeries (name, current) VALUES (%s, %s)",
                          (prefix, top))
        else:
            frappe.db.sql("UPDATE tabSeries SET current = %s WHERE name = %s",
                          (top, prefix))
        fixed.append((dt, prefix, cur, top))
        print(f"  {prefix:22s} {str(cur):>8s} ➜ {top}   ({dt})")
    frappe.db.commit()

    left = _gaps()
    print(f"\nfixed {len(fixed)}; remaining gaps: {len(left)}")
    return {"fixed": fixed, "remaining": left}
