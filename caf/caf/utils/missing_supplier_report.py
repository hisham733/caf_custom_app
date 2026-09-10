"""
Missing supplier morning report.

Finds Purchase Receipts posted YESTERDAY whose supplier is set to the configured
"missing" supplier (default a Supplier document named 'SUPPLIER MISSING').
Cancelled Purchase Receipts are excluded. Configurable in Caf Settings (enabled,
send time, which supplier counts as missing, and per-channel recipients).
"""

import frappe
from frappe.utils import add_days, today

from caf.caf.utils.notifications import _send_report_message


def _get_settings():
    try:
        st = frappe.get_single("Caf Settings")
    except Exception:
        st = None
    return st


def get_missing_supplier_prs(supplier=None, for_date=None):
    """Return non-cancelled Purchase Receipts for the given (missing) supplier.

    Falls back to the supplier configured in Caf Settings, then to a literal
    'SUPPLIER MISSING' default. Only Purchase Receipts posted yesterday are
    returned (or posted on the given for_date when provided).
    """
    if not supplier:
        st = _get_settings()
        supplier = (st.get("supplier_missing_supplier") if st else None) or "SUPPLIER MISSING"

    post_date = for_date or add_days(today(), -1)

    return frappe.db.sql(
        """
        SELECT
            name,
            supplier,
            supplier_name,
            posting_date,
            posting_time,
            grand_total,
            set_warehouse,
            status
        FROM `tabPurchase Receipt`
        WHERE supplier = %(supplier)s
            AND docstatus <> 2
            AND DATE(posting_date) = %(post_date)s
        ORDER BY posting_date DESC, creation DESC
        """,
        {"supplier": supplier, "post_date": post_date},
        as_dict=True,
    )


def build_missing_supplier_message(rows, supplier=None):
    """Format missing-supplier Purchase Receipts into a readable message."""
    now = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M")
    supplier = supplier or "SUPPLIER MISSING"

    message = "⚠️ *Missing Supplier Purchase Receipts*\n"
    message += f"📅 {now}\n"
    message += f"🛒 Supplier: {supplier}\n"
    message += "--------------------------\n\n"
    message += f"🔎 {len(rows)} Purchase Receipt(s) with missing supplier:\n\n"

    for r in rows:
        message += f"*{r.get('name') or ''}*\n"
        if r.get("posting_date"):
            message += f"  📆 Posting: {r['posting_date']}"
            if r.get("posting_time"):
                message += f" {r['posting_time']}"
            message += "\n"
        if r.get("supplier_name"):
            message += f"  🏷️ Supplier Name: {r['supplier_name']}\n"
        if r.get("grand_total") is not None:
            message += f"  💰 Total: {r['grand_total']}\n"
        if r.get("set_warehouse"):
            message += f"  📦 Warehouse: {r['set_warehouse']}\n"
        if r.get("status"):
            message += f"  🚦 Status: {r['status']}\n"
        message += "\n"

    return message


def _is_enabled():
    st = _get_settings()
    if st is None:
        return True
    return bool(st.get("supplier_enabled") if st.get("supplier_enabled") is not None else 1)


def send_missing_supplier_warning():
    """Scheduled entry point: warn about Purchase Receipts with missing supplier.

    Respects the 'enabled' flag in Caf Settings; sends nothing when disabled."
    """
    if not _is_enabled():
        return

    st = _get_settings()
    supplier = (st.get("supplier_missing_supplier") if st else None) or "SUPPLIER MISSING"
    rows = get_missing_supplier_prs(supplier)
    if not rows:
        return

    message = build_missing_supplier_message(rows, supplier)
    _send_report_message("supplier", message)


@frappe.whitelist()
def manual_missing_supplier_warning():
    """Manually trigger the missing-supplier warning (for testing)."""
    st = _get_settings()
    supplier = (st.get("supplier_missing_supplier") if st else None) or "SUPPLIER MISSING"
    rows = get_missing_supplier_prs(supplier)
    if not rows:
        return {"success": True, "message": "No missing-supplier Purchase Receipts found.", "count": 0}

    message = build_missing_supplier_message(rows, supplier)
    _send_report_message("supplier", message)
    return {"success": True, "count": len(rows), "message": f"Warning sent for {len(rows)} Purchase Receipt(s)."}
