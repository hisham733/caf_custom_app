"""HR's four join-date decisions, applied — and what each one costs.

    bench --site <site> execute caf.scripts.join_date_signoff_apply.run
    bench --site <site> execute caf.scripts.join_date_signoff_apply.apply
    bench --site <site> execute caf.scripts.join_date_signoff_apply.verify

⚠️ **Not test-server-only.** These are HR's sign-off answers on real people, and
the same four rows exist on production. T-28 records that `emp.join_date` is now
SIGNED OFF, which means this file is also the statement of what was signed.

WHY THIS EXISTS
---------------
`JOIN_DATE_for_HR_signoff.html` measured 89 employees against three sources —
ERPNext `date_of_joining`, Ingress `user.IssueDate`, and the machine's first raw
tap. 84 agreed, 1 had no Ingress account, and **4 disagreed**. HR answered on
2026-09-04, via MG:

    "sultan = 2018 sept 4"
    "the other 3 emp follow ingress_issueDate"

🔴 THE ANSWER GOES AGAINST THE PAGE'S OWN EVIDENCE FOR THREE OF THE FOUR, AND
   THAT WAS CHECKED BEFORE IT WAS APPLIED
------------------------------------------------------------------------------
For Uzzal, Aida and Syamimi the page said, in the "what the difference is"
column: *"ERPNext matches the machine's FIRST TAP exactly; Ingress is N days
later and looks like the first day somebody processed in Ingress, not a joining
date."* HR read that and chose Ingress anyway. That is her call to make — the
Ingress account may genuinely have been created on the day the paperwork was
done, and paperwork is what a joining date records.

But "her call" is only safe if somebody has priced it, so it was priced:

  Md Uzzal Hossan       2023-09-02 -> 2025-12-01   +821 days   NO leave effect
  Nur Aida Basirah      2025-08-04 -> 2025-12-01   +119 days   NO leave effect
  Nur Syamimi Sadli     2025-03-17 -> 2025-08-01   +137 days   🟡 -3 annual days
  Md Sultan Hosen Rubel 2018-08-04 -> 2018-09-04   + 31 days   NO leave effect

Three of the four are in **entitlement group A** — the 51 active employees HR
confirmed on 2026-09-04 hold no annual or medical entitlement — so moving their
joining date moves a service record and nothing else.

🟡 **Nur Syamimi Binti Sadli is the one exception.** She is in group B. At
2025-03-17 she has 21 completed months at cycle end and the formula gives her
**14.0** annual days; at 2025-08-01 she has 17 and it gives **11.0**. She holds
no 2026 annual allocation today, so nothing already granted is being taken away
— but the number the allocation run would produce for her drops by three days.
That is stated here so it is a decision on the record rather than a surprise in
January.

⚠️ Sultan's own change is +31 days and he is 8 years in, so it moves nothing at
all. It is applied because HR gave an explicit date, not because it matters.

WHAT IS NOT DONE HERE
---------------------
`Yow Kwee Chin` — HR confirmed on 2026-09-04 that this employee is a director
with **no Ingress account**, which is why the page could not check him. His
ERPNext date (2005-10-01) stands unchallenged and unchanged. He is the reason
`attendance_device_id` is NOT being made mandatory (MG, 2026-09-04).

⚠️ `db.set_value` writes no Version (OD-26), so each change leaves a Comment
naming HR, the date, and the source of the new value.
"""

import frappe
from frappe.utils import getdate

# (employee, who, from, to, source of the new date, leave effect)
DECISIONS = [
    ("HR-EMP-00030", "Md Sultan Hosen Rubel", "2018-08-04", "2018-09-04",
     "HR gave the date explicitly ('sultan = 2018 sept 4'); it is also the "
     "Ingress IssueDate, so the two agree.",
     "none — group A (no entitlement), and 8 years of service either way"),

    ("HR-EMP-00072", "Md Uzzal Hossan", "2023-09-02", "2025-12-01",
     "Ingress user.IssueDate, per HR's 'the other 3 emp follow "
     "ingress_issueDate'. ⚠️ 821 days after his first finger tap (2023-08-29).",
     "none — group A (no entitlement). Service record moves 2y3m"),

    ("HR-EMP-00153", "Nur Aida Basirah Binti Mohd Adenan", "2025-08-04", "2025-12-01",
     "Ingress user.IssueDate, per HR. ⚠️ 119 days after her first tap, which "
     "matched ERPNext exactly.",
     "none — group A (no entitlement)"),

    ("HR-EMP-00121", "Nur Syamimi Binti Sadli", "2025-03-17", "2025-08-01",
     "Ingress user.IssueDate, per HR. ⚠️ 137 days after her first tap, which "
     "matched ERPNext exactly.",
     "🟡 GROUP B — annual entitlement 14.0 -> 11.0 for the 2026 cycle "
     "(21 completed months -> 17). No allocation exists yet, so nothing "
     "granted is withdrawn"),
]

HR_NOTE = ("HR sign-off 2026-09-04 (JOIN_DATE_for_HR_signoff.html, "
           "question 1 of 4 rows). Recorded by MG.")


def _state():
    out = []
    for emp, who, was, want, source, effect in DECISIONS:
        now = frappe.db.get_value("Employee", emp, "date_of_joining")
        out.append({
            "employee": emp, "who": who, "expected_before": getdate(was),
            "now": getdate(now) if now else None, "want": getdate(want),
            "source": source, "effect": effect,
        })
    return out


def run():
    """Report only. Prints what would change and what each change costs."""
    print(f"\n{'=' * 78}\nJOIN DATE — HR's four decisions, 2026-09-04\n{'=' * 78}")
    todo = 0
    for r in _state():
        if r["now"] is None:
            print(f"\n🔴 {r['employee']} {r['who']} — NOT FOUND")
            continue
        drift = r["now"] != r["expected_before"]
        done = r["now"] == r["want"]
        mark = "✅ already applied" if done else ("🔴 DRIFT — the page measured "
                                                 f"{r['expected_before']}, the site now "
                                                 f"holds {r['now']}" if drift else
                                                 f"→ WOULD CHANGE {r['now']} to {r['want']}")
        print(f"\n{r['employee']}  {r['who']}")
        print(f"  {mark}")
        print(f"  days moved : {(r['want'] - r['now']).days:+d}")
        print(f"  source     : {r['source']}")
        print(f"  leave      : {r['effect']}")
        if not done and not drift:
            todo += 1

    print(f"\n{'-' * 78}\n{todo} change(s) pending. Run `apply` to write them.")
    print("Yow Kwee Chin: HR confirmed director, no Ingress account — unchanged.")
    return {"pending": todo}


def apply():
    """Write the four dates. Refuses any row whose current value has drifted."""
    frappe.set_user("Administrator")
    changed, skipped = [], []

    for r in _state():
        if r["now"] is None:
            skipped.append((r["employee"], "not found"))
            continue
        if r["now"] == r["want"]:
            skipped.append((r["employee"], "already correct"))
            continue
        if r["now"] != r["expected_before"]:
            # Somebody else moved it since the page was measured. Refusing is the
            # only safe answer — HR signed off on a specific before/after pair.
            skipped.append((r["employee"],
                            f"🔴 DRIFT: expected {r['expected_before']}, found {r['now']}"))
            continue

        frappe.db.set_value("Employee", r["employee"], "date_of_joining",
                            r["want"], update_modified=False)
        frappe.get_doc("Employee", r["employee"]).add_comment(
            "Comment",
            f"date_of_joining {r['now']} → {r['want']}. {HR_NOTE} "
            f"Source: {r['source']} Leave effect: {r['effect']}")
        changed.append((r["employee"], r["who"], str(r["now"]), str(r["want"])))

    frappe.db.commit()
    print(f"\nCHANGED {len(changed)}:")
    for c in changed:
        print(f"    {c[0]} {c[1][:34]:34s} {c[2]} → {c[3]}")
    print(f"SKIPPED {len(skipped)}:")
    for s in skipped:
        print(f"    {s[0]} {s[1]}")
    return {"changed": changed, "skipped": skipped}


def verify():
    """Both directions: the four dates are HR's, and nobody else moved."""
    fails = 0
    for r in _state():
        ok = r["now"] == r["want"]
        print(f"JD-{r['employee']} {'PASS' if ok else 'FAIL'}  "
              f"{r['who'][:32]:32s} is {r['now']} (want {r['want']})")
        fails += 0 if ok else 1

    # The 84 that agreed must still agree — a bulk edit would show here.
    total = frappe.db.count("Employee", {"status": "Active"})
    none_missing = frappe.db.count("Employee",
                                   {"status": "Active", "date_of_joining": ["is", "not set"]})
    ok2 = none_missing == 0
    print(f"JD-NO-BLANKS {'PASS' if ok2 else 'FAIL'}  active employees without a "
          f"joining date: {none_missing} of {total} — want 0")
    fails += 0 if ok2 else 1

    print(f"\n{'clean' if not fails else str(fails) + ' problem(s)'}")
    return fails
