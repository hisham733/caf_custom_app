"""CAF's intended permissions on STOCK doctypes — reported, then applied.

    bench --site <site> execute caf.scripts.caf_permission_matrix.run
    bench --site <site> execute caf.scripts.caf_permission_matrix.run --kwargs "{'apply':1}"

⚠️ **Not test-server-only.** These are site customisations (`Custom DocPerm`), so
production needs the same pass. Report first, always.

Stock doctypes cannot be fixed by editing our app's `.json` — the permissions live
in the site. Hence a script rather than a commit to a doctype file, and hence it
must be re-runnable and self-describing.

Each entry below records **MG's decision and the reasoning**, because a permission
row with no rationale is one somebody will "tidy" later.
"""

import frappe

# ─────────────────────────────────────────────────────────────── the decisions

CHANGES = [
    {
        "doctype": "Employee Performance Feedback",
        "role": "Employee",
        "why": (
            "MG, 2026-08-22. EPF is a complaint-or-compliment form, so ANY employee "
            "must be able to write one. But `too@` could cancel a feedback SOMEBODY "
            "ELSE wrote (HR-PF-2026-00052), which is not a role problem so much as a "
            "missing ownership test.\n"
            "        The rule MG set: the AUTHOR may retract their own — a complaint "
            "you regret should be withdrawable — and HR Manager may cancel anyone's. "
            "Nobody else. This is safe precisely because EPF carries no weight in the "
            "appraisal score (design rule), so retracting one changes no number."),
        "rows": [
            # Anyone may read and start one…
            {"if_owner": 0, "read": 1, "create": 1, "write": 0, "submit": 0,
             "cancel": 0, "delete": 0, "report": 1, "email": 1, "print": 1},
            # …but only the author may change, submit or retract it.
            {"if_owner": 1, "read": 1, "create": 0, "write": 1, "submit": 1,
             "cancel": 1, "delete": 0, "report": 1, "email": 1, "print": 1},
        ],
    },
    {
        "doctype": "Employee",
        "role": "Employee Self Service",
        "why": (
            "MG, 2026-08-22: *logically Mr A can see his own Emp.doc, but definitely "
            "with no write and save permission.* Stock grants this role `write` on "
            "Employee, so the four holders (fiza@, hisham@, mimi1@, nazifa1@) can "
            "edit employee master data through the self-service surface.\n"
            "        Read stays. Which FIELDS are visible is a separate, larger "
            "question (it needs permlevels on the Employee doctype) and is NOT "
            "attempted here — MG accepted read-all-fields as good enough for now."),
        "rows": [
            {"if_owner": 0, "read": 1, "create": 0, "write": 0, "submit": 0,
             "cancel": 0, "delete": 0, "report": 1, "email": 1, "print": 1},
        ],
    },
    # ── T-24 / OD-84 · CAF does not practise self-service attendance ─────────
    #
    # MG, 2026-09-02: *"CAF does not practise self attendance (even a long
    # distance driver has to physically log via the finger print machine)…
    # note CAF does not use Employee Self Service role or mobile check-in
    # attendance."*
    #
    # 🔴 Both doctypes were measured OPEN and INERT — 0 rows each, and
    # `enable_auto_attendance` is 0 on all 18 Shift Types, so nothing converts a
    # checkin into Attendance today. **Inert is one checkbox from live**, which
    # is why these are closed rather than left. FBR69: ERPNext holds exactly one
    # source of attendance, and the escape hatch for a machine-down day is in
    # INGRESS (paper, then HR keys it in), not here.
    *[
        {
            "doctype": dt,
            "role": role,
            "why": (
                f"T-24 / OD-84, MG 2026-09-02. CAF does not use self-service "
                f"attendance. {reason}\n"
                f"        READ stays where stock granted it — seeing a record is "
                f"not creating one, and removing read would break list views "
                f"employees can legitimately open. CREATE/WRITE/DELETE go."),
            "rows": [
                {"if_owner": 0, "read": read, "create": 0, "write": 0, "submit": 0,
                 "cancel": 0, "delete": 0, "report": read, "email": read,
                 "print": read},
            ],
        }
        for dt, role, read, reason in (
            ("Attendance Request", "Employee", 1,
             "`Attendance Request.on_submit` CREATES Attendance, so an open "
             "create here is a second source for a day the Finger Log already "
             "decided."),
            ("Attendance Request", "Employee Self Service", 0,
             "The role is a standing zero (OD-84); the row is written explicitly "
             "so a future stock upgrade cannot re-grant it silently."),
            ("Employee Checkin", "Employee", 1,
             "The HRMS mobile PWA writes Employee Checkin directly, and a Shift "
             "Type's `enable_auto_attendance` turns those into Attendance. That "
             "checkbox is the whole distance between inert and live."),
            ("Employee Checkin", "Employee Self Service", 0,
             "Same standing zero."),
        )
    ],
]

# Doctypes that must record who changed what. An audit trail is the whole reason
# MG accepted an UNSCOPED create on OT Approval — "any emp can file one, and
# ACTIVITIES logs who and when". Verified true for OT Approval (track_changes=1,
# 57 versions logged); EPF had it OFF, which would have left a retraction
# invisible. Both are asserted here so neither can quietly regress.
TRACK_CHANGES = ["OT Approval", "Employee Performance Feedback", "Employee",
                 "Finger Log", "Attendance", "Leave Application"]

PERM_FIELDS = ("read", "write", "create", "delete", "submit", "cancel", "amend",
               "report", "email", "print", "share", "export", "import", "select")


def _current(doctype, role):
    return frappe.get_all(
        "Custom DocPerm",
        filters={"parent": doctype, "role": role, "permlevel": 0},
        fields=["name", "if_owner"] + list(PERM_FIELDS))


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")
    acted = []

    for change in CHANGES:
        dt, role = change["doctype"], change["role"]
        print(f"\n{'=' * 74}\n{dt}  ·  role: {role}")
        print("  " + change["why"].replace("\n", "\n  "))

        existing = _current(dt, role)
        print(f"\n  NOW  ({len(existing)} row(s)):")
        for r in existing:
            print(f"    if_owner={r.if_owner}  " + " ".join(
                f"{f}={r.get(f) or 0}" for f in
                ("read", "write", "create", "submit", "cancel", "delete")))
        print(f"  WANT ({len(change['rows'])} row(s)):")
        for r in change["rows"]:
            print(f"    if_owner={r['if_owner']}  " + " ".join(
                f"{f}={r.get(f, 0)}" for f in
                ("read", "write", "create", "submit", "cancel", "delete")))

        if not apply:
            continue

        for r in existing:
            frappe.delete_doc("Custom DocPerm", r.name, ignore_permissions=True,
                              force=True, delete_permanently=True)
        for spec in change["rows"]:
            doc = frappe.new_doc("Custom DocPerm")
            doc.parent = dt
            doc.parenttype = "DocType"
            doc.parentfield = "permissions"
            doc.role = role
            doc.permlevel = 0
            doc.if_owner = spec["if_owner"]
            for f in PERM_FIELDS:
                setattr(doc, f, spec.get(f, 0))
            doc.flags.ignore_permissions = True
            doc.insert(ignore_permissions=True)
        acted.append(f"{dt}/{role}")

    print(f"\n{'=' * 74}\nTRACK CHANGES (the audit path MG relies on)")
    for dt in TRACK_CHANGES:
        on = frappe.db.get_value("DocType", dt, "track_changes")
        mark = "ok" if on else "🔴 OFF"
        print(f"  {dt:34s} track_changes={on}  {mark}")
        if apply and not on:
            frappe.db.set_value("DocType", dt, "track_changes", 1,
                                update_modified=False)
            acted.append(f"{dt}/track_changes")

    if not apply:
        print("\n(report only — pass apply=1 to write)")
        return {"would_change": len(CHANGES)}

    frappe.db.commit()
    frappe.clear_cache()
    print(f"\nDONE — {len(acted)} change(s): {acted}")
    print("Affected users must RELOAD their browser.")
    return {"changed": acted}
