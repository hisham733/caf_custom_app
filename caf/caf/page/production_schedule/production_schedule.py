import datetime
import re
import time

import frappe
from frappe import _
from frappe.utils import getdate, add_days
from frappe.model.naming import make_autoname

NO_COOKING = "No Cooking"
CHILD_DOCTYPE = "Create ProExl Items"


def _log_schedule_change(action_type, day=None, dp_name=None, child_row_name=None,
                         recipe_name=None, workstation=None, cook_round=None,
                         old_data=None, new_data=None):
    """Log a user action on the schedule board with full diff."""
    try:
        old_data = old_data or {}
        new_data = new_data or {}

        # Compute diff
        changes = []
        all_keys = set(list(old_data.keys()) + list(new_data.keys()))
        for key in sorted(all_keys):
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            if old_val != new_val:
                changes.append({"field": key, "old": old_val, "new": new_val})

        # Build human-readable summary
        summary = _build_log_summary(action_type, recipe_name, workstation, cook_round, day, changes)

        log_entry = frappe.get_doc({
            "doctype": "Schedule Change Log",
            "change_datetime": frappe.utils.now_datetime(),
            "changed_by": frappe.session.user,
            "action_type": action_type,
            "day": day,
            "workstation": workstation,
            "cook_round": cook_round,
            "recipe_name": recipe_name,
            "dp_name": dp_name,
            "child_row_name": child_row_name,
            "summary": summary,
            "changes_json": frappe.as_json(changes, indent=None) if changes else None,
        })
        log_entry.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="Schedule change log failed", message=frappe.get_traceback())


def _build_log_summary(action_type, recipe_name, workstation, cook_round, day, changes):
    """Build a human-readable summary string."""
    recipe_label = recipe_name or "—"
    slot_label = f"R{cook_round}" if cook_round else ""
    ws_label = f" on {workstation}" if workstation else ""
    day_label = f" ({day})" if day else ""

    action_verbs = {
        "Move": "Moved", "Swap": "Swapped", "Edit": "Edited",
        "Add Recipe": "Added", "Cancel": "Cancelled",
        "Clear": "Cleared",
        "Create WO": "Created WOs", "Submit Week": "Submitted week",
    }
    verb = action_verbs.get(action_type, action_type)

    if action_type == "Move":
        # Show: "Moved Recipe A from Cooker 3/R2 to Cooker 1/R1 (2026-07-20)"
        old_ws = changes[0]["old"] if changes and changes[0]["field"] == "recipe_cook_workstaion" else None
        old_round = changes[1]["old"] if len(changes) > 1 and changes[1]["field"] == "recipe_cook_round" else None
        from_label = ""
        if old_ws or old_round:
            from_label = f" from {old_ws or '—'}/R{old_round or '?'}"
        to_label = f" to {workstation or '—'}/R{cook_round or '?'}" if workstation else ""
        return f"{verb} {recipe_label}{from_label}{to_label}{day_label}"

    if action_type == "Swap":
        # Show: "Swapped Recipe A ↔ Recipe B (2026-07-20)"
        name_b = changes[0].get("new") if changes else "—"
        return f"{verb} {recipe_label} ↔ {name_b}{day_label}"

    if not changes:
        return f"{verb} {recipe_label}{ws_label}/{slot_label}{day_label}"

    # For edits and other actions, show changed fields
    FIELD_LABELS = {
        "size": "size", "produ_status": "status", "recipe_note": "note",
        "number_of_pack": "packs", "production_type": "type",
        "urgent_check": "urgent", "production_plane": "plane",
        "recipe_name": "recipe",
    }
    change_parts = []
    for c in changes[:5]:
        label = FIELD_LABELS.get(c["field"], c["field"])
        old_val = c["old"] if c["old"] is not None else "—"
        new_val = c["new"] if c["new"] is not None else "—"
        change_parts.append(f"{label}: {old_val} → {new_val}")
    diff_str = "; ".join(change_parts)
    if len(changes) > 5:
        diff_str += f" (+{len(changes) - 5} more)"

    return f"{verb} {recipe_label}{ws_label}/{slot_label}{day_label} — {diff_str}"


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
        "raw_materials": 0,  # populated client-side from BOM data
        "total_input": 0,
        "total_output": 0,
        "link_id": row.link_id or "",
        "required_date": str(row.required_date) if row.required_date else "",
        "urgent": bool(row.get("urgent_check")),
        "pack_items": pack_items,
        "recipe_note": row.get("recipe_note") or "",
        "production_plane": row.get("production_plane") or "",
        "mr_reference": row.get("mr_reference") or "",
        "pair_id": row.get("custom_pair_id") or "",
        "wo_status": row.get("rq_status") or "",
        "wo_error": row.get("custom_wo_error") or "",
    }


@frappe.whitelist()
def get_week_data(year, week_number, mode):
    """Load the weekly schedule for the targeted workstations.

    Per-day latest DP logic:
      - "View Schedule" → workflow_state = "Submitted"
      - "Edit Schedule" → workflow_state != "Submitted" (or empty)

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

    if mode == "View Schedule":
        dp_filter = {"workflow_state": "Submitted"}
    else:
        dp_filter = {"workflow_state": ["!=", "Submitted"]}

    dp_names = {}
    day_has_dp = {}
    dp_submit_refs = {}

    # Phase 1a: Batch DP lookups — single query instead of 6
    all_dps = frappe.get_all(
        "Daily Production",
        filters={"required_by": ["in", [getdate(d) for d in days]], "docstatus": 0, **dp_filter},
        fields=["name", "required_by", "custom_submit_ref"],
        order_by="name desc",
    )
    # Build lookup maps
    dp_by_day = {}
    for dp in all_dps:
        day_str = str(dp.required_by)
        if day_str not in dp_by_day or dp.name > dp_by_day[day_str].name:
            dp_by_day[day_str] = dp
    for day in days:
        info = dp_by_day.get(day)
        dp_names[day] = info.name if info else None
        day_has_dp[day] = info is not None
        dp_submit_refs[day] = info.custom_submit_ref if info else None

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
                "rounds": {},
                "note": "",
                "pack": "",
            }

    # Phase 1b: Batch child row fetch — single query instead of up to 6
    _dp_names = [n for n in dp_names.values() if n]
    all_rows = {}
    if _dp_names:
        raw_rows = frappe.get_all(
            CHILD_DOCTYPE,
            filters={"parent": ["in", _dp_names]},
            fields=[
                "name", "parent", "recipe_name", "size", "recipe_cook_workstaion",
                "recipe_cook_round", "required_date", "produ_status",
                "number_of_pack", "recipe_note", "production_type",
                "recipe_cook_time", "custom_yield", "link_id", "custom_pair_id",
                "mr_reference", "production_plane", "urgent_check",
                "rq_status", "custom_wo_error",
                "pack_remark", "pack_remark_2", "pack_remark_3",
                "pack_remark_4", "pack_remark_5", "pack_remark_6", "pack_remark_7",
                "pack_name", "pack_name_2", "pack_name_3",
                "pack_name_4", "pack_name_5", "pack_name_6", "pack_name_7",
                "pack_qty", "pack_qty_2", "pack_qty_3",
                "pack_qty_4", "pack_qty_5", "pack_qty_6", "pack_qty_7",
            ],
            order_by="idx asc",
        )
        for r in raw_rows:
            parent = r.get("parent")
            if parent not in all_rows:
                all_rows[parent] = []
            all_rows[parent].append(r)

    # Fill rows from DB using batched results
    for day in days:
        dp_name = dp_names.get(day)
        if not dp_name:
            continue

        rows = all_rows.get(dp_name, [])

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

            # Dynamically add the round slot if not yet present, then fill it
            if round_num not in schedule[ws_name][day]["rounds"]:
                schedule[ws_name][day]["rounds"][round_num] = None

            if schedule[ws_name][day]["rounds"][round_num] is None:
                schedule[ws_name][day]["rounds"][round_num] = _build_round_data(row, recipe_name)

        # Apply combined notes/packs
        for ws_name in day_notes:
            if ws_name in schedule:
                schedule[ws_name][day]["note"] = " / ".join(
                    d for d in day_notes[ws_name] if d) if day_notes[ws_name] else ""
                schedule[ws_name][day]["pack"] = " / ".join(
                    d for d in day_packs[ws_name] if d) if day_packs[ws_name] else ""

    # Compute per-day round keys from actual data (union of all workstations for that day)
    day_round_keys = {}
    for day in days:
        keys = set()
        for ws in workstations:
            for rk in schedule[ws["name"]][day]["rounds"]:
                keys.add(rk)
        day_round_keys[day] = sorted(keys, key=int) if keys else ["1", "2", "3"]

    return {
        "workstations": workstations,
        "days": days,
        "day_labels": day_labels,
        "dp_names": dp_names,
        "dp_submit_refs": dp_submit_refs,
        "schedule": schedule,
        "day_round_keys": day_round_keys,
    }


@frappe.whitelist()
def save_move_item(item_id, source_date, target_date, target_cooker, target_round=None):
    """Move a child row between cookers, rounds, or DPs.

    No WOs: recipe data moves, status preserved, ws/round/link_id stay static to slot.
    Has WOs (same-day only): ws/round/link_id swap, "Change Slot" status, WO migration.
    Cross-day: only allowed when neither DP has WOs. Recipe data moves, status preserved.

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
    if source_row.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}

    # Same day: move recipe between slots
    if source_date == target_date:
        target_nc = None
        for r in source_dp.production_table:
            if (str(r.recipe_cook_workstaion or "") == str(target_cooker) and
                str(r.recipe_cook_round or "") == str(target_round) and
                r.recipe_name == NO_COOKING and
                r.name != source_row.name):
                target_nc = r
                break

        if not target_nc:
            new_nc = source_dp.append("production_table", {})
            new_nc.recipe_name = NO_COOKING
            new_nc.recipe_cook_workstaion = target_cooker
            new_nc.recipe_cook_round = int(target_round)
            new_nc.required_date = source_date
            target_nc = new_nc

        has_wos = bool(source_dp.custom_submit_ref)

        if has_wos:
            # ── Has WOs: swap ws/round/link_id + "Change Slot" + WO migration ──
            old_ws = source_row.recipe_cook_workstaion
            old_round = source_row.recipe_cook_round
            old_link_id = source_row.link_id

            source_row.recipe_cook_workstaion = target_cooker
            source_row.recipe_cook_round = int(target_round)

            target_nc.recipe_cook_workstaion = old_ws
            target_nc.recipe_cook_round = old_round

            if not target_nc.link_id:
                target_nc.link_id = make_autoname("R-.YYYY.-.#####")

            target_link_id = target_nc.link_id
            target_nc.link_id = old_link_id
            source_row.link_id = target_link_id

            from frappe.utils import now_datetime
            pair_id = now_datetime().strftime("%Y%m%d%H%M%S%f")
            source_row.produ_status = "Change Slot"
            target_nc.produ_status = "Change Slot"
            source_row.custom_pair_id = pair_id
            target_nc.custom_pair_id = pair_id

            # Guard: Cook WO must not be Completed
            cook_status = frappe.db.get_value("Work Order",
                {"custom_link_id": old_link_id, "custom_item_type": "Cook", "docstatus": ["<", 2]},
                "status")
            if cook_status == "Completed":
                return {"success": False, "message": _("Cook Work Order is already Completed. Cannot change slot.")}

            from caf.caf.doctype.daily_production.rearrange_and_change_slot import (
                _get_quality_data_by_id,
            )
            quality_data = _get_quality_data_by_id(old_link_id)

            from caf.caf.doctype.daily_production.rearrange_and_change_slot import (
                _migrate_db_link_ids,
            )
            _migrate_db_link_ids(source_id=old_link_id, target_id=source_row.link_id)

            source_row.rq_status = "Processing"
            target_nc.rq_status = "Processing"
        else:
            # ── No WOs: just move recipe data, keep ws/round/link_id static ──
            saved_status = source_row.produ_status
            saved_ws = source_row.recipe_cook_workstaion
            saved_round = source_row.recipe_cook_round
            saved_link_id = source_row.link_id

            # Save source recipe data
            old_recipe = source_row.recipe_name
            old_size = source_row.size
            old_pack_count = source_row.number_of_pack
            old_prod_type = source_row.production_type
            old_urgent = source_row.urgent_check
            old_note = source_row.recipe_note
            old_prod_plane = source_row.production_plane
            old_yield = source_row.custom_yield
            old_packs = {}
            for i in range(1, 8):
                suffix = "" if i == 1 else f"_{i}"
                old_packs[i] = {
                    "name": source_row.get(f"pack_name{suffix}"),
                    "qty": source_row.get(f"pack_qty{suffix}"),
                    "remark": source_row.get(f"pack_remark{suffix}"),
                }

            # Clear source row → No Cooking (keep its own ws/round/link_id)
            source_row.recipe_name = NO_COOKING
            source_row.produ_status = ""
            source_row.size = 0
            source_row.number_of_pack = 0
            source_row.production_type = ""
            source_row.urgent_check = 0
            source_row.recipe_note = ""
            source_row.production_plane = ""
            source_row.custom_yield = None
            source_row.mr_reference = None
            source_row.wo_list = None
            source_row.wo_list_with_type = None
            source_row.custom_pair_id = ""
            for i in range(1, 8):
                suffix = "" if i == 1 else f"_{i}"
                source_row.set(f"pack_name{suffix}", None)
                source_row.set(f"pack_qty{suffix}", 0)
                source_row.set(f"pack_remark{suffix}", None)

            # Target NC receives recipe data (keep its own ws/round/link_id)
            target_nc.recipe_name = old_recipe
            target_nc.size = old_size
            target_nc.number_of_pack = old_pack_count
            target_nc.production_type = old_prod_type
            target_nc.urgent_check = old_urgent
            target_nc.recipe_note = old_note
            target_nc.production_plane = old_prod_plane
            target_nc.custom_yield = old_yield
            target_nc.produ_status = saved_status
            for i in range(1, 8):
                suffix = "" if i == 1 else f"_{i}"
                target_nc.set(f"pack_name{suffix}", old_packs[i]["name"])
                target_nc.set(f"pack_qty{suffix}", old_packs[i]["qty"])
                target_nc.set(f"pack_remark{suffix}", old_packs[i]["remark"])

        for i, r in enumerate(source_dp.production_table):
            r.idx = i + 1

        source_dp.flags.skip_edit_log = True
        source_dp.save(ignore_permissions=True)
        frappe.db.commit()

        _log_schedule_change("Move", day=source_date, dp_name=source_dp.name,
                             child_row_name=source_row.name,
                             recipe_name=old_recipe if not has_wos else source_row.recipe_name,
                             workstation=target_cooker, cook_round=int(target_round),
                             old_data={"recipe_cook_workstaion": saved_ws if not has_wos else old_ws,
                                       "recipe_cook_round": saved_round if not has_wos else old_round},
                             new_data={"recipe_cook_workstaion": target_cooker,
                                       "recipe_cook_round": int(target_round)})

        if has_wos:
            frappe.enqueue(
                "caf.caf.page.production_schedule.production_schedule._background_move_wo_migration",
                queue="long",
                timeout=600,
                dp_name=source_dp.name,
            )

        return {
            "success": True,
            "message": "Moved",
            "has_wos": has_wos,
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
    old_status = source_row.produ_status
    old_yield = source_row.custom_yield
    old_ws = source_row.recipe_cook_workstaion
    old_round = source_row.recipe_cook_round
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
    source_row.custom_yield = None
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
    target_nc.custom_yield = old_yield
    target_nc.produ_status = old_status
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

    source_dp.flags.skip_edit_log = True
    target_dp.flags.skip_edit_log = True
    source_dp.save(ignore_permissions=True)
    target_dp.save(ignore_permissions=True)
    frappe.db.commit()

    _log_schedule_change("Move", day=target_date, dp_name=target_dp.name,
                         child_row_name=target_nc.name, recipe_name=old_recipe,
                         workstation=target_cooker, cook_round=int(target_round),
                         old_data={"required_date": str(source_date),
                                   "recipe_cook_workstaion": old_ws,
                                   "recipe_cook_round": old_round},
                         new_data={"required_date": str(target_date),
                                   "recipe_cook_workstaion": target_cooker,
                                   "recipe_cook_round": int(target_round)})

    return {"success": True, "message": "Moved"}


@frappe.whitelist()
def save_update_item(item_id, field, value):
    """Update a single field on a child row of a draft DP.

    Phase 2a: Uses db.set_value instead of full DP load+save (~158q → ~4q).
    """
    # Get row data for rq_status check and logging
    row_data = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": item_id},
        ["name", "parent", "rq_status", "recipe_name", "recipe_cook_workstaion",
         "recipe_cook_round", "produ_status", "required_date"],
        as_dict=True,
    )
    if not row_data:
        return {"success": False, "message": "Item not found"}

    if row_data.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}

    values = {field: value}
    if field == "produ_status" and value == "New Schedule":
        values["mr_reference"] = None
        values["wo_list"] = None
        values["wo_list_with_type"] = None

    frappe.db.set_value(CHILD_DOCTYPE, item_id, values)

    # Log the change
    _log_schedule_change("Edit", day=row_data.required_date, dp_name=row_data.parent,
                         child_row_name=item_id, recipe_name=row_data.recipe_name,
                         workstation=row_data.recipe_cook_workstaion,
                         cook_round=row_data.recipe_cook_round,
                         old_data={field: None},
                         new_data={field: value})

    frappe.db.commit()
    return {"success": True, "message": "Updated"}
    return {"success": True, "message": "Updated"}


@frappe.whitelist()
def save_item_fields(item_id, fields):
    """Save multiple fields on a child row in a single transaction.

    Phase 2a: Uses db.set_value instead of full DP load+save (~158q → ~4q).
    """
    import json
    if isinstance(fields, str):
        fields = json.loads(fields)

    # Get row data for rq_status check and logging
    row_data = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": item_id},
        ["name", "parent", "rq_status", "recipe_name", "recipe_cook_workstaion",
         "recipe_cook_round", "required_date"],
        as_dict=True,
    )
    if not row_data:
        return {"success": False, "message": "Item not found"}

    if row_data.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}

    values = {}
    old_data = {}
    for f in fields:
        fname = f.get("field")
        fval = f.get("value")
        old_data[fname] = None
        values[fname] = fval

    frappe.db.set_value(CHILD_DOCTYPE, item_id, values)

    new_data = {f.get("field"): f.get("value") for f in fields}

    _log_schedule_change("Edit", day=row_data.required_date, dp_name=row_data.parent,
                         child_row_name=item_id, recipe_name=row_data.recipe_name,
                         workstation=row_data.recipe_cook_workstaion,
                         cook_round=row_data.recipe_cook_round,
                         old_data=old_data, new_data=new_data)

    frappe.db.commit()
    return {"success": True, "message": "Updated"}


@frappe.whitelist()
def send_day_schedule(week_monday, day_index, custom_message=""):
    """Send a selected day's DP schedule image to WhatsApp.

    Validates that Work Orders were already created for that day before
    sending. Returns a JSON response.

    Args:
        week_monday: Date string of the Monday
        day_index: 0=Mon, 1=Tue, ..., 5=Sat
        custom_message: Optional text appended to the WhatsApp image caption.
    """
    from datetime import timedelta

    monday = getdate(week_monday)
    day = monday + timedelta(days=int(day_index))

    dp_name = frappe.db.get_value(
        "Daily Production",
        {"required_by": str(day), "docstatus": 0},
        "name",
        order_by="name desc",
    )
    if not dp_name:
        return {"success": False, "message": _("No Daily Production for {0}.").format(str(day))}

    dp = frappe.get_doc("Daily Production", dp_name)
    if dp.workflow_state != "Submitted":
        return {
            "success": False,
            "message": _("Daily Production for {0} is not Submitted yet. Please Submit it first.").format(str(day)),
        }

    has_mr = any(row.mr_reference for row in dp.production_table)
    if not dp.custom_submit_ref or not has_mr:
        return {
            "success": False,
            "message": _("Work Orders are not created for {0} yet. Please Create WO first.").format(str(day)),
        }

    try:
        from caf.caf.utils.notifications import notify_dp_schedule
        frappe.enqueue(notify_dp_schedule, dp_name=dp.name, queue="short", caption_extra=custom_message)
    except Exception:
        frappe.log_error(title="Send day schedule failed", message=frappe.get_traceback())
        return {"success": False, "message": _("Failed to queue the WhatsApp message.")}

    return {"success": True, "message": _("Schedule for {0} sent to WhatsApp.").format(str(day))}


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
        {"required_by": str(day), "docstatus": 0, "workflow_state": "Submitted"},
        "name",
        order_by="name desc",
    )
    if not dp_name:
        return {"success": False, "message": _("No submitted DP for {0}").format(str(day))}

    dp = frappe.get_doc("Daily Production", dp_name)
    if dp.custom_submit_ref:
        has_mr = any(row.mr_reference for row in dp.production_table)
        if not has_mr:
            frappe.db.set_value("Daily Production", dp_name, "custom_submit_ref", "")
            frappe.db.commit()
            dp.reload()
        else:
            return {"success": False, "message": _("Work Orders already created for {0}").format(str(day))}

    for row in dp.production_table:
        if row.rq_status == "Processing":
            return {"success": False, "message": _("Work Orders are being processed for {0}. Please wait.").format(str(day))}

    try:
        dp.process_manual_updates()

        # Clear all produ_status after successful WO creation
        frappe.db.sql("""
            UPDATE `tabCreate ProExl Items`
            SET produ_status = ''
            WHERE parent = %s AND produ_status != ''
        """, dp.name)

        _log_schedule_change("Create WO", day=str(day), dp_name=dp.name,
                             old_data={}, new_data={"action": "process_manual_updates"})
        return {
            "success": True,
            "message": _("Work Orders created for {0}").format(str(day)),
        }
    except Exception as e:
        frappe.log_error(title="process_day_dp failed", message=frappe.get_traceback())
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def submit_week(week_monday):
    """Switch all draft DPs for the week Mon-Sat to View mode.

    Sets workflow_state = "Submitted" (docstatus stays 0).
    WO creation happens later via the Create WO button in View mode.

    Skips past days (before today).
    Aborts entire week if any DP has Processing rows.
    Returns JSON response.

    Args:
        week_monday: Date string of the Monday
    """
    monday = getdate(week_monday)
    days = [monday + datetime.timedelta(days=i) for i in range(6)]
    today = datetime.date.today()

    submitted = 0
    skipped_past = 0
    skipped_no_dp = 0
    skipped_empty = 0

    for day in days:
        if day < today:
            skipped_past += 1
            continue

        dp_name = frappe.db.get_value(
            "Daily Production",
            {"required_by": day, "docstatus": 0, "workflow_state": ["!=", "Submitted"]},
            "name",
            order_by="name desc",
        )
        if not dp_name:
            skipped_no_dp += 1
            continue

        dp = frappe.get_doc("Daily Production", dp_name)

        if not any(r.recipe_name != NO_COOKING for r in dp.production_table):
            skipped_empty += 1
            continue

        has_processing = any(row.rq_status == "Processing" for row in dp.production_table)
        if has_processing:
            return {"success": False, "message": _("Work Orders are being processed for {0}. Please wait.").format(str(day))}

        frappe.db.set_value("Daily Production", dp.name, "workflow_state", "Submitted")
        frappe.db.commit()
        submitted += 1

    if submitted == 0:
        return {
            "success": False,
            "message": _("No draft DPs found for this week."),
        }

    _log_schedule_change("Submit Week", day=str(monday), old_data={},
                         new_data={"submitted": submitted, "skipped_past": skipped_past,
                                   "skipped_empty": skipped_empty})

    return {
        "success": True,
        "message": _("Submitted {0} DP(s). Skipped {1} past, {2} empty.").format(submitted, skipped_past, skipped_empty),
    }


@frappe.whitelist()
def edit_week(week_monday):
    """Switch all DPs for the week Mon-Sat to Edit mode.

    For each day Mon-Sat (skipping past days):
    - If a DP exists and is in Submitted state → flips workflow_state to ""
    - If no DP exists → creates an empty DP with No Cooking placeholders

    Args:
        week_monday: Date string of the Monday
    """
    from caf.caf.doctype.daily_production.daily_production import get_merged_production_items

    monday = getdate(week_monday)
    days = [monday + datetime.timedelta(days=i) for i in range(6)]
    today = datetime.date.today()

    edited = 0
    created = 0
    skipped_past = 0

    for day in days:
        if day < today:
            skipped_past += 1
            continue

        # Check if DP already exists for this date
        dp_name = frappe.db.get_value(
            "Daily Production",
            {"required_by": day, "docstatus": 0},
            "name",
            order_by="name desc",
        )

        if dp_name:
            # Flip to Edit mode if currently Submitted
            current_state = frappe.db.get_value("Daily Production", dp_name, "workflow_state")
            if current_state == "Submitted":
                frappe.db.set_value("Daily Production", dp_name, "workflow_state", "Draft")
                frappe.db.commit()
                edited += 1
        else:
            # Create empty DP for this day
            doc = frappe.new_doc("Daily Production")
            doc.required_by = str(day)

            data = get_merged_production_items(str(day), "Daily Production")
            if data and data.get("rows"):
                excluded = ["name", "parent", "parentfield", "parenttype", "doctype", "idx"]
                for item in data["rows"]:
                    child = doc.append("production_table", {})
                    for key, value in item.items():
                        if key not in excluded:
                            child.set(key, value)

            doc.planner_name = frappe.get_value("User", frappe.session.user, "full_name")
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            created += 1

    return {
        "success": True,
        "message": _("Switched {0} DP(s) to Edit mode, created {1} new DP(s). Skipped {2} past.").format(
            edited, created, skipped_past
        ),
    }


@frappe.whitelist()
def _get_or_create_dp(day):
    """Find the latest draft DP for a day, or create one if none exists."""
    dp_name = frappe.db.get_value(
        "Daily Production",
        {"required_by": day, "docstatus": 0},
        "name",
        order_by="name desc",
    )
    if dp_name:
        return {"dp_name": dp_name}

    # Create a new DP for this day
    from caf.caf.doctype.daily_production.daily_production import get_merged_production_items
    doc = frappe.new_doc("Daily Production")
    doc.required_by = day
    data = get_merged_production_items(day, "Daily Production")
    if data and data.get("rows"):
        excluded = ["name", "parent", "parentfield", "parenttype", "doctype", "idx"]
        for item in data["rows"]:
            child = doc.append("production_table", {})
            for key, value in item.items():
                if key not in excluded:
                    child.set(key, value)
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"dp_name": doc.name}


@frappe.whitelist()
def add_recipe(day, recipe, size, cooker, pack_count, round_num, **kwargs):
    """Add a new recipe row to the draft DP for the given day."""
    dp_name = frappe.db.get_value(
        "Daily Production",
        {"required_by": day, "docstatus": 0},
        "name",
    )
    if not dp_name:
        return {"success": False, "message": f"No draft DP for {day}"}

    dp = frappe.get_doc("Daily Production", dp_name)

    cooker_str = str(cooker or "").strip()
    round_str = str(round_num or "1").strip()
    existing_row = None
    for r in dp.production_table:
        if (str(r.recipe_cook_workstaion or "").strip() == cooker_str
                and str(r.recipe_cook_round or "").strip() == round_str):
            existing_row = r
            break

    if existing_row is None:
        # Debug: log what slots exist
        slots = [(str(r.recipe_cook_workstaion or ""), str(r.recipe_cook_round or "")) for r in dp.production_table]
        frappe.log_error(
            title="add_recipe: slot not found",
            message=f"Looking for: ws='{cooker_str}', round='{round_str}'\nDP: {dp_name}\nAvailable: {slots[:100]}"
        )
        return {"success": False, "message": "No existing slot found. Please refresh the page."}

    if existing_row.recipe_name != NO_COOKING:
        return {"success": False, "message": "A recipe already exists at this slot. Please refresh the page."}

    if existing_row.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}
    row = existing_row

    old_recipe_name = row.recipe_name if row.recipe_name and row.recipe_name != NO_COOKING else None
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
        row.rq_status = "Processing"

    for i in range(1, 8):
        suffix = "" if i == 1 else "_{}".format(i)
        for pfield in ("pack_name", "pack_qty", "pack_remark"):
            val = kwargs.get(pfield + suffix)
            if val:
                row.set(pfield + suffix, val)

    for i, r in enumerate(dp.production_table):
        r.idx = i + 1

    dp.flags.skip_edit_log = True
    dp.save(ignore_permissions=True)
    frappe.db.commit()

    _log_schedule_change("Add Recipe", day=day, dp_name=dp.name,
                         child_row_name=row.name, recipe_name=recipe,
                         workstation=cooker, cook_round=int(round_num) if round_num else 1,
                         old_data={"recipe_name": old_recipe_name} if old_recipe_name else {},
                         new_data={"recipe_name": recipe, "size": row.size,
                                   "produ_status": row.produ_status or ""})

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
            "recipe": recipe,
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
    """No-op: versioning removed. Only one DP per date."""
    frappe.response["type"] = "json"
    return {"success": True}


@frappe.whitelist()
def swap_recipes(source_id, target_id):
    """Swap recipe data between two child rows, keeping slot identity fields.

    No WOs: swaps recipe data, keeps existing statuses.
    Has WOs: swaps recipe data, sets both to "Rearrange" + pair_id, WO migration.

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

        row_a = next((r for r in src_doc.production_table if r.name == source_id), None)
        row_b = next((r for r in tgt_doc.production_table if r.name == target_id), None)
        if not row_a or not row_b:
            return {"success": False, "message": "Row not found"}
        if row_a.rq_status == "Processing" or row_b.rq_status == "Processing":
            return {"success": False, "message": "Work Orders are being processed. Please wait."}

        swappable = [
            df.fieldname for df in _get_child_meta_fields()
            if df.fieldname not in SLOT_FIELDS
        ]
        old_a = {fn: row_a.get(fn) for fn in swappable}
        old_b = {fn: row_b.get(fn) for fn in swappable}
        for fn in swappable:
            val_a, val_b = row_a.get(fn), row_b.get(fn)
            row_a.set(fn, val_b)
            row_b.set(fn, val_a)
        new_a = {fn: row_a.get(fn) for fn in swappable}
        new_b = {fn: row_b.get(fn) for fn in swappable}

        src_doc.flags.skip_edit_log = True
        tgt_doc.flags.skip_edit_log = True
        src_doc.save(ignore_permissions=True)
        tgt_doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Build swap diff: show row_a's fields that changed
        swap_changes = []
        for fn in swappable:
            if old_a.get(fn) != new_a.get(fn):
                swap_changes.append({"field": fn, "old": old_a.get(fn), "new": new_a.get(fn)})
        _log_schedule_change("Swap", day=row_a.required_date, dp_name=src_doc.name,
                             child_row_name=source_id, recipe_name=row_a.recipe_name,
                             workstation=row_a.recipe_cook_workstaion, cook_round=row_a.recipe_cook_round,
                             old_data={"recipe_name_A": old_a.get("recipe_name"), "recipe_name_B": old_b.get("recipe_name")},
                             new_data={"recipe_name_A": new_a.get("recipe_name"), "recipe_name_B": new_b.get("recipe_name")})
        return {"success": True, "message": "Recipes swapped"}

    dp = frappe.get_doc("Daily Production", src_dp)

    row_a = row_b = None
    for row in dp.production_table:
        if row.name == source_id:
            row_a = row
        elif row.name == target_id:
            row_b = row
    if row_a is None or row_b is None:
        return {"success": False, "message": "Row not found"}
    if row_a.rq_status == "Processing" or row_b.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}

    has_wos = bool(dp.custom_submit_ref)

    swappable = [
        df.fieldname for df in _get_child_meta_fields()
        if df.fieldname not in SLOT_FIELDS
    ]

    old_a = {fn: row_a.get(fn) for fn in swappable}
    old_b = {fn: row_b.get(fn) for fn in swappable}
    for fn in swappable:
        val_a = row_a.get(fn)
        val_b = row_b.get(fn)
        row_a.set(fn, val_b)
        row_b.set(fn, val_a)
    new_a = {fn: row_a.get(fn) for fn in swappable}
    new_b = {fn: row_b.get(fn) for fn in swappable}

    if has_wos:
        from frappe.utils import now_datetime

        # Guard: neither Cook WO must be Completed
        for check_row, check_name in [(row_a, "first"), (row_b, "second")]:
            cook_status = frappe.db.get_value("Work Order",
                {"custom_link_id": check_row.link_id, "custom_item_type": "Cook", "docstatus": ["<", 2]},
                "status")
            if cook_status == "Completed":
                return {"success": False, "message": _("Cook Work Order is already Completed for {0} recipe. Cannot rearrange.").format(check_name)}

        pair_id = now_datetime().strftime("%Y%m%d%H%M%S%f")
        row_a.produ_status = "Rearrange"
        row_b.produ_status = "Rearrange"
        row_a.custom_pair_id = pair_id
        row_b.custom_pair_id = pair_id
        row_a.rq_status = "Processing"
        row_b.rq_status = "Processing"

    dp.flags.skip_edit_log = True
    dp.save(ignore_permissions=True)
    frappe.db.commit()

    _log_schedule_change("Swap", day=row_a.required_date, dp_name=dp.name,
                         child_row_name=source_id, recipe_name=row_a.recipe_name,
                         workstation=row_a.recipe_cook_workstaion, cook_round=row_a.recipe_cook_round,
                         old_data={"recipe_name_A": old_a.get("recipe_name"), "recipe_name_B": old_b.get("recipe_name")},
                         new_data={"recipe_name_A": new_a.get("recipe_name"), "recipe_name_B": new_b.get("recipe_name")})

    if has_wos:
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
    """Fetch BOM data for a recipe: custom_yield, custom_raw_materails, and pack count.

    Args:
        recipe_name: Item name (recipe)

    Returns:
        Dict with yield, raw_materials, and pack_count values
    """
    bom = frappe.db.get_value(
        "BOM",
        {"item": recipe_name, "docstatus": 1, "is_active": 1, "is_default": 1},
        ["name", "custom_yield", "custom_raw_materails"],
        as_dict=True,
        order_by="modified desc",
    )
    pack_count = frappe.db.sql("""
        SELECT COUNT(DISTINCT bom.item)
        FROM `tabBOM` AS bom
        INNER JOIN `tabBOM Item` AS bom_item ON bom_item.parent = bom.name
        WHERE bom_item.item_code = %s
          AND bom.is_active = 1 AND bom.docstatus = 1
          AND bom.is_default = 1
    """, recipe_name)[0][0]
    return {
        "yield": (bom.custom_yield or 0) if bom else 0,
        "raw_materials": (bom.custom_raw_materails or 0) if bom else 0,
        "pack_count": min(pack_count, 7),
    }


@frappe.whitelist()
def validate_pack_weights(recipe_name, size, packs):
    """Check if total output is enough for all pack quantities.

    Args:
        recipe_name: Item name (recipe)
        size: Batch size
        packs: JSON string — list of {name, qty}

    Returns:
        Dict with valid flag and error message if invalid
    """
    import json
    packs = json.loads(packs) if isinstance(packs, str) else packs

    if not packs or len(packs) <= 1:
        return {"valid": True, "message": ""}

    bom = frappe.db.get_value(
        "BOM",
        {"item": recipe_name, "docstatus": 1, "is_active": 1},
        ["custom_raw_materails"],
        as_dict=True,
        order_by="modified desc",
    )
    if not bom or not bom.custom_raw_materails:
        return {"valid": True, "message": ""}

    raw_materials = float(bom.custom_raw_materails)
    total_output = raw_materials * float(size)

    # Batch fetch all pack weights in single query
    pack_names = [p.get("name") for p in packs if p.get("name")]
    weight_map = _get_pack_weights_batch(pack_names)

    # Sum weighted qty of all packs except the last
    weighted_sum = 0
    for pack in packs[:-1]:
        if not pack.get("name") or not pack.get("qty"):
            continue
        weight = weight_map.get(pack["name"], 0)
        weighted_sum += float(pack["qty"]) * weight

    last_pack = packs[-1]
    last_qty = float(last_pack.get("qty") or 0)
    last_weight = weight_map.get(last_pack.get("name") or "", 0)

    if last_qty > 0:
        # User entered last pack qty — validate total weighted sum
        weighted_sum += last_qty * last_weight
        if weighted_sum > total_output:
            min_size = int(weighted_sum / raw_materials) + 1
            return {
                "valid": False,
                "message": _("Not enough output: total input is {0:.2f} kg but packs need {1:.2f} kg. Increase size to at least {2}.").format(total_output, weighted_sum, min_size),
            }
    else:
        # Last pack gets remaining — check at least 1 unit possible
        remaining = total_output - weighted_sum
        if remaining < last_weight and last_weight > 0:
            min_size = int((weighted_sum + last_weight) / raw_materials) + 1
            return {
                "valid": False,
                "message": _("Not enough output: remaining {0:.2f} kg cannot pack '{1}' (min weight: {2:.2f} kg). Increase size to at least {3}.").format(remaining, last_pack.get("name") or "", last_weight, min_size),
            }

    return {"valid": True, "message": ""}


def _get_pack_weight(item_code):
    """Fetch pack item weight from Item Variant Attribute (Weight) or Item.weight_per_unit."""
    weight = frappe.db.get_value(
        "Item Variant Attribute",
        {"parent": item_code, "attribute": "Weight"},
        "attribute_value",
    )
    if weight is None:
        weight = frappe.db.get_value("Item", item_code, "weight_per_unit")
    return float(weight or 0)


def _get_pack_weights_batch(item_codes):
    """Fetch weights for multiple pack items in a single batch query.

    Returns dict mapping item_code -> weight (float).
    Uses Item Variant Attribute (Weight) first, falls back to Item.weight_per_unit.
    """
    if not item_codes:
        return {}

    unique_codes = list(set(item_codes))
    weights = {}

    # Batch fetch from Item Variant Attribute
    iva_rows = frappe.get_all(
        "Item Variant Attribute",
        filters={"parent": ["in", unique_codes], "attribute": "Weight"},
        fields=["parent", "attribute_value"],
    )
    for row in iva_rows:
        weights[row.parent] = float(row.attribute_value or 0)

    # Find items not yet weighted — fallback to Item.weight_per_unit
    missing = [c for c in unique_codes if c not in weights]
    if missing:
        item_rows = frappe.get_all(
            "Item",
            filters={"name": ["in", missing]},
            fields=["name", "weight_per_unit"],
        )
        for row in item_rows:
            weights[row.name] = float(row.weight_per_unit or 0)

    # Any still missing get 0
    for c in unique_codes:
        if c not in weights:
            weights[c] = 0.0

    return weights


@frappe.whitelist()
def get_row_status(item_id):
    """Lightweight poll: return wo_status, mr_reference, and error for a row."""
    vals = frappe.db.get_value(
        CHILD_DOCTYPE,
        {"name": item_id},
        ["rq_status", "mr_reference", "custom_wo_error"],
        as_dict=True,
    )
    if vals:
        return {
            "wo_status": vals.rq_status or "",
            "mr_reference": vals.mr_reference or "",
            "error": vals.custom_wo_error or "",
        }
    return {"wo_status": "", "mr_reference": "", "error": ""}


@frappe.whitelist()
def process_recipe_change(item_id):
    """Enqueue background recipe change WO reprocessing for a row."""
    row_data = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": item_id},
        ["parent", "produ_status", "mr_reference", "recipe_name", "rq_status", "link_id"],
        as_dict=True,
    )
    if not row_data:
        return {"success": False, "message": "Item not found"}
    if row_data.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}
    if row_data.produ_status != "Recipe Change" or not row_data.mr_reference:
        return {"success": False, "message": "No recipe change needed"}

    # Guard: Cook WO must not be Completed
    if row_data.link_id:
        cook_status = frappe.db.get_value("Work Order",
            {"custom_link_id": row_data.link_id, "custom_item_type": "Cook", "docstatus": ["<", 2]},
            "status")
        if cook_status == "Completed":
            return {"success": False, "message": _("Cook Work Order is already Completed. Cannot change recipe.")}

    dp_custom_submit_ref = frappe.db.get_value("Daily Production", row_data.parent, "custom_submit_ref")
    if not dp_custom_submit_ref:
        return {"success": True, "message": _("Saved — will be processed when Work Orders are created")}

    frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "Processing")

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
def process_pack_change(item_id):
    """Enqueue background pack change WO reprocessing for a row."""
    row_data = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": item_id},
        ["parent", "produ_status", "mr_reference", "rq_status", "link_id"],
        as_dict=True,
    )
    if not row_data:
        return {"success": False, "message": "Item not found"}
    if row_data.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}
    if row_data.produ_status != "Pack Change" or not row_data.mr_reference:
        return {"success": False, "message": "No pack change needed"}

    # Guard: no Pack WO must be Completed
    if row_data.link_id:
        completed_pack = frappe.db.get_value("Work Order",
            {"custom_link_id": row_data.link_id, "custom_item_type": "Pack", "docstatus": ["<", 2], "status": "Completed"},
            "name")
        if completed_pack:
            return {"success": False, "message": _("A Pack Work Order is already Completed. Cannot change pack.")}

    dp_custom_submit_ref = frappe.db.get_value("Daily Production", row_data.parent, "custom_submit_ref")
    if not dp_custom_submit_ref:
        return {"success": True, "message": _("Saved — will be processed when Work Orders are created")}

    frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "Processing")

    frappe.enqueue(
        "caf.caf.page.production_schedule.production_schedule._background_pack_change",
        queue="long",
        timeout=600,
        item_id=item_id,
        dp_name=row_data.parent,
    )
    return {"success": True, "message": _("Pack change queued")}


@frappe.whitelist()
def check_cook_wo_completed(item_id):
    """Pre-check if Cook WO is Completed before allowing recipe change."""
    row = frappe.db.get_value(CHILD_DOCTYPE, item_id, ["link_id", "recipe_name"], as_dict=True)
    if not row or not row.link_id:
        return {"completed": False, "msg": ""}
    cook_wo = frappe.db.get_value("Work Order",
        {"custom_link_id": row.link_id, "custom_item_type": "Cook", "docstatus": ["<", 2]},
        "name")
    if not cook_wo:
        return {"completed": False, "msg": ""}
    status = frappe.db.get_value("Work Order", cook_wo, "status")
    if status == "Completed":
        return {"completed": True,
                "msg": _("🛑 Cannot change recipe for <b>{0}</b>. The Cook Work Order {1} is already <b>Completed</b>.")
                .format(row.recipe_name, cook_wo)}
    return {"completed": False, "msg": ""}


@frappe.whitelist()
def check_pack_wo_completed(item_id):
    """Pre-check if any Pack WO is Completed before allowing pack change."""
    row = frappe.db.get_value(CHILD_DOCTYPE, item_id, ["link_id", "recipe_name"], as_dict=True)
    if not row or not row.link_id:
        return {"completed": False, "msg": ""}
    pack_wos = frappe.get_all("Work Order",
        filters={"custom_link_id": row.link_id, "custom_item_type": "Pack", "docstatus": ["<", 2]},
        fields=["name", "status"])
    completed = [w for w in pack_wos if w.status == "Completed"]
    if completed:
        return {"completed": True,
                "msg": _("🛑 Cannot change packs for <b>{0}</b>. Pack Work Order(s) {1} already <b>Completed</b>.")
                .format(row.recipe_name, ", ".join(w.name for w in completed))}
    return {"completed": False, "msg": ""}


@frappe.whitelist()
def cancel_item(item_id):
    """Cancel a production item row and queue WO cancellation.

    Phase 2a: Uses db.set_value instead of full DP load+save (~104q → ~3q).
    """
    row_data = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": item_id},
        ["name", "parent", "rq_status", "recipe_name", "recipe_cook_workstaion",
         "recipe_cook_round", "required_date", "produ_status"],
        as_dict=True,
    )
    if not row_data:
        return {"success": False, "message": "Item not found"}

    if row_data.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}

    dp_ref = frappe.db.get_value("Daily Production", row_data.parent, "custom_submit_ref")
    has_wo = bool(dp_ref)

    values = {"produ_status": "Cancelled"}
    if has_wo:
        values["rq_status"] = "Processing"

    frappe.db.set_value(CHILD_DOCTYPE, item_id, values)

    _log_schedule_change("Cancel", day=row_data.required_date, dp_name=row_data.parent,
                         child_row_name=item_id, recipe_name=row_data.recipe_name,
                         workstation=row_data.recipe_cook_workstaion,
                         cook_round=row_data.recipe_cook_round,
                         old_data={"produ_status": row_data.produ_status},
                         new_data={"produ_status": "Cancelled"})

    frappe.db.commit()

    if has_wo:
        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_cancel_item",
            queue="long", timeout=600,
            item_id=item_id, dp_name=row_data.parent,
        )
        return {"success": True, "message": _("Cancellation queued")}

    return {"success": True, "message": _("Cancelled")}


@frappe.whitelist()
def clear_item(item_id):
    """Reset a production item row to a clean 'No Cooking' slot.

    Intended for rows that have no Work Orders (no mr_reference or no
    production_plane). Resets recipe, size, packs, status, notes and
    reference fields so the slot becomes an empty addable slot again.
    No WOs are cancelled here — the callers only show the button when
    no WOs exist.
    """
    row_data = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": item_id},
        ["name", "parent", "rq_status", "recipe_name", "recipe_cook_workstaion",
         "recipe_cook_round", "required_date", "produ_status"],
        as_dict=True,
    )
    if not row_data:
        return {"success": False, "message": "Item not found"}

    if row_data.rq_status == "Processing":
        return {"success": False, "message": "Work Orders are being processed. Please wait."}

    values = {
        "recipe_name": NO_COOKING,
        "size": 0,
        "produ_status": "",
        "number_of_pack": 0,
        "production_type": "",
        "urgent_check": 0,
        "recipe_note": "",
        "custom_yield": 0,
        "recipe_cook_time": None,
        "mr_reference": "",
        "wo_list": "",
        "wo_list_with_type": "",
        "production_plane": "",
        "custom_pair_id": "",
        "rq_status": "",
        "custom_wo_error": "",
    }
    for i in range(1, 8):
        suffix = "" if i == 1 else f"_{i}"
        values[f"pack_name{suffix}"] = None
        values[f"pack_qty{suffix}"] = 0
        values[f"pack_remark{suffix}"] = None

    frappe.db.set_value(CHILD_DOCTYPE, item_id, values)

    _log_schedule_change("Clear", day=row_data.required_date, dp_name=row_data.parent,
                         child_row_name=item_id, recipe_name=row_data.recipe_name,
                         workstation=row_data.recipe_cook_workstaion,
                         cook_round=row_data.recipe_cook_round,
                         old_data={"recipe_name": row_data.recipe_name,
                                   "produ_status": row_data.produ_status},
                         new_data={"recipe_name": NO_COOKING, "produ_status": ""})

    frappe.db.commit()
    return {"success": True, "message": _("Slot cleared")}


@frappe.whitelist()
def copy_item(source_id, target_id):
    """Copy a recipe slot's production data into an empty target slot.

    Used by the WhatsApp AI planner (copy_recipe_slot). Copies the data
    fields and sets produ_status = 'New Schedule'. The target keeps its
    own link_id / workstation / round; the source is left untouched.
    """
    src = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": source_id},
        ["name", "recipe_name", "size", "number_of_pack", "production_type",
         "urgent_check", "recipe_note", "recipe_cook_time", "custom_yield"],
        as_dict=True,
    )
    if not src or not src.recipe_name or src.recipe_name == NO_COOKING:
        return {"success": False, "message": _("Source slot has no recipe to copy")}

    tgt = frappe.db.get_value(
        CHILD_DOCTYPE, {"name": target_id},
        ["name", "parent", "recipe_name", "rq_status", "recipe_cook_workstaion",
         "recipe_cook_round", "required_date"],
        as_dict=True,
    )
    if not tgt:
        return {"success": False, "message": _("Target slot not found")}
    if tgt.recipe_name != NO_COOKING:
        return {"success": False, "message": _("Target slot is not empty")}
    if tgt.rq_status == "Processing":
        return {"success": False, "message": _("Work Orders are being processed. Please wait.")}

    values = {
        "recipe_name": src.recipe_name,
        "size": src.size or 0,
        "number_of_pack": src.number_of_pack or 0,
        "production_type": src.production_type or "",
        "urgent_check": src.urgent_check or 0,
        "recipe_note": src.recipe_note or "",
        "recipe_cook_time": src.recipe_cook_time,
        "custom_yield": src.custom_yield or 0,
        "produ_status": "New Schedule",
    }
    for i in range(1, 8):
        suffix = "" if i == 1 else f"_{i}"
        values[f"pack_name{suffix}"] = src.get(f"pack_name{suffix}")
        values[f"pack_qty{suffix}"] = src.get(f"pack_qty{suffix}") or 0
        values[f"pack_remark{suffix}"] = src.get(f"pack_remark{suffix}")

    frappe.db.set_value(CHILD_DOCTYPE, target_id, values)

    _log_schedule_change("Add Recipe", day=tgt.required_date, dp_name=tgt.parent,
                         child_row_name=target_id, recipe_name=src.recipe_name,
                         workstation=tgt.recipe_cook_workstaion,
                         cook_round=tgt.recipe_cook_round,
                         old_data={"recipe_name": NO_COOKING},
                         new_data={"recipe_name": src.recipe_name,
                                   "size": src.size or 0,
                                   "produ_status": "New Schedule"})

    frappe.db.commit()
    return {"success": True, "message": _("Recipe copied")}


def _background_change_recipe(item_id, dp_name, new_recipe):
    """Background worker: reprocess WOs after recipe change via DP's process_recipe_change_or_size_change."""
    try:
        current = frappe.db.get_value(
            CHILD_DOCTYPE, item_id,
            ["produ_status", "mr_reference", "rq_status"], as_dict=True
        )
        if not current or current.produ_status != "Recipe Change" or not current.mr_reference:
            frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "")
            frappe.db.commit()
            return

        from caf.caf.doctype.daily_production.change_size import process_recipe_change_or_size_change

        for attempt in range(3):
            try:
                process_recipe_change_or_size_change(dp_name, CHILD_DOCTYPE)
                break
            except frappe.QueryDeadlockError:
                if attempt == 2:
                    raise
                time.sleep(0.5)

        processing_rows = frappe.get_all(CHILD_DOCTYPE,
            filters={"parent": dp_name, "rq_status": "Processing"},
            fields=["name"])
        for pr in processing_rows:
            frappe.db.set_value(CHILD_DOCTYPE, pr.name, "rq_status", "Done")
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="Background recipe change failed", message=frappe.get_traceback())
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "Failed")
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_error", _extract_friendly_error(e))
        frappe.db.commit()


def _background_cancel_item(item_id, dp_name):
    """Background worker: process cancellation and reset row to free the slot."""
    try:
        current = frappe.db.get_value(
            CHILD_DOCTYPE, item_id,
            ["produ_status", "rq_status"], as_dict=True
        )
        if not current or current.produ_status != "Cancelled":
            frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "")
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
            row.rq_status = ""
            for i in range(1, 8):
                suffix = "" if i == 1 else f"_{i}"
                row.set(f"pack_name{suffix}", None)
                row.set(f"pack_qty{suffix}", 0)
                row.set(f"pack_remark{suffix}", None)
            dp.flags.skip_edit_log = True
            dp.save(ignore_permissions=True)
            frappe.db.commit()
        else:
            frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "Done")
            frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="Background cancellation failed", message=frappe.get_traceback())
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "Failed")
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_error", _extract_friendly_error(e))
        frappe.db.commit()


def _background_pack_change(item_id, dp_name):
    """Background worker: cancel WOs for a pack-change row, reprocess, and recreate."""
    try:
        data = frappe.db.get_value(
            CHILD_DOCTYPE, item_id,
            ["rq_status", "produ_status"],
            as_dict=True,
        )
        if not data or data.rq_status != "Processing":
            return

        if not frappe.flags.custom_submit_ref:
            frappe.flags.custom_submit_ref = frappe.db.get_value("Daily Production", dp_name, "custom_submit_ref")

        from caf.caf.doctype.daily_production.change_pack import process_pack_change_or_add

        for attempt in range(3):
            try:
                process_pack_change_or_add(dp_name, CHILD_DOCTYPE)
                break
            except frappe.QueryDeadlockError:
                if attempt == 2:
                    raise
                time.sleep(0.5)

        # Mark ALL pack-change rows on this DP as Done (batch function processes all at once)
        processing_rows = frappe.get_all(
            CHILD_DOCTYPE,
            filters={"parent": dp_name, "rq_status": "Processing"},
            fields=["name"],
        )
        for r in processing_rows:
            frappe.db.set_value(CHILD_DOCTYPE, r.name, "rq_status", "Done")
            frappe.db.set_value(CHILD_DOCTYPE, r.name, "custom_wo_error", "")
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="Background pack change failed", message=frappe.get_traceback())
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "Failed")
        frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_error", _extract_friendly_error(e))
        frappe.db.commit()


def _background_swap_recipes(row_a_name, row_b_name):
    """Background worker: process WO swap, cancel, recreate for a Rearrange pair."""
    try:
        data_a = frappe.db.get_value(
            CHILD_DOCTYPE, row_a_name,
            ["parent", "rq_status", "mr_reference", "link_id", "recipe_name"],
            as_dict=True,
        )
        data_b = frappe.db.get_value(
            CHILD_DOCTYPE, row_b_name,
            ["parent", "rq_status", "mr_reference", "link_id", "recipe_name"],
            as_dict=True,
        )
        if (not data_a or not data_b or
            data_a.rq_status != "Processing" or data_b.rq_status != "Processing"):
            for name in [row_a_name, row_b_name]:
                cur = frappe.db.get_value(CHILD_DOCTYPE, name, "rq_status")
                if cur == "Processing":
                    frappe.db.set_value(CHILD_DOCTYPE, name, "rq_status", "")
            frappe.db.commit()
            return

        dp = frappe.get_doc("Daily Production", data_a.parent)
        row_a = next((r for r in dp.production_table if r.name == row_a_name), None)
        row_b = next((r for r in dp.production_table if r.name == row_b_name), None)
        if not row_a or not row_b:
            for name in [row_a_name, row_b_name]:
                frappe.db.set_value(CHILD_DOCTYPE, name, "rq_status", "")
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

        for attempt in range(3):
            try:
                _swap_db_link_ids(row_a.link_id, row_b.link_id)

                _cancel_cook_pack_by_id(row_a.link_id)
                _cancel_cook_pack_by_id(row_b.link_id)

                start_time = now_datetime()
                new_wos_a = dp.recreate_mr_after_update_slot(row_a.recipe_name, [row_a])
                new_wos_b = dp.recreate_mr_after_update_slot(row_b.recipe_name, [row_b])

                _cleanup_redundant_wips(new_wos_a, row_a, CHILD_DOCTYPE, start_time)
                _cleanup_redundant_wips(new_wos_b, row_b, CHILD_DOCTYPE, start_time)

                new_cook_a = get_wo_by_type(row_a.link_id, "Cook")
                new_cook_b = get_wo_by_type(row_b.link_id, "Cook")

                if new_cook_a:
                    _relink_quality_docs(qual_b, new_cook_a)
                if new_cook_b:
                    _relink_quality_docs(qual_a, new_cook_b)
                break
            except frappe.QueryDeadlockError:
                if attempt == 2:
                    raise
                time.sleep(0.5)

        frappe.db.set_value(CHILD_DOCTYPE, row_a_name, "rq_status", "Done")
        frappe.db.set_value(CHILD_DOCTYPE, row_b_name, "rq_status", "Done")
        frappe.db.set_value(CHILD_DOCTYPE, row_a_name, "produ_status", "")
        frappe.db.set_value(CHILD_DOCTYPE, row_b_name, "produ_status", "")
        frappe.db.set_value(CHILD_DOCTYPE, row_a_name, "custom_pair_id", "")
        frappe.db.set_value(CHILD_DOCTYPE, row_b_name, "custom_pair_id", "")
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="Background swap recipes failed", message=frappe.get_traceback())
        for name in [row_a_name, row_b_name]:
            frappe.db.set_value(CHILD_DOCTYPE, name, "rq_status", "Failed")
            frappe.db.set_value(CHILD_DOCTYPE, name, "custom_wo_error", _extract_friendly_error(e))
        frappe.db.commit()


def _background_move_wo_migration(dp_name):
    """Background worker: process ALL Change Slot WO migrations for a DP at once."""
    processing_rows = []
    try:
        from caf.caf.doctype.daily_production.rearrange_and_change_slot import (
            _cancel_cook_pack_by_id,
            _relink_quality_docs,
            _cleanup_redundant_wips,
            _get_quality_data_by_id,
        )
        from caf.caf.doctype.daily_production.wo_helpers import get_wo_by_type
        from frappe.utils import now_datetime

        # Find ALL Processing rows for this DP (handles multiple concurrent moves)
        processing_rows = frappe.get_all(
            CHILD_DOCTYPE,
            filters={"parent": dp_name, "rq_status": "Processing"},
            fields=["name", "recipe_name", "link_id", "mr_reference", "custom_pair_id"],
        )
        if not processing_rows:
            return

        dp = frappe.get_doc("Daily Production", dp_name)
        start_time = now_datetime()

        for pr_data in processing_rows:
            row = next((r for r in dp.production_table if r.name == pr_data.name), None)
            if not row:
                frappe.db.set_value(CHILD_DOCTYPE, pr_data.name, "rq_status", "Done")
                continue
            if row.recipe_name == NO_COOKING:
                frappe.db.set_value(CHILD_DOCTYPE, pr_data.name, "rq_status", "Done")
                continue

            quality_data = _get_quality_data_by_id(pr_data.link_id)

            for attempt in range(3):
                try:
                    if pr_data.mr_reference:
                        _cancel_cook_pack_by_id(row.link_id)

                    new_wos = dp.recreate_mr_after_update_slot(
                        row.recipe_name, [row]
                    )
                    _cleanup_redundant_wips(new_wos, row, CHILD_DOCTYPE, start_time)

                    if pr_data.mr_reference:
                        new_cook_wo = get_wo_by_type(row.link_id, "Cook")
                        if new_cook_wo:
                            _relink_quality_docs(quality_data, new_cook_wo)
                    break
                except frappe.QueryDeadlockError:
                    if attempt == 2:
                        raise
                    time.sleep(0.5)

            frappe.db.set_value(CHILD_DOCTYPE, pr_data.name, "rq_status", "Done")

            # Clear paired NC row status
            if pr_data.custom_pair_id:
                pair_rows = frappe.get_all(
                    CHILD_DOCTYPE,
                    filters={"parent": dp_name, "custom_pair_id": pr_data.custom_pair_id},
                    fields=["name"],
                )
                for ppr in pair_rows:
                    frappe.db.set_value(CHILD_DOCTYPE, ppr.name, "produ_status", "")
                    frappe.db.set_value(CHILD_DOCTYPE, ppr.name, "custom_pair_id", "")
                    frappe.db.set_value(CHILD_DOCTYPE, ppr.name, "rq_status", "Done")

            frappe.db.set_value(CHILD_DOCTYPE, pr_data.name, "custom_pair_id", "")

        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="Background move WO migration failed", message=frappe.get_traceback())
        # Mark all Processing rows as Failed
        for pr_data in processing_rows:
            frappe.db.set_value(CHILD_DOCTYPE, pr_data.name, "rq_status", "Failed")
            frappe.db.set_value(CHILD_DOCTYPE, pr_data.name, "custom_wo_error", _extract_friendly_error(e))
        frappe.db.commit()


def _extract_friendly_error(exc):
    """Extract a user-friendly error message from an exception.

    - frappe.ValidationError → the message the user should see
    - Other exceptions → generic message (full traceback still goes to Error Log)
    """
    msg = str(exc).strip()
    if isinstance(exc, frappe.ValidationError) and msg:
        return msg
    return "An unexpected error occurred. Please check the Error Log for details."


def _background_create_mr(row_name, dp_name):
    """Background worker: create MR + WOs for a single New Schedule row."""
    try:
        current = frappe.db.get_value(
            CHILD_DOCTYPE, row_name, ["produ_status", "rq_status"], as_dict=True
        )
        if not current or current.produ_status != "New Schedule":
            if current:
                frappe.db.set_value(CHILD_DOCTYPE, row_name, "rq_status", "")
                frappe.db.commit()
            return

        dp = frappe.get_doc("Daily Production", dp_name)
        row = next((r for r in dp.production_table if r.name == row_name), None)
        if not row or row.produ_status != "New Schedule":
            frappe.db.set_value(CHILD_DOCTYPE, row_name, "rq_status", "")
            frappe.db.commit()
            return

        final = frappe.db.get_value(CHILD_DOCTYPE, row_name, "produ_status")
        if final != "New Schedule":
            frappe.db.set_value(CHILD_DOCTYPE, row_name, "rq_status", "")
            frappe.db.commit()
            return

        for attempt in range(3):
            try:
                dp._process_new_schedules()
                break
            except frappe.QueryDeadlockError:
                if attempt == 2:
                    raise
                time.sleep(0.5)

        frappe.db.set_value(CHILD_DOCTYPE, row_name, "rq_status", "Done")
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="Background MR creation failed", message=frappe.get_traceback())
        frappe.db.set_value(CHILD_DOCTYPE, row_name, "rq_status", "Failed")
        frappe.db.set_value(CHILD_DOCTYPE, row_name, "custom_wo_error", _extract_friendly_error(e))
        frappe.db.commit()


@frappe.whitelist()
def process_dp_updates(item_id):
    """Enqueue process_manual_updates on the parent DP in the background."""
    dp_name = frappe.db.get_value(CHILD_DOCTYPE, {"name": item_id}, "parent")
    if not dp_name:
        return {"success": False, "message": "Item not found"}

    dp = frappe.get_doc("Daily Production", dp_name)

    for row in dp.production_table:
        if row.recipe_name != NO_COOKING and row.rq_status == "Processing":
            return {"success": False, "message": "Work Orders are being processed. Please wait."}

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
    """Set rq_status on every row in the DP."""
    for row in dp.production_table:
        if row.recipe_name != NO_COOKING:
            row.rq_status = status


def _background_process_dp(dp_name):
    """Background worker: runs process_manual_updates and updates row status."""
    try:
        dp = frappe.get_doc("Daily Production", dp_name)
        dp.process_manual_updates()
        _set_rows_wo_status(dp, "Done")
        dp.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="Background DP processing failed", message=frappe.get_traceback())
        friendly = _extract_friendly_error(e)
        try:
            dp = frappe.get_doc("Daily Production", dp_name)
            for row in dp.production_table:
                if row.recipe_name != NO_COOKING and row.produ_status:
                    frappe.db.set_value(CHILD_DOCTYPE, row.name, "rq_status", "Failed")
                    frappe.db.set_value(CHILD_DOCTYPE, row.name, "custom_wo_error", friendly)
            frappe.db.commit()
        except Exception:
            pass
        frappe.db.commit()


@frappe.whitelist()
def get_row_error(item_id):
    """Return the stored error message for a failed row."""
    err = frappe.db.get_value(CHILD_DOCTYPE, item_id, "custom_wo_error")
    return {"error": err or ""}


@frappe.whitelist()
def retry_failed_row(item_id):
    """Reset a failed row and re-enqueue the appropriate background worker.

    For "Processing" rows, only allows retry if the row hasn't been updated
    in the last 10 minutes (job likely stuck/no longer running).
    """
    row_data = frappe.db.get_value(
        CHILD_DOCTYPE, item_id,
        ["parent", "produ_status", "rq_status", "recipe_name",
         "link_id", "mr_reference", "recipe_cook_workstaion", "recipe_cook_round",
         "modified"],
        as_dict=True,
    )
    if not row_data:
        return {"success": False, "message": "Row not found"}
    if row_data.rq_status not in ("Failed", "Processing"):
        return {"success": False, "message": "Row is not in a retryable state"}

    if row_data.rq_status == "Processing":
        from frappe.utils import now_datetime, time_diff_in_seconds
        elapsed = time_diff_in_seconds(now_datetime(), row_data.modified)
        if elapsed < 600:
            return {"success": False, "message": "Work Orders are still being processed. Please wait."}

    dp_name = row_data.parent
    dp = frappe.get_doc("Daily Production", dp_name)

    frappe.db.set_value(CHILD_DOCTYPE, item_id, "rq_status", "Processing")
    frappe.db.set_value(CHILD_DOCTYPE, item_id, "custom_wo_error", "")
    frappe.db.commit()

    status = row_data.produ_status

    if status == "New Schedule":
        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_create_mr",
            queue="long", timeout=600,
            row_name=item_id, dp_name=dp_name,
        )
    elif status == "Recipe Change":
        recipe = row_data.recipe_name
        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_change_recipe",
            queue="long", timeout=600,
            item_id=item_id, dp_name=dp_name, new_recipe=recipe,
        )
    elif status == "Cancelled":
        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_cancel_item",
            queue="long", timeout=600,
            item_id=item_id, dp_name=dp_name,
        )
    elif status in ("Change Slot", "Rearrange"):
        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_move_wo_migration",
            queue="long", timeout=600,
            dp_name=dp_name,
        )
    elif status == "Pack Change":
        frappe.enqueue(
            "caf.caf.page.production_schedule.production_schedule._background_pack_change",
            queue="long", timeout=600,
            item_id=item_id, dp_name=dp_name,
        )
    else:
        return {"success": False, "message": f"Cannot retry status: {status}"}

    return {"success": True, "message": "Retrying..."}


@frappe.whitelist()
def get_schedule_logs(year, week_number):
    """Return all Schedule Change Log entries for a given week, newest first."""
    monday = _iso_week_to_monday(year, week_number)
    sunday = monday + datetime.timedelta(days=6)

    logs = frappe.get_all(
        "Schedule Change Log",
        filters={"day": ["between", [str(monday), str(sunday)]]},
        fields=["name", "change_datetime", "changed_by", "action_type",
                "day", "workstation", "cook_round", "recipe_name",
                "dp_name", "summary", "changes_json"],
        order_by="change_datetime desc",
        limit_page_length=200,
    )
    return logs
