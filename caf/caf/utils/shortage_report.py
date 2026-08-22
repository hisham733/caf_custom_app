"""
Material shortage warning report.

Scheduled every 1 hours. Sends a WhatsApp + Telegram message only when an
active Work Order planned for today has a raw material shortage in its source
warehouse.

The query mirrors the "not enough material" Metabase report, with these
differences:
  - only Work Orders whose planned_start_date is today
  - items with no stock record (no bin row) are treated as a shortage
    (actual_qty = 0) instead of being silently skipped
  - a short item is ignored when the same item is itself produced by another
    Work Order under the same link id (in-house pre-step like a TIM/WIP
    that runs before the recipe consumes it), so in-flight stock is not
    reported as missing
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


def _get_items_with_producer_wo(rows):
    """Return set of (custom_link_id, item_code) that have a producer Work Order.

    A short item is ignored when the same item is itself produced by another
    Work Order under the same link id (e.g. a TIM/WIP pre-step running before
    the recipe consumes it), so the not-yet-on-hand stock is still in flight.
    """
    pairs = {(r["custom_link_id"], r["item_code"]) for r in rows if r.get("custom_link_id")}
    if not pairs:
        return set()

    link_ids = {p[0] for p in pairs}
    item_codes = {p[1] for p in pairs}
    producers = frappe.db.sql(
        """
        SELECT DISTINCT wo.custom_link_id, wo.production_item
        FROM `tabWork Order` wo
        WHERE wo.custom_link_id IN %(link_ids)s
          AND wo.production_item IN %(item_codes)s
          AND wo.docstatus <> 2
          AND IFNULL(wo.status, '') NOT IN ('Cancelled', 'Closed')
        """,
        {
            "link_ids": list(link_ids),
            "item_codes": list(item_codes),
        },
        as_dict=True,
    )
    return {(p["custom_link_id"], p["production_item"]) for p in producers}


def get_material_shortages(planned_date=None):
    """Return Work Orders planned for the given date with insufficient material.

    Each row is one short item for one Work Order:
    work_order, custom_link_id, production_item, planned_start_date, status,
    item_code, item_name, item_group, source_warehouse, required_qty,
    actual_qty, shortage.

    Short items are skipped when the same item is produced by another Work
    Order under the same link id (in-house pre-step), because that stock is
    still in flight and will be available by the time the consuming WO runs.
    """
    rows = frappe.db.sql(
        SHORTAGE_SQL,
        {"planned_date": planned_date or today()},
        as_dict=True,
    )
    if not rows:
        return []

    covered = _get_items_with_producer_wo(rows)
    result = []
    for row in rows:
        row["shortage"] = flt(row["required_qty"]) - flt(row["actual_qty"])
        if row.get("custom_link_id") and (row["custom_link_id"], row["item_code"]) in covered:
            continue
        result.append(row)
    return result


def build_shortage_message(rows):
    """Format shortage rows into a short, readable message grouped by Work Order."""
    now = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M")

    wo_map = {}
    for row in rows:
        wo_map.setdefault(row["work_order"], []).append(row)

    lines = [f"🔴 Material Insufficient — {now}"]
    lines.append(f"{len(wo_map)} WO(s), {len(rows)} item(s) short")
    lines.append("")

    for wo_name, wo_rows in wo_map.items():
        first = wo_rows[0]
        prod = first.get("production_item") or "-"
        lines.append(f"• 🏭 {prod}" + (f" | {first.get('custom_link_id') or ''}" if first.get("custom_link_id") else ""))
        for row in wo_rows:
            lines.append(
                f"  ⚠️ {row.get('item_code') or '-'}: req {flt(row['required_qty'], 3)}, "
                f"have {flt(row['actual_qty'], 3)}, short {flt(row['shortage'], 3)}"
            )
        lines.append("")

    return "\n".join(lines)


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
