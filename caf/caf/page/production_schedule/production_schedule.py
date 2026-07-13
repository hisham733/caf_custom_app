import datetime
import re

import frappe
from frappe import _
from frappe.utils import getdate, add_days
from frappe.model.naming import make_autoname

NO_COOKING = "No Cooking"
CHILD_DOCTYPE = "Create ProExl Items"

EXCLUDED_WORKSTATIONS = {
    "cooker database",
    "Cooker Exhaust Hood 1",
    "Cooker Exhaust Hood 2",
    "Fryer Exhaust Hood",
    "Fryer Exhaust Hood 2",
    "Kettle Exhaust Hood",
}


def _iso_week_to_monday(year, week_number):
    """Convert ISO year and week number to the Monday date of that week."""
    jan4 = datetime.date(int(year), 1, 4)
    jan4_weekday = jan4.isocalendar()[2]
    week1_monday = jan4 - datetime.timedelta(days=jan4_weekday - 1)
    monday = week1_monday + datetime.timedelta(weeks=int(week_number) - 1)
    return monday


@frappe.whitelist()
def get_workstations():
    """Return all active Cooker/Kettle/Fryer workstations sorted by class then index.

    Mirrors the Workstations CTE in the Metabase query:
      - cooker=1, kettle=2, fryer=3
      - excludes named exhaust hoods and 'cooker database'
      - only active (custom_inactive != 1)
    """
    rows = frappe.get_all(
        "Workstation",
        fields=["name", "workstation_name", "status"],
        filters={"custom_inactive": ["!=", 1]},
        order_by="workstation_name asc",
    )

    result = []
    for r in rows:
        name = r.workstation_name or r.name
        if name in EXCLUDED_WORKSTATIONS:
            continue
        lower = name.lower()
        if "cooker" in lower:
            ws_class = 1
        elif "kettle" in lower:
            ws_class = 2
        elif "fryer" in lower:
            ws_class = 3
        else:
            continue

        nums = re.findall(r"\d+", name)
        ws_index = int(nums[-1]) if nums else 0

        result.append({
            "name": name,
            "workstation_name": name,
            "ws_class": ws_class,
            "ws_index": ws_index,
            "status": r.status or "",
        })

    result.sort(key=lambda x: (x["ws_class"], x["ws_index"], x["name"]))
    return result


def _build_round_data(row, recipe_name):
    """Build a round dict from a child table row, including pack details."""
    pack_items = []
    pack_count = int(row.get("number_of_pack") or 0)
    for i in range(1, 8):
        suffix = "" if i == 1 else "_{}".format(i)
        pn = row.get("pack_name" + suffix) or ""
        pq = row.get("pack_qty" + suffix) or 0
        pr = row.get("pack_remark" + suffix) or ""
        if pn or pq or pr:
            pack_items.append({
                "name": pn,
                "qty": float(pq) if pq else 0,
                "remark": pr,
            })
    return {
        "id": row.name,
        "recipe": recipe_name,
        "size": row.size or 0,
        "status": row.produ_status or "",
        "production_type": row.production_type or "",
        "pack_count": pack_count,
        "cook_time": str(row.recipe_cook_time) if row.recipe_cook_time else "",
        "cook_station": row.recipe_cook_workstaion or "",
        "cook_round": str(row.recipe_cook_round or 1),
        "yield": row.custom_yield or 0,
        "link_id": row.link_id or "",
        "required_date": str(row.required_date) if row.required_date else "",
        "urgent": bool(row.get("urgent_check")),
        "pack_items": pack_items,
        "recipe_note": row.get("recipe_note") or "",
        "production_plane": row.get("production_plane") or "",
        "mr_reference": row.get("mr_reference") or "",
        "pair_id": row.get("custom_pair_id") or "",
        "wo_status": row.get("custom_wo_status") or "",
    }


@frappe.whitelist()
def get_week_data(year, week_number, mode):
    """Load the weekly schedule for the targeted workstations.

    Per-day latest DP logic:
      - "View Schedule" → latest submitted DP (docstatus=1)
      - "Edit Schedule" → latest draft DP     (docstatus=0)

    Returns a pivoted structure: {workstations, days, day_labels, dp_names, schedule}
    where schedule[ws_name][day_str] = {date_label, has_dp, dp_name, rounds: {1,2,3}, note, pack}
    """
    monday = _iso_week_to_monday(year, week_number)
    start = monday
    end_date = monday + datetime.timedelta(days=5)

    days = []
    current = start
    while current <= end_date:
        days.append(str(current))
        current += datetime.timedelta(days=1)

    target_docstatus = 1 if mode == "View Schedule" else 0

    dp_names = {}
    day_has_dp = {}
    dp_submit_refs = {}

    for day in days:
        dp_info = frappe.db.get_value(
            "Daily Production",
            {"required_by": getdate(day), "docstatus": target_docstatus},
            ["name", "docstatus", "custom_submit_ref"],
            order_by="name desc",
            as_dict=True,
        )
        dp_names[day] = dp_info.name if dp_info else None
        day_has_dp[day] = dp_info is not None
        dp_submit_refs[day] = dp_info.custom_submit_ref if dp_info else None

    day_labels = []
    for day in days:
        date_obj = getdate(day)
        day_labels.append(f"{date_obj.strftime('%a')} {date_obj.day}")

    # Get workstations in the same order as the Metabase view
    workstations = get_workstations()

    # Build normalized lookup: lowercased+despaced → original name
    def _norm(s):
        return s.lower().replace(" ", "") if s else ""

    ws_lookup = {_norm(ws["name"]): ws["name"] for ws in workstations}

    # Build schedule: {ws_name: {day: {rounds, note, pack}}}
    schedule = {}
    for ws in workstations:
        schedule[ws["name"]] = {}
        for day in days:
            schedule[ws["name"]][day] = {
                "date_label": getdate(day).strftime("%d %b"),
                "has_dp": day_has_dp[day],
                "dp_name": dp_names.get(day),
                "rounds": {"1": None, "2": None, "3": None},
                "note": "",
                "pack": "",
            }

    # Fill rows from DB
    for day in days:
        dp_name = dp_names.get(day)
        if not dp_name:
            continue

        rows = frappe.get_all(
            CHILD_DOCTYPE,
            filters={"parent": dp_name},
            fields=[
                "name", "recipe_name", "size", "recipe_cook_workstaion",
                "recipe_cook_round", "required_date", "produ_status",
                "number_of_pack", "recipe_note", "production_type",
                "recipe_cook_time", "custom_yield", "link_id", "custom_pair_id",
                "mr_reference", "production_plane", "urgent_check",
                "pack_remark", "pack_remark_2", "pack_remark_3",
                "pack_remark_4", "pack_remark_5", "pack_remark_6", "pack_remark_7",
                "pack_name", "pack_name_2", "pack_name_3",
                "pack_name_4", "pack_name_5", "pack_name_6", "pack_name_7",
                "pack_qty", "pack_qty_2", "pack_qty_3",
                "pack_qty_4", "pack_qty_5", "pack_qty_6", "pack_qty_7",
            ],
            order_by="idx asc",
        )

        day_notes = {}
        day_packs = {}

        for row in rows:
            raw_ws = row.get("recipe_cook_workstaion") or ""
            ws_name = ws_lookup.get(_norm(raw_ws))
            recipe_name = row.get("recipe_name") or ""
            round_num = str(row.get("recipe_cook_round") or 1)

            if ws_name is None:
                continue

            # Collect notes and packs per workstation
            if ws_name not in day_notes:
                day_notes[ws_name] = []
                day_packs[ws_name] = []
            if row.get("recipe_note"):
                day_notes[ws_name].append(row["recipe_note"])
            for field in ["pack_remark", "pack_remark_2", "pack_remark_3",
                          "pack_remark_4", "pack_remark_5", "pack_remark_6", "pack_remark_7"]:
                val = row.get(field)
                if val:
                    day_packs[ws_name].append(val)

            # Only fill rounds 1, 2, 3
            if round_num in ("1", "2", "3") and schedule[ws_name][day]["rounds"][round_num] is None:
                schedule[ws_name][day]["rounds"][round_num] = _build_round_data(row, recipe_name)

            # Fill remaining rounds in order (if round 4+)
            if round_num not in ("1", "2", "3"):
                for rn in ("1", "2", "3"):
                    if schedule[ws_name][day]["rounds"][rn] is None:
                        schedule[ws_name][day]["rounds"][rn] = _build_round_data(row, recipe_name)
                        break

        # Apply combined notes/packs
        for ws_name in day_notes:
            if ws_name in schedule:
                schedule[ws_name][day]["note"] = " / ".join(
                    d for d in day_notes[ws_name] if d) if day_notes[ws_name] else ""
                schedule[ws_name][day]["pack"] = " / ".join(
                    d for d in day_packs[ws_name] if d) if day_packs[ws_name] else ""

    return {
        "workstations": workstations,
        "days": days,
        "day_labels": day_labels,
        "dp_names": dp_names,
        "dp_submit_refs": dp_submit_refs,
        "schedule": schedule,
    }


@frappe.whitelist()
def save_move_item(item_id, source_date, target_date, target_cooker, target_round=None):
    """Move a child row between cookers, rounds, or DPs.

    Workstation, round, and link_id are static to the slot — the recipe
    inherits the target slot's values, and the No Cooking placeholder
    inherits the source slot's values. Both slots are marked "Change Slot".

    Args:
        item_id: Child table row name
        source_date: Source DP's required_by date
        target_date: Target DP's required_by date
        target_cooker: Target workstation name (empty string for unassigned)
        target_round: Target round number (1-9), optional

    Returns:
        Dict with success status
    """
    source_dp_name = frappe.db.get_value(
        "Daily Production",
        {"required_by": source_date, "docstatus": 0},
        "name",
    )
    if not source_dp_name:
        return {"success": False, "message": f"No draft DP for {source_date}"}

    source_dp = frappe.get_doc("Daily Production", source_dp_name)

    source_row = None
    for row in source_dp.production_table:
        if row.name == item_id:
            source_row = row
            break
    if source_row is None:
        return {"success": False, "message": "Source row not found"}

    # Same day: swap positions with the No Cooking row at target slot
    if source_date == target_date:
        old_ws = source_row.recipe_cook_workstaion
        old_round = source_row.recipe_cook_round
        old_link_id = source_row.link_id

        target_nc = None
        for r in source_dp.production_table:
            if (str(r.recipe_cook_workstaion or "") == str(target_cooker) and
                str(r.recipe_cook_round or "") == str(target_round) and
                r.recipe_name == NO_COOKING and
                r.name != source_row.name):
                target_nc = r
                break

        # Recipe row inherits target slot's static values
        source_row.recipe_cook_workstaion = target_cooker
        source_row.recipe_cook_round = int(target_round)

        pair_id = None
        swap_executed = False

        if target_nc:
            # No Cooking row inherits source slot's static values
            target_nc.recipe_cook_workstaion = old_ws
            target_nc.recipe_cook_round = old_round

            # Assign new link_id if this slot has never been used
            if not target_nc.link_id:
                target_nc.link_id = make_autoname("R-.YYYY.-.#####")

            # Swap link_ids (static to slot, not recipe)
            target_link_id = target_nc.link_id
            target_nc.link_id = old_link_id
            source_row.link_id = target_link_id

            # Mark both as Change Slot with shared pair_id
            from frappe.utils import now_datetime
            pair_id = now_datetime().strftime("%Y%m%d%H%M%S%f")
            source_row.produ_status = "Change Slot"
            target_nc.produ_status = "Change Slot"
            source_row.custom_pair_id = pair_id
            target_nc.custom_pair_id = pair_id
            swap_executed = True

            # Capture quality data BEFORE WO migration
            from caf.caf.doctype.daily_production.rearrange_and_change_slot import (
                _get_quality_data_by_id,
            )
            quality_data = _get_quality_data_by_id(old_link_id)

            # Migrate WOs from old link_id to new
            from caf.caf.doctype.daily_production.rearrange_and_change_slot import (
                _migrate_db_link_ids,
            )
            _migrate_db_link_ids(source_id=old_link_id, target_id=source_row.link_id)

            if source_dp.custom_submit_ref:
                source_row.custom_wo_status = "Processing"
                target_nc.custom_wo_status = "Processing"
        else:
            new_nc = source_dp.append("production_table", {})
            new_nc.recipe_name = NO_COOKING
            new_nc.recipe_cook_workstaion = old_ws
            new_nc.recipe_cook_round = old_round
            new_nc.required_date = source_date

        for i, r in enumerate(source_dp.production_table):
            r.idx = i + 1

        source_dp.save(ignore_permissions=True)
        frappe.db.commit()

        if swap_executed and source_dp.custom_submit_ref:
            frappe.enqueue(
                "caf.caf.page.production_schedule.production_schedule._background_move_wo_migration",
                queue="long",
                timeout=600,
                source_row_name=source_row.name,
                quality_data=quality_data,
            )

        return {
            "success": True,
            "message": "Moved",
        }

    # ── Cross-day move ──────────────────────────────────────────
    target_dp_name = frappe.db.get_value(
        "Daily Production",
        {"required_by": target_date, "docstatus": 0},
        "name",
    )
    if not target_dp_name:
        return {"success": False, "message": f"No draft DP for {target_date}"}

    # Block if either DP already has Work Orders
    if source_dp.custom_submit_ref or frappe.db.get_value(
        "Daily Production", target_dp_name, "custom_submit_ref"
    ):
        return {"success": False, "message": "Both days must have no Work Orders to move across days"}

    target_dp = frappe.get_doc("Daily Production", target_dp_name)

    # Find No Cooking row at target slot
    target_nc = None
    for r in target_dp.production_table:
        if (str(r.recipe_cook_workstaion or "") == str(target_cooker) and
            str(r.recipe_cook_round or "") == str(target_round) and
            r.recipe_name == NO_COOKING):
            target_nc = r
            break

    if not target_nc:
        return {"success": False, "message": "Target slot not found"}

    # Save source recipe data before clearing
    old_recipe = source_row.recipe_name
    old_size = source_row.size
    old_pack_count = source_row.number_of_pack
    old_prod_type = source_row.production_type
    old_urgent = source_row.urgent_check
    old_note = source_row.recipe_note
    old_prod_plane = source_row.production_plane
    old_wo_list_type = source_row.wo_list_with_type
    old_packs = {}
    for i in range(1, 8):
        suffix = "" if i == 1 else f"_{i}"
        old_packs[i] = {
            "name": source_row.get(f"pack_name{suffix}"),
            "qty": source_row.get(f"pack_qty{suffix}"),
            "remark": source_row.get(f"pack_remark{suffix}"),
        }

    # Source row → No Cooking (keeps its link_id and slot position)
    source_row.recipe_name = NO_COOKING
    source_row.size = 0
    source_row.produ_status = ""
    source_row.number_of_pack = 0
    source_row.production_type = ""
    source_row.urgent_check = 0
    source_row.recipe_note = ""
    source_row.production_plane = ""
    source_row.mr_reference = None
    source_row.wo_list = None
    source_row.wo_list_with_type = None
    source_row.custom_pair_id = ""
    for i in range(1, 8):
        suffix = "" if i == 1 else f"_{i}"
        source_row.set(f"pack_name{suffix}", None)
        source_row.set(f"pack_qty{suffix}", 0)
        source_row.set(f"pack_remark{suffix}", None)

    # Target NC row → gets the recipe (keeps its own link_id and slot position)
    target_nc.recipe_name = old_recipe
    target_nc.size = old_size
    target_nc.number_of_pack = old_pack_count
    target_nc.production_type = old_prod_type
    target_nc.urgent_check = old_urgent
    target_nc.recipe_note = old_note
    target_nc.production_plane = old_prod_plane
    target_nc.wo_list_with_type = old_wo_list_type
    target_nc.required_date = target_date
    target_nc.recipe_cook_workstaion = target_cooker
    target_nc.recipe_cook_round = int(target_round)
    target_nc.produ_status = "Change Slot"
    for i in range(1, 8):
        suffix = "" if i == 1 else f"_{i}"
        target_nc.set(f"pack_name{suffix}", old_packs[i]["name"])
        target_nc.set(f"pack_qty{suffix}", old_packs[i]["qty"])
        target_nc.set(f"pack_remark{suffix}", old_packs[i]["remark"])

    # Reindex both DPs
    for i, r in enumerate(source_dp.production_table):
        r.idx = i + 1
    for i, r in enumerate(target_dp.production_table):
        r.idx = i + 1

    source_dp.save(ignore_permissions=True)
    target_dp.save(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "message": "Moved"}


@frappe.whitelist()
def save_update_item(item_id, field, value):
    """Update a single field on a child row of a draft DP.

    Args:
        item_id: Child table row name
        field: Fieldname to update
        value: New value

    Returns:
        Dict with success status
    """
    dp_name = frappe.db.get_value(CHILD_DOCTYPE, {"name": item_id}, "parent")
    if not dp_name:
        return {"success": False, "message": "Item not found"}

    dp = frappe.get_doc("Daily Production", dp_name)
    if dp.docstatus != 0:
        return {"success": False, "message": "DP is not in draft state"}

    for row in dp.production_table:
        if row.name == item_id:
            if field == "produ_status" and value == "New Schedule":
                row.mr_reference = None
                row.wo_list = None
                row.wo_list_with_type = None
            row.set(field, value)
            break
    else:
        return {"success": False, "message": "Row not found in DP"}

    dp.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": "Updated"}


@frappe.whitelist()
def save_item_fields(item_id, fields):
    """Save multiple fields on a child row in a single transaction."""
    import json
    if isinstance(fields, str):
        fields = json.loads(fields)

    dp_name = frappe.db.get_value(CHILD_DOCTYPE, {"name": item_id}, "parent")
    if not dp_name:
        return {"success": False, "message": "Item not found"}

    dp = frappe.get_doc("Daily Production", dp_name)
    if dp.docstatus != 0:
        return {"success": False, "message": "DP is not in draft state"}

    for row in dp.production_table:
        if row.name == item_id:
            for f in fields:
                field = f.get("field")
                value = f.get("value")
                if field == "produ_status" and value == "New Schedule":
                    row.mr_reference = None
                    row.wo_list = None
                    row.wo_list_with_type = None
                row.set(field, value)
            break
    else:
        return {"success": False, "message": "Row not found in DP"}

    dp.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": "Updated"}


@frappe.whitelist()
def process_day_dp(week_monday, day_index):
    """Synchronously run process_manual_updates for one day's DP.

    Called from the page's Create WO button in View mode. Runs all
    change types (Change Slot, Rearrange, Recipe Change, New Schedule,
    Cancelled) for that day. Freezes the page with loading overlay.

    Args:
        week_monday: Date string of the Monday
        day_index: 0=Mon, 1=Tue, ..., 5=Sat

    Returns:
        Dict with success status
    """
    from datetime import timedelta

    monday = getdate(week_monday)
    day = monday + timedelta(days=int(day_index))

    dp_name = frappe.db.get_value(
        "Daily Production",
        {"required_by": str(day), "docstatus": 1},
        "name",
        order_by="name desc",
    )
    if not dp_name:
        return {"success": False, "message": _("No submitted DP for {0}").format(str(day))}

    dp = frappe.get_doc("Daily Production", dp_name)
    if dp.custom_submit_ref:
        return {"success": False, "message": _("Work Orders already created for {0}").format(str(day))}

    try:
        dp.process_manual_updates()
        return {
            "success": True,
            "message": _("Work Orders created for {0}").format(str(day)),
        }
    except Exception as e:
        frappe.log_error(title="process_day_dp failed", message=frappe.get_traceback())
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def submit_week(week_monday):
    """Submit draft DPs that have status changes for the week Mon-Sat.

    Sets skip_wo_creation flag so on_submit does NOT run process_manual_updates.
    WO creation happens later via the Create WO button in View mode.

    Only submits DPs where at least one child row has a non-empty produ_status.
    Skips past days (before today).
    Returns JSON response.

    Args:
        week_monday: Date string of the Monday
    """
    monday = getdate(week_monday)
    days = [monday + datetime.timedelta(days=i) for i in range(6)]
    today = datetime.date.today()

    submitted = 0
    skipped_past = 0
    skipped_no_status = 0
    skipped_no_dp = 0

    try:
        frappe.flags.skip_wo_creation = True

        for day in days:
            if day < today:
                skipped_past += 1
                continue

            dp_name = frappe.db.get_value(
                "Daily Production",
                {"required_by": day, "docstatus": 0},
                "name",
                order_by="name desc",
            )
            if not dp_name:
                skipped_no_dp += 1
                continue

            dp = frappe.get_doc("Daily Production", dp_name)
            has_status = any(row.produ_status for row in dp.production_table)
            if not has_status:
                skipped_no_status += 1
                continue

            try:
                dp.submit()
                submitted += 1
            finally:
                frappe.flags.pop('from_schedule_page', None)
    finally:
        frappe.flags.pop('skip_wo_creation', None)

    if submitted == 0:
        return {
            "success": False,
            "message": _("No recipes have status changes to submit."),
        }

    return {
        "success": True,
        "message": _("Submitted {0} DP(s). Skipped {1} past, {2} with no status.").format(submitted, skipped_past, skipped_no_status),
    }


@frappe.whitelist()
def add_recipe(day, recipe, size, cooker, pack_count, round_num, **kwargs):
    """Add a new recipe row to the draft DP for the given day.

    Args:
        day: Target date string
        recipe: Item name (recipe)
        size: Batch size
        cooker: Workstation name
        pack_count: Number of pack variants
        round_num: Cook round

    Returns:
        Dict with success status
    """
    dp_name = frappe.db.get_value(
        "Daily Production",
        {"required_by": day, "docstatus": 0},
        "name",
    )
    if not dp_name:
        return {"success": False, "message": f"No draft DP for {day}"}

    dp = frappe.get_doc("Daily Production", dp_name)

    cooker_str = str(cooker or "")
    round_str = str(round_num or "1")
    existing_row = None
    for r in dp.production_table:
        if (str(r.recipe_cook_workstaion or "") == cooker_str
                and str(r.recipe_cook_round or "") == round_str
                and r.recipe_name == NO_COOKING):
            existing_row = r
            break

    if existing_row:
        row = existing_row
    else:
        row = dp.append("production_table", {})

    row.required_date = day
    row.recipe_name = recipe
    row.size = size or 0
    row.recipe_cook_workstaion = cooker or None
    row.recipe_cook_round = int(round_num) if round_num else 1
    row.number_of_pack = int(pack_count) if pack_count else 0
    row.produ_status = kwargs.get("produ_status") or ""
    row.production_type = kwargs.get("production_type") or ""
    row.urgent_check = int(kwargs.get("urgent_check", 0)) if kwargs.get("urgent_check") else 0
    row.recipe_note = kwargs.get("recipe_note") or ""
    row.production_plane = kwargs.get("production_plane") or ""
    row.wo_list_with_type = kwargs.get("wo_list_with_type") or ""

    if row.produ_status == "New Schedule" and dp.custom_submit_ref:
        row.custom_wo_status = "Processing"

    for i in range(1, 8):
        suffix = "" if i == 1 else "_{}".format(i)
        for pfield in ("pack_name", "pack_qty", "pack_remark"):
            val = kwargs.get(pfield + suffix)
            if val:
                row.set(pfield + suffix, val)

    for i, r in enumerate(dp.production_table):
        r.idx = i + 1

    dp.save(ignore_permissions=True)
    frappe.db.commit()

    # Create MR + WOs in background only for submitted DPs (already had WO run once)
    # For draft DPs, New Schedule rows are processed by process_day_dp → process_manual_updates
    if row.produ_status == "New Schedule" and dp.custom_submit_ref:
        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_create_mr",
            queue="long",
            timeout=600,
            row_name=row.name,
            dp_name=dp.name,
        )

    return {
        "success": True,
        "message": f"Added {recipe} to {day}",
        "item": {
            "id": row.name,
            "recipe": row.recipe_name,
            "size": row.size,
            "cooker": row.recipe_cook_workstaion or "",
            "day": day,
            "round": row.recipe_cook_round,
            "status": "",
            "pack_count": row.number_of_pack,
            "production_type": row.production_type,
            "urgent_check": row.urgent_check,
            "recipe_note": row.recipe_note or "",
            "production_plane": row.production_plane or "",
        },
    }


@frappe.whitelist()
def create_week_version(week_number):
    """Create new draft DPs for a week from the latest submitted versions.

    Delegates to daily_production.create_empty_dp_week_by_number.
    Removes draft DPs for past days (before today).
    After creation, the new draft DPs appear in Edit Schedule mode.

    Args:
        week_number: ISO week number (e.g. 25)
    """
    from caf.caf.doctype.daily_production.daily_production import create_empty_dp_week_by_number

    create_empty_dp_week_by_number(int(week_number))

    today = datetime.date.today()
    monday = _iso_week_to_monday(datetime.date.today().year, int(week_number))
    for i in range(6):
        day = monday + datetime.timedelta(days=i)
        if day < today:
            dp_name = frappe.db.get_value(
                "Daily Production",
                {"required_by": day, "docstatus": 0},
                "name",
            )
            if dp_name:
                frappe.delete_doc("Daily Production", dp_name, ignore_permissions=True)

    frappe.response["type"] = "json"
    return {"success": True}


@frappe.whitelist()
def swap_recipes(source_id, target_id):
    """Swap recipe data between two child rows, keeping slot identity fields.

    Swaps recipe_name, size, produ_status, pack config, etc. between
    two rows in the same DP.  Preserves link_id, recipe_cook_workstaion,
    and recipe_cook_round in their original slots.

    Args:
        source_id: Child row name of the dragged recipe
        target_id: Child row name of the recipe being replaced

    Returns:
        Dict with success status
    """
    SLOT_FIELDS = {
        "name", "parent", "parentfield", "parenttype", "doctype", "idx",
        "link_id", "recipe_cook_workstaion", "recipe_cook_round", "required_date",
    }

    src_dp = frappe.db.get_value(CHILD_DOCTYPE, {"name": source_id}, "parent")
    tgt_dp = frappe.db.get_value(CHILD_DOCTYPE, {"name": target_id}, "parent")
    if not src_dp or not tgt_dp:
        return {"success": False, "message": "Item not found"}

    if src_dp != tgt_dp:
        # Cross-DP swap: block if either DP has Work Orders
        src_ref = frappe.db.get_value("Daily Production", src_dp, "custom_submit_ref")
        tgt_ref = frappe.db.get_value("Daily Production", tgt_dp, "custom_submit_ref")
        if src_ref or tgt_ref:
            return {"success": False, "message": "Both days must have no Work Orders to swap across days"}

        src_doc = frappe.get_doc("Daily Production", src_dp)
        tgt_doc = frappe.get_doc("Daily Production", tgt_dp)

        if src_doc.docstatus != 0 or tgt_doc.docstatus != 0:
            return {"success": False, "message": "Both DPs must be in draft state"}

        row_a = next((r for r in src_doc.production_table if r.name == source_id), None)
        row_b = next((r for r in tgt_doc.production_table if r.name == target_id), None)
        if not row_a or not row_b:
            return {"success": False, "message": "Row not found"}

        swappable = [
            df.fieldname for df in _get_child_meta_fields()
            if df.fieldname not in SLOT_FIELDS
        ]
        for fn in swappable:
            val_a, val_b = row_a.get(fn), row_b.get(fn)
            row_a.set(fn, val_b)
            row_b.set(fn, val_a)

        src_doc.save(ignore_permissions=True)
        tgt_doc.save(ignore_permissions=True)
        frappe.db.commit()
        return {"success": True, "message": "Recipes swapped"}

    dp = frappe.get_doc("Daily Production", src_dp)
    if dp.docstatus != 0:
        return {"success": False, "message": "DP is not in draft state"}

    row_a = row_b = None
    for row in dp.production_table:
        if row.name == source_id:
            row_a = row
        elif row.name == target_id:
            row_b = row
    if row_a is None or row_b is None:
        return {"success": False, "message": "Row not found"}

    swappable = [
        df.fieldname for df in _get_child_meta_fields()
        if df.fieldname not in SLOT_FIELDS
    ]

    for fn in swappable:
        val_a = row_a.get(fn)
        val_b = row_b.get(fn)
        row_a.set(fn, val_b)
        row_b.set(fn, val_a)

    dp.save(ignore_permissions=True)
    frappe.db.commit()

    has_wos = bool(row_a.mr_reference) or bool(row_b.mr_reference)
    if has_wos and dp.custom_submit_ref:
        row_a.custom_wo_status = "Processing"
        row_b.custom_wo_status = "Processing"
        dp.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_swap_recipes",
            queue="long",
            timeout=600,
            row_a_name=row_a.name,
            row_b_name=row_b.name,
        )
        return {"success": True, "message": "Rearranging — background processing started"}

    return {"success": True, "message": "Recipes swapped"}


@frappe.whitelist()
def undo_pair(pair_id, original_link_id=None, original_source_date=None):
    """Reverse a Change Slot or Rearrange operation by pair_id.

    Args:
        pair_id: The custom_pair_id shared by the two affected rows
        original_link_id: Original link_id for cross-day undo (from frontend)
        original_source_date: Original source date for cross-day undo

    Returns:
        Dict with success status
    """
    rows = frappe.get_all(
        CHILD_DOCTYPE,
        filters={"custom_pair_id": pair_id},
        fields=["name", "parent", "recipe_name", "produ_status",
                "recipe_cook_workstaion", "recipe_cook_round", "link_id"],
    )
    if len(rows) != 2:
        return {"success": False, "message": "Pair not found"}

    status = rows[0].produ_status or rows[1].produ_status
    parents = set(r.parent for r in rows)

    SLOT_FIELDS = {
        "name", "parent", "parentfield", "parenttype", "doctype", "idx",
        "link_id", "recipe_cook_workstaion", "recipe_cook_round", "required_date",
        "custom_pair_id",
    }

    # ── Rearrange: swap all swappable fields back ──
    if status == "Rearrange":
        dp = frappe.get_doc("Daily Production", list(parents)[0])
        row_a = row_b = None
        for r in dp.production_table:
            if r.name == rows[0].name:
                row_a = r
            elif r.name == rows[1].name:
                row_b = r
        if not row_a or not row_b:
            return {"success": False, "message": "Rows not found"}

        swappable = [
            df.fieldname for df in _get_child_meta_fields()
            if df.fieldname not in SLOT_FIELDS
        ]
        for fn in swappable:
            val_a = row_a.get(fn)
            val_b = row_b.get(fn)
            row_a.set(fn, val_b)
            row_b.set(fn, val_a)

        row_a.produ_status = ""
        row_b.produ_status = ""
        row_a.custom_pair_id = ""
        row_b.custom_pair_id = ""

        dp.save(ignore_permissions=True)
        frappe.db.commit()
        return {"success": True, "message": "Swap undone"}

    # ── Change Slot: same-day (swap WS/round back) or cross-day (copy back + delete) ──
    if status == "Change Slot":
        if len(parents) == 1:
            # Same-day: swap WS/round back
            dp = frappe.get_doc("Daily Production", list(parents)[0])
            row_a = row_b = None
            for r in dp.production_table:
                if r.name == rows[0].name:
                    row_a = r
                elif r.name == rows[1].name:
                    row_b = r
            if not row_a or not row_b:
                return {"success": False, "message": "Rows not found"}

            row_a.recipe_cook_workstaion = rows[1].recipe_cook_workstaion
            row_a.recipe_cook_round = rows[1].recipe_cook_round
            row_b.recipe_cook_workstaion = rows[0].recipe_cook_workstaion
            row_b.recipe_cook_round = rows[0].recipe_cook_round
            row_a.produ_status = ""
            row_b.produ_status = ""
            row_a.custom_pair_id = ""
            row_b.custom_pair_id = ""

            dp.save(ignore_permissions=True)
            frappe.db.commit()
            return {"success": True, "message": "Move undone"}
        else:
            # Cross-day: copy target row data back to source, delete target row
            source_data = None
            target_data = None
            for r in rows:
                if r.recipe_name == NO_COOKING:
                    source_data = r
                else:
                    target_data = r
            if not source_data or not target_data:
                return {"success": False, "message": "Could not identify source/target rows"}

            source_dp = frappe.get_doc("Daily Production", source_data.parent)
            target_dp = frappe.get_doc("Daily Production", target_data.parent)

            source_row = None
            target_row = None
            for r in source_dp.production_table:
                if r.name == source_data.name:
                    source_row = r
                    break
            for r in target_dp.production_table:
                if r.name == target_data.name:
                    target_row = r
                    break
            if not source_row or not target_row:
                return {"success": False, "message": "Rows not found in DPs"}

            swappable = [
                df.fieldname for df in _get_child_meta_fields()
                if df.fieldname not in SLOT_FIELDS
            ]
            for fn in swappable:
                val = target_row.get(fn)
                source_row.set(fn, val)

            source_row.link_id = original_link_id
            source_row.produ_status = ""
            source_row.custom_pair_id = ""

            new_table = [r for r in target_dp.production_table if r.name != target_data.name]
            target_dp.production_table = new_table

            for i, r in enumerate(source_dp.production_table):
                r.idx = i + 1
            for i, r in enumerate(target_dp.production_table):
                r.idx = i + 1

            source_dp.save(ignore_permissions=True)
            target_dp.save(ignore_permissions=True)
            frappe.db.commit()
            return {"success": True, "message": "Cross-day move undone"}

    return {"success": False, "message": f"Unknown status: {status}"}


def _get_child_meta_fields():
    """Return all field definitions from the child DocType metadata."""
    return frappe.get_meta(CHILD_DOCTYPE).fields


@frappe.whitelist()
def get_recipe_bom_data(recipe_name):
    """Fetch BOM data for a recipe: custom_yield and custom_raw_materails.

    Args:
        recipe_name: Item name (recipe)

    Returns:
        Dict with yield and raw_materials values
    """
    bom = frappe.db.get_value(
        "BOM",
        {"item": recipe_name, "docstatus": 1, "is_active": 1},
        ["name", "custom_yield", "custom_raw_materails"],
        as_dict=True,
        order_by="modified desc",
    )
    if bom:
        return {
            "yield": bom.custom_yield or 0,
            "raw_materials": bom.custom_raw_materails or 0,
        }
    return {"yield": 0, "raw_materials": 0}


@frappe.whitelist()
def get_row_status(item_id):
    """Lightweight poll: return wo_status and mr_reference for a row."""
    vals = frappe.db.get_value(
        CHILD_DOCTYPE,
        {"name": item_id},
        ["custom_wo_status", "mr_reference"],
        as_dict=True,
    )
    if vals:
        return {"wo_status": vals.custom_wo_status or "", "mr_reference": vals.mr_reference or ""}
    return {"wo_status": "", "mr_reference": ""}


@frappe.whitelist()
def process_recipe_change(item_id):
    """Enqueue background recipe change WO reprocessing for a row."""
    row_data = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": item_id},
        ["parent", "produ_status", "mr_reference", "recipe_name"],
        as_dict=True,
    )
    if not row_data:
        return {"success": False, "message": "Item not found"}
    if row_data.produ_status != "Recipe Change" or not row_data.mr_reference:
        return {"success": False, "message": "No recipe change needed"}

    dp_custom_submit_ref = frappe.db.get_value("Daily Production", row_data.parent, "custom_submit_ref")
    if not dp_custom_submit_ref:
        return {"success": True, "message": _("Saved — will be processed when Work Orders are created")}

    frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_status", "Processing")

    frappe.enqueue(
        "caf.caf.page.production_schedule.production_schedule._background_change_recipe",
        queue="long",
        timeout=600,
        item_id=item_id,
        dp_name=row_data.parent,
        new_recipe=row_data.recipe_name,
    )
    return {"success": True, "message": _("Recipe change queued")}


@frappe.whitelist()
def cancel_item(item_id):
    """Cancel a production item row and queue WO cancellation."""
    dp_name = frappe.db.get_value(CHILD_DOCTYPE, {"name": item_id}, "parent")
    if not dp_name:
        return {"success": False, "message": "Item not found"}

    dp = frappe.get_doc("Daily Production", dp_name)
    if dp.docstatus != 0:
        return {"success": False, "message": "DP is not in draft state"}

    row = next((r for r in dp.production_table if r.name == item_id), None)
    if not row:
        return {"success": False, "message": "Row not found in DP"}

    row.produ_status = "Cancelled"
    if dp.custom_submit_ref:
        row.custom_wo_status = "Processing"
    dp.save(ignore_permissions=True)
    frappe.db.commit()

    if dp.custom_submit_ref:
        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_cancel_item",
            queue="long",
            timeout=600,
            item_id=item_id,
            dp_name=dp_name,
        )
    return {"success": True, "message": _("Item cancelled")}


def _background_change_recipe(item_id, dp_name, new_recipe):
    """Background worker: reprocess WOs after recipe change."""
    try:
        current = frappe.db.get_value(
            CHILD_DOCTYPE, item_id,
            ["produ_status", "mr_reference", "custom_wo_status"], as_dict=True
        )
        if not current or current.produ_status != "Recipe Change" or not current.mr_reference:
            frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_status", "")
            frappe.db.commit()
            return

        from caf.caf.doctype.daily_production.rearrange_and_change_slot import (
            _cancel_cook_pack_by_id,
            _cleanup_redundant_wips,
        )
        from caf.caf.doctype.daily_production.wo_helpers import get_wo_by_type
        from frappe.utils import now_datetime

        dp = frappe.get_doc("Daily Production", dp_name)
        row = next((r for r in dp.production_table if r.name == item_id), None)
        if not row or row.produ_status != "Recipe Change":
            frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_status", "")
            frappe.db.commit()
            return

        _cancel_cook_pack_by_id(row.link_id)
        new_wos = dp.create_material_request_after_change_size(new_recipe, [row])
        _cleanup_redundant_wips(new_wos, row, CHILD_DOCTYPE, now_datetime())
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_status", "Done")
    except Exception:
        frappe.log_error(title="Background recipe change failed", message=frappe.get_traceback())
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_status", "Failed")
        frappe.db.commit()


def _background_cancel_item(item_id, dp_name):
    """Background worker: process cancellation and reset row to free the slot."""
    try:
        current = frappe.db.get_value(
            CHILD_DOCTYPE, item_id,
            ["produ_status", "custom_wo_status"], as_dict=True
        )
        if not current or current.produ_status != "Cancelled":
            frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_status", "")
            frappe.db.commit()
            return

        from caf.caf.doctype.daily_production.cancellation import process_cancellations

        process_cancellations(dp_name, "Daily Production", CHILD_DOCTYPE)

        dp = frappe.get_doc("Daily Production", dp_name)
        row = next((r for r in dp.production_table if r.name == item_id), None)
        if row:
            row.recipe_name = "No Cooking"
            row.size = 0
            row.produ_status = ""
            row.number_of_pack = 0
            row.production_type = ""
            row.urgent_check = 0
            row.recipe_note = ""
            row.mr_reference = None
            row.wo_list = None
            row.wo_list_with_type = None
            row.custom_wo_status = ""
            for i in range(1, 8):
                suffix = "" if i == 1 else f"_{i}"
                row.set(f"pack_name{suffix}", None)
                row.set(f"pack_qty{suffix}", 0)
                row.set(f"pack_remark{suffix}", None)
            dp.save(ignore_permissions=True)
            frappe.db.commit()
        else:
            frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_status", "Done")
    except Exception:
        frappe.log_error(title="Background cancellation failed", message=frappe.get_traceback())
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_status", "Failed")
        frappe.db.commit()


def _background_swap_recipes(row_a_name, row_b_name):
    """Background worker: process WO swap, cancel, recreate for a Rearrange pair."""
    try:
        data_a = frappe.db.get_value(
            CHILD_DOCTYPE, row_a_name,
            ["parent", "custom_wo_status", "mr_reference", "link_id", "recipe_name"],
            as_dict=True,
        )
        data_b = frappe.db.get_value(
            CHILD_DOCTYPE, row_b_name,
            ["parent", "custom_wo_status", "mr_reference", "link_id", "recipe_name"],
            as_dict=True,
        )
        if (not data_a or not data_b or
            data_a.custom_wo_status != "Processing" or data_b.custom_wo_status != "Processing"):
            for name in [row_a_name, row_b_name]:
                cur = frappe.db.get_value(CHILD_DOCTYPE, name, "custom_wo_status")
                if cur == "Processing":
                    frappe.db.set_value(CHILD_DOCTYPE, name, "custom_wo_status", "")
                    frappe.db.commit()
            return

        dp = frappe.get_doc("Daily Production", data_a.parent)
        row_a = next((r for r in dp.production_table if r.name == row_a_name), None)
        row_b = next((r for r in dp.production_table if r.name == row_b_name), None)
        if not row_a or not row_b:
            for name in [row_a_name, row_b_name]:
                frappe.db.set_value(CHILD_DOCTYPE, name, "custom_wo_status", "")
                frappe.db.commit()
            return

        from caf.caf.doctype.daily_production.rearrange_and_change_slot import (
            _cancel_cook_pack_by_id,
            _get_quality_data_by_id,
            _relink_quality_docs,
            _swap_db_link_ids,
            _cleanup_redundant_wips,
        )
        from caf.caf.doctype.daily_production.wo_helpers import get_wo_by_type
        from frappe.utils import now_datetime

        qual_a = _get_quality_data_by_id(row_a.link_id)
        qual_b = _get_quality_data_by_id(row_b.link_id)

        _swap_db_link_ids(row_a.link_id, row_b.link_id)

        _cancel_cook_pack_by_id(row_a.link_id)
        _cancel_cook_pack_by_id(row_b.link_id)

        new_wos_a = dp.create_material_request_after_change_size(row_a.recipe_name, [row_a])
        new_wos_b = dp.create_material_request_after_change_size(row_b.recipe_name, [row_b])

        _cleanup_redundant_wips(new_wos_a, row_a, CHILD_DOCTYPE, now_datetime())
        _cleanup_redundant_wips(new_wos_b, row_b, CHILD_DOCTYPE, now_datetime())

        new_cook_a = get_wo_by_type(row_a.link_id, "Cook")
        new_cook_b = get_wo_by_type(row_b.link_id, "Cook")

        if new_cook_a:
            _relink_quality_docs(qual_b, new_cook_a)
        if new_cook_b:
            _relink_quality_docs(qual_a, new_cook_b)

        frappe.db.set_value(CHILD_DOCTYPE, row_a_name, "custom_wo_status", "Done")
        frappe.db.set_value(CHILD_DOCTYPE, row_b_name, "custom_wo_status", "Done")
    except Exception:
        frappe.log_error(title="Background swap recipes failed", message=frappe.get_traceback())
        for name in [row_a_name, row_b_name]:
            frappe.db.set_value(CHILD_DOCTYPE, name, "custom_wo_status", "Failed")
        frappe.db.commit()


def _background_move_wo_migration(source_row_name, quality_data):
    """Background worker: process WO migration after a Change Slot move."""
    try:
        row_data = frappe.db.get_value(
            CHILD_DOCTYPE,
            {"name": source_row_name},
            ["parent", "recipe_name", "link_id", "mr_reference", "custom_wo_status"],
            as_dict=True,
        )
        if not row_data or row_data.custom_wo_status != "Processing":
            if row_data:
                frappe.db.set_value(CHILD_DOCTYPE, source_row_name, "custom_wo_status", "")
                frappe.db.commit()
            return

        from caf.caf.doctype.daily_production.rearrange_and_change_slot import (
            _cancel_cook_pack_by_id,
            _relink_quality_docs,
            _cleanup_redundant_wips,
        )
        from caf.caf.doctype.daily_production.wo_helpers import get_wo_by_type
        from frappe.utils import now_datetime

        dp = frappe.get_doc("Daily Production", row_data.parent)
        row = next((r for r in dp.production_table if r.name == source_row_name), None)
        if not row:
            frappe.db.set_value(CHILD_DOCTYPE, source_row_name, "custom_wo_status", "")
            frappe.db.commit()
            return

        if row_data.mr_reference:
            _cancel_cook_pack_by_id(row.link_id)

        new_wos = dp.create_material_request_after_change_size(
            row.recipe_name, [row]
        )
        _cleanup_redundant_wips(new_wos, row, CHILD_DOCTYPE, now_datetime())

        if row_data.mr_reference:
            new_cook_wo = get_wo_by_type(row.link_id, "Cook")
            if new_cook_wo:
                _relink_quality_docs(quality_data, new_cook_wo)

        frappe.db.set_value(CHILD_DOCTYPE, source_row_name, "custom_wo_status", "Done")
    except Exception:
        frappe.log_error(title="Background move WO migration failed", message=frappe.get_traceback())
        frappe.db.set_value(CHILD_DOCTYPE, source_row_name, "custom_wo_status", "Failed")
        frappe.db.commit()


def _background_create_mr(row_name, dp_name):
    """Background worker: create MR + WOs for a single New Schedule row."""
    try:
        current = frappe.db.get_value(
            CHILD_DOCTYPE, row_name, ["produ_status", "custom_wo_status"], as_dict=True
        )
        if not current or current.produ_status != "New Schedule":
            if current:
                frappe.db.set_value(CHILD_DOCTYPE, row_name, "custom_wo_status", "")
                frappe.db.commit()
            return

        dp = frappe.get_doc("Daily Production", dp_name)
        row = next((r for r in dp.production_table if r.name == row_name), None)
        if not row or row.produ_status != "New Schedule":
            frappe.db.set_value(CHILD_DOCTYPE, row_name, "custom_wo_status", "")
            frappe.db.commit()
            return

        final = frappe.db.get_value(CHILD_DOCTYPE, row_name, "produ_status")
        if final != "New Schedule":
            frappe.db.set_value(CHILD_DOCTYPE, row_name, "custom_wo_status", "")
            frappe.db.commit()
            return

        dp._process_new_schedules()
        frappe.db.set_value(CHILD_DOCTYPE, row_name, "custom_wo_status", "Done")
    except Exception:
        frappe.log_error(title="Background MR creation failed", message=frappe.get_traceback())
        frappe.db.set_value(CHILD_DOCTYPE, row_name, "custom_wo_status", "Failed")
        frappe.db.commit()


@frappe.whitelist()
def process_dp_updates(item_id):
    """Enqueue process_manual_updates on the parent DP in the background."""
    dp_name = frappe.db.get_value(CHILD_DOCTYPE, {"name": item_id}, "parent")
    if not dp_name:
        return {"success": False, "message": "Item not found"}

    dp = frappe.get_doc("Daily Production", dp_name)
    if dp.docstatus != 0:
        return {"success": False, "message": "DP is not in draft state"}

    _set_rows_wo_status(dp, "Processing")
    dp.save(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "caf.caf.page.production_schedule.production_schedule._background_process_dp",
        queue="long",
        timeout=600,
        dp_name=dp_name,
    )
    return {"success": True, "message": _("Processing queued")}


def _set_rows_wo_status(dp, status):
    """Set custom_wo_status on every row in the DP."""
    for row in dp.production_table:
        if row.recipe_name != NO_COOKING:
            row.custom_wo_status = status


def _background_process_dp(dp_name):
    """Background worker: runs process_manual_updates and updates row status."""
    try:
        dp = frappe.get_doc("Daily Production", dp_name)
        if dp.docstatus != 0:
            return
        dp.process_manual_updates()
        _set_rows_wo_status(dp, "Done")
        dp.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(title="Background DP processing failed", message=frappe.get_traceback())
        try:
            dp = frappe.get_doc("Daily Production", dp_name)
            if dp.docstatus == 0:
                _set_rows_wo_status(dp, "Failed")
                dp.save(ignore_permissions=True)
                frappe.db.commit()
        except Exception:
            pass
        frappe.db.commit()
