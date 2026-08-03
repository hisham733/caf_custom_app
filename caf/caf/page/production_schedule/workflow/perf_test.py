#!/usr/bin/env python3
"""
Performance Test Script — Before/After Refactoring Measurement

Usage:
    bench --site development.localhost execute caf.caf.page.production_schedule.workflow.perf_test.perf_test
"""

import frappe
import time
import json
from datetime import date, timedelta


# Enable query logging inline
try:
    frappe.flags.in_test = True
except Exception:
    pass


def _get_query_count():
    """Count currently logged queries across all methods."""
    total = 0
    if hasattr(frappe.local, "logged_queries"):
        total = len(frappe.local.logged_queries)
    if hasattr(frappe.local, "_queries"):
        total = len(frappe.local._queries)
    if hasattr(frappe, "db") and hasattr(frappe.db, "sql_log"):
        total = len(frappe.db.sql_log)
    # As last resort, use mysql status
    if total == 0:
        try:
            rows = frappe.db.sql("SHOW STATUS LIKE 'Questions'")
            total = int(rows[0][1]) if rows else 0
        except Exception:
            pass
    return total


def measure(label, fn, *args, **kwargs):
    """Run fn, measure time, print result."""
    # Use DB-level question counter as baseline
    base_questions = 0
    try:
        rows = frappe.db.sql("SHOW STATUS LIKE 'Questions'", auto_commit=False)
        base_questions = int(rows[0][1]) if rows else 0
    except Exception:
        pass

    t0 = time.time()
    result = None
    error = None
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        error = str(e)
    elapsed = time.time() - t0

    # Get question delta
    qc = 0
    try:
        rows = frappe.db.sql("SHOW STATUS LIKE 'Questions'", auto_commit=False)
        qc = int(rows[0][1]) - base_questions if rows else 0
    except Exception:
        pass

    status = "OK" if not error else "ERR"
    msg = f"  {label}: {elapsed:.3f}s | ~{qc} queries | {status}"
    if error:
        # Truncate error message
        short = error[:100].replace("\n", " ")
        msg += f" — {short}"
    print(msg)
    return {"label": label, "time": elapsed, "queries": qc, "error": error, "result": result}


def _get_monday():
    today = date.today()
    return today - timedelta(days=today.weekday())


def _get_week_number():
    today = date.today()
    return today.isocalendar()[1]


def _find_valid_row(dp, status_ok=None):
    """Find a row that passes weight validation (has sensible pack data)."""
    for r in dp.production_table:
        if not r.recipe_name or r.recipe_name == "No Cooking":
            continue
        if status_ok and r.produ_status not in status_ok:
            continue
        # Check if pack data looks reasonable
        nop = int(r.number_of_pack or 0)
        if nop <= 0:
            continue
        has_packs = any(r.get(f"pack_name{'' if i == 1 else f'_{i}'}") for i in range(1, nop + 1))
        if not has_packs:
            continue
        return r
    return None


def run_all():
    print("\n" + "=" * 60)
    print("PERFORMANCE BENCHMARK — Production Schedule")
    print("=" * 60)

    monday = _get_monday()
    year = date.today().year
    week_number = _get_week_number()

    # --- Scenario 1: Page Load ---
    print("\n[1] Page Load — get_week_data")
    try:
        from caf.caf.page.production_schedule.production_schedule import get_week_data
        measure("get_week_data", get_week_data, year, week_number, "Edit Schedule")
    except Exception as e:
        print(f"  SKIP: {e}")

    # --- Find test data ---
    dp, row = None, None
    for i in range(6):
        d = monday + timedelta(days=i)
        name = frappe.db.get_value("Daily Production", {"required_by": str(d)}, "name")
        if name:
            dp = frappe.get_doc("Daily Production", name)
            row = _find_valid_row(dp)
            if row:
                break

    if not dp:
        from caf.caf.doctype.daily_production.daily_production import create_empty_dp_week
        create_empty_dp_week(str(monday))
        for i in range(6):
            d = monday + timedelta(days=i)
            name = frappe.db.get_value("Daily Production", {"required_by": str(d)}, "name")
            if name:
                dp = frappe.get_doc("Daily Production", name)
                row = _find_valid_row(dp)
                if row:
                    break

    if not dp or not row:
        print("  ❌  No testable DP found — skipping remaining tests")
        print("\n" + "=" * 60 + "\n")
        return

    print(f"  Using DP: {dp.name} | Row: {row.name} ({row.recipe_name})")

    # --- Scenario 2: Save one field ---
    print("\n[2] Single Edit — save_item_fields")
    try:
        from caf.caf.page.production_schedule.production_schedule import save_item_fields
        old_note = row.recipe_note or ""
        # fields is a JSON string of [{field, value}] list
        fields_data = json.dumps([{"field": "recipe_note", "value": "perf_test_" + str(int(time.time()))}])
        measure("save_item_fields", save_item_fields, item_id=row.name, fields=fields_data)
        frappe.db.set_value("Create ProExl Items", row.name, "recipe_note", old_note)
    except Exception as e:
        print(f"  SKIP: {e}")

    # --- Scenario 3: Cancel a recipe ---
    print("\n[3] Cancel — cancel_item")
    try:
        from caf.caf.page.production_schedule.production_schedule import cancel_item
        cr = None
        for r in dp.production_table:
            if r.recipe_name and r.recipe_name != "No Cooking" and r.mr_reference and r.produ_status != "Cancelled":
                cr = r
                break
        if cr:
            old_status = cr.produ_status
            measure("cancel_item", cancel_item, item_id=cr.name)
            frappe.db.set_value("Create ProExl Items", cr.name, "produ_status", old_status or "")
        else:
            print("  SKIP: no row with MR reference")
    except Exception as e:
        print(f"  SKIP: {e}")

    # --- Scenario 4: Swap two recipes ---
    print("\n[4] Swap — swap_recipes")
    try:
        from caf.caf.page.production_schedule.production_schedule import swap_recipes
        cook = [r for r in dp.production_table if r.recipe_name and r.recipe_name != "No Cooking"]
        if len(cook) >= 2:
            measure("swap_recipes", swap_recipes, source_id=cook[0].name, target_id=cook[1].name)
            measure("swap_recipes_restore", swap_recipes, source_id=cook[0].name, target_id=cook[1].name)
        else:
            print("  SKIP: need 2 cook rows")
    except Exception as e:
        print(f"  SKIP: {e}")

    # --- Scenario 5: Add recipe ---
    print("\n[5] Add Recipe — add_recipe")
    try:
        from caf.caf.page.production_schedule.production_schedule import add_recipe
        no_cook = [r for r in dp.production_table if not r.recipe_name or r.recipe_name == "No Cooking"]
        _cook_rows = [r for r in dp.production_table if r.recipe_name and r.recipe_name != "No Cooking"]
        if no_cook and _cook_rows:
            target = no_cook[0]
            recipe = _cook_rows[0].recipe_name
            pack_name = frappe.db.sql("""
                SELECT DISTINCT bom.item
                FROM `tabBOM` AS bom
                INNER JOIN `tabBOM Item` AS bom_item ON bom_item.parent = bom.name
                WHERE bom_item.item_code = %s
                  AND bom.is_active = 1 AND bom.docstatus = 1
                LIMIT 1
            """, recipe)
            pack = pack_name[0][0] if pack_name else None
            measure("add_recipe", add_recipe,
                    day=str(dp.required_by), recipe=recipe, size=10,
                    cooker=target.recipe_cook_workstaion, pack_count=1,
                    round_num=target.recipe_cook_round,
                    pack_name=pack or "")
            frappe.db.set_value("Create ProExl Items", target.name, "recipe_name", "No Cooking")
            frappe.db.set_value("Create ProExl Items", target.name, "size", 0)
        else:
            print("  SKIP: need no-cook slot and a recipe")
    except Exception as e:
        print(f"  SKIP: {e}")

    # --- Scenario 6: WO pipeline (clean) ---
    print("\n[6] WO Creation — process_manual_updates (New Schedule)")
    try:
        # Find a Submitted DP with empty custom_submit_ref (not null, empty string)
        dp6_name = frappe.db.get_value("Daily Production",
            {"workflow_state": "Submitted", "custom_submit_ref": "", "docstatus": 0},
            "name")
        if not dp6_name:
            # Find a draft DP, submit it
            for i in range(6):
                d = monday + timedelta(days=i)
                name = frappe.db.get_value("Daily Production",
                    {"required_by": str(d), "docstatus": 0, "workflow_state": ("in", ["", "Draft"])},
                    "name")
                if name:
                    ddp = frappe.get_doc("Daily Production", name)
                    if not ddp.custom_submit_ref:
                        ddp.workflow_state = "Submitted"
                        # Ensure at least one row has valid pack data for WO creation
                        for r6 in ddp.production_table:
                            if r6.recipe_name and r6.recipe_name != "No Cooking":
                                if int(r6.size or 0) <= 0:
                                    r6.size = 10
                                if int(r6.number_of_pack or 0) <= 0:
                                    r6.number_of_pack = 1
                        ddp.save(ignore_permissions=True)
                        dp6_name = name
                        break

        if dp6_name:
            dp6 = frappe.get_doc("Daily Production", dp6_name)
            if not dp6.custom_submit_ref and dp6.workflow_state == "Submitted":
                for r6 in dp6.production_table:
                    if r6.recipe_name and r6.recipe_name != "No Cooking" and not r6.produ_status:
                        frappe.db.set_value("Create ProExl Items", r6.name, "produ_status", "New Schedule")
                        if int(r6.size or 0) <= 0:
                            frappe.db.set_value("Create ProExl Items", r6.name, "size", 10)
                        if int(r6.number_of_pack or 0) <= 0:
                            frappe.db.set_value("Create ProExl Items", r6.name, "number_of_pack", 1)
                        break
                dp6.reload()
                measure("process_manual_updates", dp6.process_manual_updates)
            else:
                print("  SKIP: WOs already exist or not Submitted")
        else:
            print("  SKIP: no suitable DP found")
    except Exception as e:
        print(f"  SKIP: {e}")

    # --- Scenario 7: WO pipeline (with changes) ---
    print("\n[7] WO Creation — process_manual_updates (Recipe Change)")
    try:
        # Find Submitted DP with existing WOs (custom_submit_ref is not empty)
        dp7_name = frappe.db.get_value("Daily Production",
            {"workflow_state": "Submitted", "custom_submit_ref": ("!=", ""), "docstatus": 0},
            "name", order_by="creation desc")

        if dp7_name:
            dp7 = frappe.get_doc("Daily Production", dp7_name)
            changed = 0
            for r7 in dp7.production_table:
                if r7.recipe_name and r7.recipe_name != "No Cooking" and changed < 3:
                    if r7.produ_status not in ("Processing", "Done", "Cancelled"):
                        frappe.db.set_value("Create ProExl Items", r7.name, "produ_status", "Only Remark")
                        frappe.db.set_value("Create ProExl Items", r7.name, "recipe_note", "perf_test")
                        changed += 1
            if changed:
                dp7.reload()
                measure("process_manual_updates", dp7.process_manual_updates)
            else:
                print("  SKIP: no rows available")
        else:
            print("  SKIP: no DP with WOs found")
    except Exception as e:
        print(f"  SKIP: {e}")

    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    print("=" * 60 + "\n")


@frappe.whitelist()
def perf_test():
    """Entry point for bench execute."""
    run_all()
