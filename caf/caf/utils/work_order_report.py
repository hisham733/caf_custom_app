"""
Daily Work Order report.

Summarizes Work Orders by type (WIP / Pack / Cook) and status
(Completed vs Not Finished), anchored on the Cook/Pack Work Orders whose
PLAN START DATE falls on the report date (default: yesterday).

A batch's TIM WIP Work Order is planned days_no days earlier than its Cook
(or pulled back to today if that earlier day is a holiday/in the past -
see production_plan.change_wo_plane_start_date), so it cannot be matched by
date. Instead the whole batch is gathered by custom_link_id. Work Orders
without a custom_link_id are ignored.

Configurable in Caf Settings (enabled and per-channel recipients).
"""

import frappe
from frappe.utils import add_days, today

from caf.caf.utils.notifications import _send_report_message


def _get_settings():
    try:
        return frappe.get_single("Caf Settings")
    except Exception:
        return None


def _is_enabled():
    st = _get_settings()
    if st is None:
        return True
    return bool(st.get("wo_enabled") if st.get("wo_enabled") is not None else 1)


def get_work_orders(report_date=None):
    """Return the Work Orders to summarize for the given report date.

    Anchor on Cook/Pack Work Orders whose planned_start_date falls on the
    report date, then gather every Work Order in those batches by
    custom_link_id (so a batch's TIM WIP is included regardless of its own
    planned start date). Work Orders without a link_id are ignored, as are
    Cancelled and Closed Work Orders (superseded/inactive variants).
    """
    report_date = report_date or add_days(today(), -1)
    report_start = f"{report_date} 00:00:00"
    report_end = f"{report_date} 23:59:59"

    anchor = frappe.get_all(
        "Work Order",
        filters={
            "custom_item_type": ["in", ["Cook", "Pack"]],
            "planned_start_date": ["between", [report_start, report_end]],
            "status": ["not in", ["Cancelled", "Closed"]],
        },
        fields=["name", "status", "custom_item_type", "custom_link_id"],
    )

    # Ignore any anchor row without a link_id.
    anchor = [w for w in anchor if w.get("custom_link_id")]

    if not anchor:
        return []

    # Gather every active Work Order in the batches by link_id (includes each
    # batch's TIM WIP regardless of its own planned start date).
    link_ids = list({w["custom_link_id"] for w in anchor})
    work_orders = frappe.get_all(
        "Work Order",
        filters={
            "custom_link_id": ["in", link_ids],
            "status": ["not in", ["Cancelled", "Closed"]],
        },
        fields=["name", "status", "custom_item_type", "custom_link_id"],
    )

    # De-duplicate by name (anchor rows may also come back from the link query).
    seen = set()
    unique_orders = []
    for wo in work_orders:
        if wo["name"] not in seen:
            seen.add(wo["name"])
            unique_orders.append(wo)
    return unique_orders


def build_work_order_message(work_orders, report_date):
    """Count Work Orders by type/status and format the message."""
    report_data = {
        "WIP": {"Completed": 0, "Pending": 0},
        "Pack": {"Completed": 0, "Pending": 0},
        "Cook": {"Completed": 0, "Pending": 0},
    }

    for wo in work_orders:
        tipe = wo.get("custom_item_type") or "Other"
        if tipe not in report_data:
            report_data[tipe] = {"Completed": 0, "Pending": 0}
        if wo.get("status") == "Completed":
            report_data[tipe]["Completed"] += 1
        else:
            report_data[tipe]["Pending"] += 1

    message = "📊 *Daily Work Order Report*\n"
    message += f"📅 Date: {report_date}\n"
    message += "--------------------------\n\n"

    for tipe, counts in report_data.items():
        total = counts["Completed"] + counts["Pending"]
        if total > 0:
            message += f"*{tipe} Summary:*\n"
            message += f"✅ Completed: {counts['Completed']}\n"
            message += f"⏳ Not Finished: {counts['Pending']}\n"
            message += f"📈 Total: {total}\n\n"

    return message


def send_work_order_daly_report():
    """Scheduled entry point: send the daily Work Order report.

    Respects the 'enabled' flag in Caf Settings; sends nothing when disabled.
    """
    if not _is_enabled():
        return

    report_date = add_days(today(), -1)
    work_orders = get_work_orders(report_date)
    if not work_orders:
        return

    message = build_work_order_message(work_orders, report_date)
    _send_report_message("wo", message)


@frappe.whitelist()
def manual_work_order_warning():
    """Manually trigger the daily Work Order report (for testing)."""
    report_date = add_days(today(), -1)
    work_orders = get_work_orders(report_date)
    if not work_orders:
        return {"success": True, "message": "No Work Orders found.", "count": 0}

    message = build_work_order_message(work_orders, report_date)
    _send_report_message("wo", message)
    return {"success": True, "count": len(work_orders), "message": "Daily Work Order report sent."}
