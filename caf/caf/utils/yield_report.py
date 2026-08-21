"""
Yield deviation morning report.

Mirrors the Metabase yield calculation:
  Yield% = (Total_Weighted_Pack_Production + Pack_Balance + Total_Weighted_Pack_Rejects)
           / Cook_Total_Material_Input * 100

For each Completed Cook+Pack group (per custom_link_id) from the configured
range, the actual yield is compared against the BOM expected yield
(custom_yield * 100, is_default=1, docstatus=1). A run is flagged when the
actual yield deviates from the BOM yield by more than the threshold, in either
direction (too high OR too low):
  abs(actual_yield - bom_yield) > yield_limit   (default limit = 3)

Configurable in Caf Settings: enabled, send time, look-back range, threshold,
and per-channel recipients.
"""

import frappe
from frappe.utils import add_days, flt, today

from caf.caf.utils.notifications import _send_report_message


def _get_settings():
    try:
        st = frappe.get_single("Caf Settings")
    except Exception:
        st = None
    return st


def _is_enabled():
    st = _get_settings()
    if st is None:
        return True
    return bool(st.get("yield_enabled") if st.get("yield_enabled") is not None else 1)


def get_yield_limit():
    st = _get_settings()
    limit = (st.get("yield_limit") if st else None) or 3
    return flt(limit)


def get_lookback_days():
    st = _get_settings()
    days = (st.get("yield_lookback_days") if st else None) or 1
    return int(days)


def _run_yield_sql(start_date, end_date):
    """Compute per-link_id yield for the given date range (Completed Cook+Pack groups)."""
    return frappe.db.sql(
        """
        SELECT
            agg.custom_link_id,
            agg.Cook_Work_Order,
            agg.Cook_Production_Item,
            agg.Cook_Total_Material_Input,
            agg.Recook_Counter,
            agg.Pack_Balance,
            agg.Total_Weighted_Pack_Production,
            agg.Total_Weighted_Pack_Rejects,
            agg.Packed_Items_List,
            agg.Packed_Items_Count,
            agg.plan_date,
            agg.Yield_Percentage,
            ROUND(bom_ref.custom_yield * 100, 2) AS Yield_In_BOM,
            wo_ref.custom_batch_size AS Batch_Size,
            wo_ref.custom_round AS Round,
            wo_ref.planned_start_date AS Plan_Start,
            woo.workstation AS WS_Cook
        FROM (
            SELECT
                ad.custom_link_id,
                ad.Cook_Work_Order,
                ad.Cook_Production_Item,
                ad.Cook_Total_Material_Input,
                ad.Recook_Counter,
                ad.Pack_Balance,
                ad.Total_Weighted_Pack_Production,
                ad.Total_Weighted_Pack_Rejects,
                ad.Packed_Items_List,
                ad.Packed_Items_Count,
                ad.plan_date,
                ROUND(
                    (
                        COALESCE(ad.Total_Weighted_Pack_Production, 0)
                        + COALESCE(ad.Total_Weighted_Pack_Rejects, 0)
                        + COALESCE(ad.Pack_Balance, 0)
                    ) / NULLIF(ad.Cook_Total_Material_Input, 0) * 100,
                    2
                ) AS Yield_Percentage
            FROM (
                SELECT
                    two.custom_link_id,
                    MAX(CASE WHEN two.custom_item_type = 'Cook' AND two.status = 'Completed'
                        THEN two.name END) AS Cook_Work_Order,
                    MAX(CASE WHEN two.custom_item_type = 'Cook' AND two.status = 'Completed'
                        THEN two.production_item END) AS Cook_Production_Item,
                    MAX(CASE WHEN two.custom_item_type = 'Cook' AND two.status = 'Completed'
                        THEN mnf_sum.sum END) AS Cook_Total_Material_Input,
                    MAX(CASE WHEN two.custom_item_type = 'Cook' AND two.status = 'Completed'
                        THEN mnf_sum.recook_weight ELSE 0 END) AS Recook_Counter,
                    SUM(CASE WHEN two.custom_item_type = 'Pack' AND two.status = 'Completed'
                        THEN COALESCE(bfp.total_scrap_qty, 0) ELSE 0 END) AS Pack_Balance,
                    SUM(CASE WHEN two.custom_item_type = 'Pack' AND two.status = 'Completed'
                        THEN COALESCE(two.produced_qty, 0)
                           * CASE WHEN ti.item_group = 'WIP FLOSS' THEN 1
                                  ELSE COALESCE(CAST(tiva.attribute_value AS DECIMAL(10,4)), 0)
                             END
                        ELSE 0 END) AS Total_Weighted_Pack_Production,
                    SUM(CASE WHEN two.custom_item_type = 'Pack' AND two.status = 'Completed'
                        THEN COALESCE(pr.sum, 0)
                           * COALESCE(CAST(tiva.attribute_value AS DECIMAL(10,4)), 0)
                        ELSE 0 END) AS Total_Weighted_Pack_Rejects,
                    GROUP_CONCAT(DISTINCT CASE WHEN two.custom_item_type = 'Pack' AND two.status = 'Completed'
                        THEN two.production_item END SEPARATOR ', ') AS Packed_Items_List,
                    COUNT(DISTINCT CASE WHEN two.custom_item_type = 'Pack' AND two.status = 'Completed'
                        THEN two.production_item END) AS Packed_Items_Count,
                    MAX(two.planned_start_date) AS plan_date
                FROM `tabWork Order` two
                LEFT JOIN `tabItem` ti ON two.production_item = ti.name
                LEFT JOIN `tabItem Variant Attribute` tiva
                    ON two.production_item = tiva.parent AND tiva.attribute = 'Weight'
                LEFT JOIN (
                    SELECT se.work_order,
                        SUM(CASE WHEN sed.uom IN ('Gram') THEN sed.transfer_qty / 1000
                                 WHEN sed.uom IN ('Kg') THEN sed.transfer_qty ELSE 0 END) AS sum,
                        SUM(CASE WHEN sed.item_code = inner_wo.production_item THEN
                            (CASE WHEN sed.uom IN ('Gram') THEN sed.transfer_qty / 1000
                                  WHEN sed.uom IN ('Kg') THEN sed.transfer_qty ELSE 0 END)
                            ELSE 0 END) AS recook_weight
                    FROM `tabStock Entry` se
                    LEFT JOIN `tabStock Entry Detail` sed ON se.name = sed.parent
                    LEFT JOIN `tabWork Order` inner_wo ON se.work_order = inner_wo.name
                    WHERE se.stock_entry_type = 'Manufacture'
                        AND se.docstatus = 1
                        AND sed.uom IN ('Kg', 'Gram')
                        AND sed.s_warehouse IS NOT NULL
                    GROUP BY se.work_order
                ) mnf_sum ON two.name = mnf_sum.work_order
                LEFT JOIN (
                    SELECT se.custom_link_id,
                        finished_detail.item_code AS finished_good_item_code,
                        SUM(scrap_detail.transfer_qty) AS total_scrap_qty
                    FROM `tabStock Entry` se
                    JOIN `tabStock Entry Detail` scrap_detail ON se.name = scrap_detail.parent
                    JOIN `tabStock Entry Detail` finished_detail ON se.name = finished_detail.parent
                    WHERE se.stock_entry_type = 'Manufacture'
                        AND se.docstatus = 1
                        AND scrap_detail.is_scrap_item = 1
                        AND scrap_detail.t_warehouse = 'Prod Balance - CAF'
                        AND finished_detail.is_finished_item = 1
                    GROUP BY se.custom_link_id, finished_detail.item_code
                ) bfp ON two.custom_link_id = bfp.custom_link_id
                    AND two.production_item = bfp.finished_good_item_code
                LEFT JOIN (
                    SELECT se.custom_link_id, sed.item_code, SUM(sed.transfer_qty) AS sum
                    FROM `tabStock Entry` se
                    LEFT JOIN `tabStock Entry Detail` sed ON se.name = sed.parent
                    WHERE se.docstatus = 1 AND sed.t_warehouse = 'Prod Reject - CAF'
                    GROUP BY se.custom_link_id, sed.item_code
                ) pr ON two.custom_link_id = pr.custom_link_id
                    AND two.production_item = pr.item_code
                WHERE two.status <> 'Cancelled'
                    AND two.custom_item_type IN ('Pack', 'Cook')
                GROUP BY two.custom_link_id
                HAVING
                    SUM(CASE WHEN two.custom_item_type = 'Cook' AND two.status = 'Completed'
                        THEN 1 ELSE 0 END) > 0
                    AND SUM(CASE WHEN two.custom_item_type = 'Pack' THEN 1 ELSE 0 END) > 0
                    AND SUM(CASE WHEN two.custom_item_type = 'Pack' THEN 1 ELSE 0 END)
                        = SUM(CASE WHEN two.custom_item_type = 'Pack' AND two.status = 'Completed'
                            THEN 1 ELSE 0 END)
            ) ad
        ) agg
        LEFT JOIN `tabWork Order` wo_ref
            ON agg.custom_link_id = wo_ref.custom_link_id
            AND wo_ref.custom_item_type = 'Cook'
            AND wo_ref.status = 'Completed'
        LEFT JOIN (
            SELECT parent, workstation FROM `tabWork Order Operation` WHERE idx = 1 AND docstatus = 1
        ) woo ON woo.parent = wo_ref.name
        LEFT JOIN `tabBOM` bom_ref
            ON wo_ref.production_item = bom_ref.item
            AND bom_ref.is_default = 1
            AND bom_ref.docstatus = 1
        WHERE DATE(wo_ref.planned_start_date) BETWEEN %(start_date)s AND %(end_date)s
        ORDER BY DATE(wo_ref.planned_start_date) DESC, woo.workstation ASC, wo_ref.custom_round ASC
        """,
        {"start_date": start_date, "end_date": end_date},
        as_dict=True,
    )


def get_yield_drops(start_date=None, end_date=None, limit=None, lookback_days=None):
    """Return completed Cook+Pack groups whose yield deviates from the BOM yield.

    Examines the date range [start_date, end_date]. When no dates are given,
    the morning check looks at the last completed days ending yesterday:
    end_date = yesterday, and start_date = end_date - (lookback_days - 1).
    lookback_days defaults from Caf Settings (default 1 = yesterday only).

    limit is the threshold in percentage points (default from Caf Settings,
    else 3). A run is flagged when abs(actual - bom) > limit — i.e. the actual
    yield is more than the threshold ABOVE or BELOW the BOM expected yield.
    """
    lookback_days = lookback_days if lookback_days is not None else get_lookback_days()

    if end_date is None:
        # Morning check: today has no completed work yet, so examine the last
        # completed days. Default end = yesterday, start = yesterday - (lookback-1).
        end_date = add_days(today(), -1)
        start_date = add_days(end_date, -(lookback_days - 1)) if lookback_days > 1 else end_date
    else:
        if start_date is None:
            start_date = add_days(end_date, -(lookback_days - 1)) if lookback_days > 1 else end_date

    limit = limit if limit is not None else get_yield_limit()

    rows = _run_yield_sql(start_date, end_date)
    drops = []
    for r in rows:
        actual = flt(r.get("Yield_Percentage"))
        bom = flt(r.get("Yield_In_BOM"))
        # Flag when the yield deviates from the BOM expected yield by more than
        # the threshold, in either direction (too low OR too high).
        if bom and abs(actual - bom) > limit:
            r["Yield_Deviation_%"] = round(actual - bom)
            r["Yield_Percentage"] = round(actual)
            r["Yield_In_BOM"] = round(bom)
            drops.append(r)
    return drops


def build_yield_message(rows, limit):
    """Format the flagged yield-deviation rows into a readable message."""
    now = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M")

    message = "📊 *Yield Deviation*\n"
    message += f"📅 {now}\n"
    message += f"🔻 Threshold: more than {limit} points from BOM yield (either direction)\n"
    message += "--------------------------\n\n"
    message += f"🔎 {len(rows)} Cooking run(s) outside the expected yield range:\n\n"

    for r in rows:
        message += f"*{r.get('Cook_Production_Item') or ''}*"
        if r.get("custom_link_id"):
            message += f" | 🔗 {r['custom_link_id']}"
        message += "\n"
        if r.get("Cook_Work_Order"):
            message += f"  🏭 Cook WO: {r['Cook_Work_Order']}\n"
        if r.get("WS_Cook"):
            message += f"  ⚙️ Workstation: {r['WS_Cook']}\n"
        if r.get("Round"):
            message += f"  🔢 Round: {r['Round']}\n"
        if r.get("Batch_Size"):
            message += f"  📏 Batch Size: {r['Batch_Size']}\n"
        deviation = flt(r.get("Yield_Deviation_%"))
        direction = "above expected" if deviation > 0 else "below expected"
        message += (
            f"  🎯 Yield: {flt(r.get('Yield_Percentage'))}% "
            f"(BOM: {flt(r.get('Yield_In_BOM'))}%) "
            f"⛔ Deviation: {abs(deviation)}% {direction}\n"
        )
        if r.get("Packed_Items_List"):
            message += f"  📦 Packs: {r['Packed_Items_List']}\n"
        if r.get("Plan_Start"):
            message += f"  🗓️ Planned: {r['Plan_Start']}\n"
        message += "\n"

    return message


def send_yield_warning():
    """Scheduled entry point: warn about yield deviations outside the range."""
    if not _is_enabled():
        return

    limit = get_yield_limit()
    rows = get_yield_drops(limit=limit)
    if not rows:
        return

    message = build_yield_message(rows, limit)
    _send_report_message("yield", message)


@frappe.whitelist()
def manual_yield_warning():
    """Manually trigger the yield deviation warning (for testing)."""
    limit = get_yield_limit()
    rows = get_yield_drops(limit=limit)
    if not rows:
        return {"success": True, "message": "No yield deviations found.", "count": 0}

    message = build_yield_message(rows, limit)
    _send_report_message("yield", message)
    return {"success": True, "count": len(rows), "message": f"Warning sent for {len(rows)} yield deviation(s)."}
