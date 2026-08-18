"""The daily "nobody imported yesterday" reminder.

    bench --site <site> execute caf.tests.ingress.test_reminder.run

The reminder is the safety net under FBR44, so its failure mode is the quiet one:
it does not error, it simply never fires, and nobody learns that attendance stopped
arriving. Every assertion here is about it firing when it should and staying quiet
when it should not.

Self-cleaning. Restores the settings it changes, and removes the notifications it
causes, whatever happens.
"""

import frappe
from frappe.utils import add_days, getdate, nowdate

from caf.caf.ingress import reminder

RESULTS = []
SUBJ = "No attendance imported"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:28s} {'PASS' if ok else 'FAIL'}  {detail}")


def _sent():
    return frappe.get_all("Notification Log",
                          filters={"subject": ("like", f"%{SUBJ}%")},
                          fields=["name", "for_user", "read"])


def _wipe():
    for n in _sent():
        frappe.delete_doc("Notification Log", n.name, ignore_permissions=True,
                          force=True, delete_permanently=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    s = frappe.get_doc("Ingress Sync Settings")
    before = (s.get("reminder_enabled"), s.get("reminder_recipients"))
    yesterday = add_days(getdate(nowdate()), -1)
    made_batch = None

    def setting(enabled, recipients):
        frappe.db.set_value("Ingress Sync Settings", "Ingress Sync Settings",
                            {"reminder_enabled": enabled,
                             "reminder_recipients": recipients},
                            update_modified=False)
        frappe.clear_cache(doctype="Ingress Sync Settings")

    try:
        # ── R1 — fires when yesterday is not covered ───────────────────────
        _wipe()
        setting(1, "natalie@caffood.com\nfiza@caffood.com")
        reminder.daily_import_check()
        sent = _sent()
        check("R1-FIRES-WHEN-MISSING",
              {n.for_user for n in sent} == {"natalie@caffood.com", "fiza@caffood.com"},
              f"with no batch covering {yesterday}, exactly the two NAMED "
              f"recipients were notified ({sorted(n.for_user for n in sent)}) — not "
              f"every HR Manager, because the directors hold the role and do not "
              f"do the import")

        # ── R2 — does not stack ────────────────────────────────────────────
        reminder.daily_import_check()
        check("R2-NO-STACKING", len(_sent()) == 2,
              f"running it again left {len(_sent())} notification(s), not 4. A "
              f"reminder that repeats itself is one people learn to click away, "
              f"and the scheduler may retry a queue")

        # ── R3 — silent when the day IS covered ────────────────────────────
        _wipe()
        b = frappe.new_doc("Ingress Import Batch")
        b.run_type, b.purpose, b.status = "Manual", "Test", "Completed"
        b.from_date = b.to_date = yesterday
        b.flags.ignore_permissions = True
        b.insert(ignore_permissions=True)
        made_batch = b.name
        frappe.db.commit()

        reminder.daily_import_check()
        check("R3-SILENT-WHEN-COVERED", len(_sent()) == 0,
              f"with a COMPLETED batch covering {yesterday}, nothing was sent. A "
              f"reminder that fires on days the job was done is one that stops "
              f"being read")

        # ── R4 — a FAILED batch does not count as covered ──────────────────
        _wipe()
        frappe.db.set_value("Ingress Import Batch", made_batch, "status", "Failed",
                            update_modified=False)
        frappe.clear_cache()
        reminder.daily_import_check()
        check("R4-FAILED-STILL-REMINDS", len(_sent()) == 2,
              f"a FAILED batch for {yesterday} still triggered the reminder "
              f"({len(_sent())} sent). 🔴 The import was ATTEMPTED and did not "
              f"land — which is exactly when somebody needs telling, and the case "
              f"a naive 'does a batch exist?' check would miss")

        # ── R5 — the off switch works ──────────────────────────────────────
        _wipe()
        setting(0, "natalie@caffood.com")
        reminder.daily_import_check()
        check("R5-OFF-SWITCH", len(_sent()) == 0,
              "with the reminder disabled nothing is sent — the setting is read, "
              "not decorative")

        # ── R6 — blank recipients falls back to the HR Manager role ────────
        _wipe()
        setting(1, "")
        people = reminder._recipients(frappe.get_cached_doc("Ingress Sync Settings"))
        check("R6-ROLE-FALLBACK",
              len(people) > 0 and "Administrator" not in people,
              f"blank recipients resolves to the {len(people)} enabled HR Manager "
              f"holder(s) and EXCLUDES Administrator — notifying the system account "
              f"reminds nobody")

    finally:
        _wipe()
        if made_batch and frappe.db.exists("Ingress Import Batch", made_batch):
            frappe.delete_doc("Ingress Import Batch", made_batch,
                              ignore_permissions=True, force=True,
                              delete_permanently=True)
        setting(before[0], before[1])
        frappe.db.commit()
        print(f"\nrestored: reminder_enabled={before[0]!r} recipients={before[1]!r}")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
