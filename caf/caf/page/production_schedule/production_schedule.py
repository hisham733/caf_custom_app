import datetime
import re

import frappe
from frappe import _
from frappe.utils import getdate, add_days

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
        fields=["name", "workstation_name"],
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

    for day in days:
        dp_info = frappe.db.get_value(
            "Daily Production",
            {"required_by": getdate(day), "docstatus": target_docstatus},
            ["name", "docstatus"],
            order_by="name desc",
            as_dict=True,
        )
        dp_names[day] = dp_info.name if dp_info else None
        day_has_dp[day] = dp_info is not None

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
        "schedule": schedule,
    }


@frappe.whitelist()
def save_move_item(item_id, source_date, target_date, target_cooker, target_round=None):
    """Move a child row between cookers, rounds, or DPs.

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

        target_nc = None
        for r in source_dp.production_table:
            if (str(r.recipe_cook_workstaion or "") == str(target_cooker) and
                str(r.recipe_cook_round or "") == str(target_round) and
                r.recipe_name == NO_COOKING and
                r.name != source_row.name):
                target_nc = r
                break

        pair_id = frappe.generate_hash(length=10)

        source_row.recipe_cook_workstaion = target_cooker
        source_row.recipe_cook_round = int(target_round)
        source_row.produ_status = "Change Slot"
        source_row.custom_pair_id = pair_id

        if target_nc:
            target_nc.recipe_cook_workstaion = old_ws
            target_nc.recipe_cook_round = old_round
            target_nc.produ_status = "Change Slot"
            target_nc.custom_pair_id = pair_id
        else:
            new_nc = source_dp.append("production_table", {})
            new_nc.recipe_name = NO_COOKING
            new_nc.recipe_cook_workstaion = old_ws
            new_nc.recipe_cook_round = old_round
            new_nc.produ_status = "Change Slot"
            new_nc.custom_pair_id = pair_id
            new_nc.required_date = source_date

        for i, r in enumerate(source_dp.production_table):
            r.idx = i + 1

        source_dp.save(ignore_permissions=True)
        frappe.db.commit()
        return {
            "success": True,
            "message": "Moved",
            "pair_id": pair_id,
            "target_row_name": target_nc.name if target_nc else None,
        }

    # Different day — not allowed
    return {"success": False, "message": "Cross-day moves are not allowed."}


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
            row.set(field, value)
            break
    else:
        return {"success": False, "message": "Row not found in DP"}

    dp.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": "Updated"}


@frappe.whitelist()
def submit_week(week_monday):
    """Submit all draft DPs for the week Mon-Sat.

    Args:
        week_monday: Date string of the Monday
    """
    from caf.caf.doctype.daily_production.daily_production import submit_dp_week

    submit_dp_week(week_monday)
    frappe.response["type"] = "json"
    return {"success": True}


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
def get_dp_row_url(dp_name, row_name):
    """Return the ERPNext URL to open a DP form scrolled to a specific row.

    Args:
        dp_name: Daily Production document name
        row_name: Child table row name

    Returns:
        Full URL string
    """
    base = frappe.utils.get_url() or ""
    return f"{base}/app/daily-production/{dp_name}?row={row_name}"


@frappe.whitelist()
def create_week_version(week_number):
    """Create new draft DPs for a week from the latest submitted versions.

    Delegates to daily_production.create_empty_dp_week_by_number.
    After creation, the new draft DPs appear in Edit Schedule mode.

    Args:
        week_number: ISO week number (e.g. 25)
    """
    from caf.caf.doctype.daily_production.daily_production import create_empty_dp_week_by_number

    create_empty_dp_week_by_number(int(week_number))
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
        return {"success": False, "message": "Swap across different DPs is not yet supported"}

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

    pair_id = frappe.generate_hash(length=10)
    row_a.produ_status = "Rearrange"
    row_b.produ_status = "Rearrange"
    row_a.custom_pair_id = pair_id
    row_b.custom_pair_id = pair_id

    dp.save(ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "message": "Recipes swapped", "pair_id": pair_id}


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
