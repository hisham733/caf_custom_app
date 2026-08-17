"""Ingress ➜ Finger Log — the Chunk 3 entry point, now a shim.

⚠️ **The feature moved to `caf.caf.ingress`** (2026-08-17). This module stays
because it is named in places that are not code and cannot be refactored by a
grep: `OpenCode_analysis/README.md`, `FIX_DECISION_LOG.md` F-3, and the muscle
memory of anyone who has run

    bench --site … execute caf.caf.ingress_import.import_month --args 2026,7

Those keep working. What they do NOW, and what changed:

  · the source can be the LIVE Ingress MySQL, not only `/tmp/attendance.csv.gz`
    (configured on **Ingress Sync Settings**);
  · every run produces an **Ingress Import Batch** — a manifest you can revert,
    which is what makes a test import disposable;
  · 🔴 a Finger Log **HR cancelled is no longer re-created**. The old `run()`
    filtered `docstatus < 2`, so a cancel was silently undone by the next run.
    Only an explicit human re-import (`allow_recreate`) brings such a day back.

The real code, and the reasoning, live in:
    caf/caf/ingress/source.py   the two readers, and what is never imported
    caf/caf/ingress/sync.py     the ownership rule and the import loop
"""

import frappe

from caf.caf.ingress.sync import manual_import


def run(snapshot: str = None, from_date=None, to_date=None, submit: bool = True,
        limit: int = 0):
    """Chunk 3's signature, kept. `limit` is accepted and ignored — a batch is
    bounded by its date range and its employee filter now, which is the same
    control expressed in terms a person can reason about.
    """
    if not (from_date and to_date):
        frappe.throw("run() needs from_date and to_date. For a whole month use "
                     "import_month(year, month).")
    if limit:
        frappe.msgprint("`limit` is ignored — narrow the date range or pass "
                        "employees instead.", alert=True)

    return manual_import(from_date, to_date, submit=submit, purpose="Production",
                         source_mode="Snapshot CSV" if snapshot else None)


def import_month(year, month, snapshot: str = None):
    """One calendar month. Unchanged signature."""
    from calendar import monthrange

    year, month = int(year), int(month)
    last = monthrange(year, month)[1]
    return run(snapshot, f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}")
