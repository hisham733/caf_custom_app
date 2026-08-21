"""
Material shortage warning report.

Scheduled every 1.5 hours. Sends a WhatsApp + Telegram message only when an
active Work Order planned for today has a raw material shortage in its source
warehouse.

The query mirrors the "not enough material" Metabase report, with two
differences requested by the user:
  - only Work Orders whose planned_start_date is today
  - items with no stock record (no bin row) are treated as a shortage
    (actual_qty = 0) instead of being silently skipped
"""

import frappe
from frappe.utils import flt, today

from caf.caf.utils.notifications import _send_report_message


SHORTAGE_SQL = """
SELECT
    wo.name AS work_order,
    wo.production_item,
    wo.custom_link_id,
    wo.planned_start_date,
    wo.status,
    wi.item_code,
    wi.item_name,
    wi.required_qty,
    wi.source_warehouse,
    COALESCE(b.actual_qty, 0) AS actual_qty,
    it.item_group
FROM
    `tabWork Order` wo
    JOIN `tabWork Order Item` wi ON wo.name = wi.parent
    LEFT JOIN `tabBin` b
        ON wi.item_code = b.item_code
        AND wi.source_warehouse = b.warehouse
    LEFT JOIN `tabItem` it ON wi.item_code = it.name
WHERE
    wi.required_qty > COALESCE(b.actual_qty, 0)
    AND wo.status NOT IN ('Cancelled', 'Closed', 'Completed')
    AND DATE(wo.planned_start_date) = %(planned_date)s
    AND (it.item_group IS NULL OR it.item_group <> 'Recipe')
ORDER BY
    wo.name, wi.idx
"""


def get_material_shortages(planned_date=None):
    """Return Work Orders planned for the given date with insufficient material.

    Each row is one short item for one Work Order:
    work_order, custom_link_id, production_item, planned_start_date, status,
    item_code, item_name, item_group, source_warehouse, required_qty,
    actual_qty, shortage.
    """
    rows = frappe.db.sql(
        SHORTAGE_SQL,
        {"planned_date": planned_date or today()},
        as_dict=True,
    )
    for row in rows:
        row["shortage"] = flt(row["required_qty"]) - flt(row["actual_qty"])
    return rows


def build_shortage_message(rows):
    """Format shortage rows into a readable message grouped by Work Order."""
    now = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M")

    wo_map = {}
    for row in rows:
        wo_map.setdefault(row["work_order"], []).append(row)

    message = "⚠️ *Material Shortage Warning*\n"
    message += f"📅 {now}\n"
    message += "--------------------------\n\n"
    message += f"🔎 {len(wo_map)} Work Order(s) with insufficient material:\n\n"

    for wo_name in wo_map:
        first = wo_map[wo_name][0]
        message += f"*{wo_name}* | {first.get('production_item') or ''}"
        if first.get("custom_link_id"):
            message += f" | 🔗 {first['custom_link_id']}"
        message += "\n"
        for row in wo_map[wo_name]:
            message += f"  📦 {row.get('item_code') or ''}"
            if row.get("item_name"):
                message += f" ({row['item_name']})"
            message += f" — {row.get('item_group') or ''}\n"
            message += f"  🏭 {row.get('source_warehouse') or ''}\n"
            message += (
                f"  🆚 Required: {flt(row['required_qty'])} | "
                f"Available: {flt(row['actual_qty'])} | "
                f"Short: {flt(row['shortage'])}\n"
            )
        if first.get("planned_start_date"):
            message += f"  🗓️ Planned: {first['planned_start_date']}\n"
        message += "\n"

    return message


def _is_enabled():
    try:
        st = frappe.get_single("Caf Settings")
        val = st.get("shortage_enabled")
        return bool(val if val is not None else 1)
    except Exception:
        return True


def send_shortage_warning():
    """Scheduled entry point: warn via WhatsApp + Telegram when shortages exist.

    Sends nothing when all active Work Orders have enough material, or when the
    report is disabled in Caf Settings.
    """
    if not _is_enabled():
        return

    rows = get_material_shortages()
    if not rows:
        return

    message = build_shortage_message(rows)
    _send_report_message("shortage", message)


@frappe.whitelist()
def manual_shortage_warning():
    """Manually trigger the shortage warning (for testing from the UI)."""
    rows = get_material_shortages()
    if not rows:
        return {"success": True, "message": "No material shortages found.", "count": 0}

    message = build_shortage_message(rows)
    _send_report_message("shortage", message)
    return {"success": True, "count": len(rows), "message": f"Warning sent for {len(rows)} short item(s)."}
