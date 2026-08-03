# 06 — Status Workflows (Complete Reference)

Exact flow for each `produ_status` — from user click to `tabWork Order` rows in the DB.
Each status includes a **call tree** showing every function and its purpose.

> **Last updated:** 2027-01-18 — Auto-clearing rules, Cook/Pack pre-checks, Cancelled/Single WO hidden

---

## Function Glossary

| Function | File | Line | Purpose |
|----------|------|------|---------|
| `_show_edit_dialog` | production_schedule.js | ~1286 | Opens dialog to edit an existing recipe slot |
| `_show_add_dialog` | production_schedule.js | ~1767 | Opens dialog to add a new recipe |
| `_save_item_fields` | production_schedule.js | ~1600 | Saves field changes to the child row |
| `_handle_drop` | production_schedule.js | ~1128 | Handles drag-and-drop events |
| `_do_move_item` | production_schedule.js | ~1222 | Moves a recipe to an empty slot |
| `_swap_recipes` | production_schedule.js | ~1207 | Swaps two recipe slots |
| `_submit_week` | production_schedule.js | ~2421 | User clicks Submit Week button |
| `_create_work_order_for_day` | production_schedule.js | ~2562 | User clicks Create WO in View mode |
| `_show_add_rounds_dialog` | production_schedule.js | ~2422 | Add extra rounds to a day's DP |
| `add_recipe` | production_schedule.py | ~990 | Add new recipe to draft DP |
| `save_item_fields` | production_schedule.py | ~710 | Save field changes to child row |
| `save_move_item` | production_schedule.py | ~356 | Move recipe between slots (drag-drop) |
| `swap_recipes` | production_schedule.py | ~1026 | Swap two recipes |
| `process_recipe_change` | production_schedule.py | ~1572 | Enqueue recipe change bg job with Cook WO check |
| `process_pack_change` | production_schedule.py | ~1617 | Enqueue pack change bg job with Pack WO check |
| `cancel_item` | production_schedule.py | ~1667 | Enqueue cancellation bg job |
| `check_cook_wo_completed` | production_schedule.py | ~1648 | Pre-check: is Cook WO Completed? (blocks save) |
| `check_pack_wo_completed` | production_schedule.py | ~1669 | Pre-check: is any Pack WO Completed? (blocks save) |
| `submit_week` | production_schedule.py | ~841 | Submit all draft DPs for a week |
| `edit_week` | production_schedule.py | ~908 | Switch DPs to Edit mode (sets workflow_state="Draft") |
| `process_day_dp` | production_schedule.py | ~777 | Create WOs for a day in View mode |
| `get_template_round_config` | daily_production.py | ~1611 | Returns default_rounds + max_rounds from template |
| `add_extra_round` | daily_production.py | ~1530 | Add extra round rows to a DP |
| `onload` | daily_production.py | ~69 | Sets workflow_state="Draft" if falsy |
| `validate` | daily_production.py | ~42 | Validates rows, sets workflow_state="Draft" if falsy |
| `_assign_link_id` | daily_production.py | ~140 | Assign R-YYYY-##### to rows without one |
| `_fill_missing_slots` | daily_production.py | ~145 | Create No Cooking placeholder rows for all slots |
| `submit_dp` | daily_production.py | ~1643 | Sets workflow_state="Submitted" only (docstatus stays 0) |
| `process_manual_updates` | daily_production.py | ~303 | 9-step orchestrator: process all pending changes |
| `_process_new_schedules` | daily_production.py | ~301 | Create MRs for New Schedule rows |
| `create_material_request` | daily_production.py | ~356 | Create MR with recipe + pack items |
| `recreate_mr_after_update_slot` | daily_production.py | ~389 | Detach old MR, create new MR (with existing link_id) |
| `_cancel_work_orders_by_id` | cancellation.py | ~194 | Cancel ALL WOs (Cook+Pack+WIP) by link_id |
| `_cancel_cook_pack_by_id` (rearrange) | rearrange_and_change_slot.py | ~92 | Cancel Cook+Pack WOs by link_id |
| `_cancel_cook_pack_by_id` (change_pack) | change_pack.py | ~78 | Cancel Pack WOs; cleans Job Cards + Stock Entries first |
| `process_recipe_change_or_size_change` | change_size.py | ~79 | Recipe Change: cancel old WOs → create new MR+WOs |
| `process_pack_change_or_add` | change_pack.py | ~9 | Pack Change: cancel old Pack → create new Pack |
| `process_cancellations` | cancellation.py | ~337 | Cancel all WOs for Cancelled rows |
| `_cleanup_redundant_wips` | rearrange_and_change_slot.py | ~130 | Delete new WIP WOs (Draft+Submitted) |
| `_cleanup_everything_except_new_pack` | change_pack.py | ~152 | Delete new Cook+WIP, keep only new Pack |
| `_migrate_db_link_ids` | rearrange_and_change_slot.py | ~68 | One-way WO migration: UPDATE WOs old→new link_id |
| `_swap_db_link_ids` | rearrange_and_change_slot.py | ~23 | Two-way WO swap with temp ID |
| `_relink_quality_docs` | rearrange_and_change_slot.py | ~125 | Reassign Quality Reviews/Weight Records |
| `_get_quality_data_by_id` | rearrange_and_change_slot.py | ~115 | Backup Quality Reviews + Weight Records |
| `_write_back_to_row` | daily_production.py | ~528 | Write MR reference + WO list to child row |
| `_write_back_to_row_additive` | daily_production.py | ~580 | Merge new WOs with existing, purge cancelled |

---

## Workflow State (NOT Produ Status)

Daily Production uses `workflow_state` (not `docstatus`) for mode toggling:

| Mode | workflow_state | docstatus |
|------|---------------|-----------|
| **Draft** (Edit) | `"Draft"` | 0 |
| **Submitted** (View) | `"Submitted"` | 0 |

- `submit_dp()` sets `workflow_state="Submitted"`, docstatus stays 0
- `edit_week()` flips `workflow_state="Draft"` (was `""`, changed to "Draft" to prevent `WorkflowStateError`)
- `onload()` and `validate()` ensure `workflow_state` is never falsy
- No Workflow document exists — `track_changes: 1` only

---

## Status Auto-Clearing Rules

| Status | Auto-Cleared? | When |
|--------|-------------|------|
| **New Schedule** | ❌ Kept | Status visible after processing |
| **Recipe Change** | ❌ Kept | Status visible after processing |
| **Pack Change** | ❌ Kept | Status visible after processing |
| **Cancelled** | ✅ Cleared (slot reset) | Row becomes No Cooking |
| **Change Slot** | ✅ Cleared | Both rows cleared after migration |
| **Rearrange** | ✅ Cleared | Both rows cleared after swap |
| **Only Remark** | ❌ Kept | Status visible — user can see remark was applied |
| **Single WO** | ❌ Hidden | Removed from dropdown entirely |

**Create WO button**: Clears ALL produ_status values after success (single SQL UPDATE).

---

## Cook/Pack WO Pre-Check (NEW)

Before saving Recipe Change or Pack Change, a **pre-check** fires:

| Trigger | Check | Blocks Save |
|---------|-------|-------------|
| Status dropdown → "Recipe Change" | `check_cook_wo_completed` | ❌ Warnings only |
| Status dropdown → "Pack Change" | `check_pack_wo_completed` | ❌ Warnings only |
| Save button (Recipe Change + link_id) | `check_cook_wo_completed` | ✅ Blocks save |
| Save button (Pack Change + link_id) | `check_pack_wo_completed` | ✅ Blocks save |

The dropdown check fires immediately when the user selects the status (warning message).
The save check fires when the user clicks Save — if WO is Completed, **save is blocked entirely**, dialog stays open.

---

## 1. New Schedule

### Purpose
User adds a brand-new recipe to a slot. No old WOs exist. Creates MR + WOs from scratch.

### Status Dropdown Options
- No Cooking / empty slot: "New Schedule"
- Recipe set, no WOs: "New Schedule", "Recipe Change"
- Recipe set, has WOs: "Recipe Change", "Only Remark", "Pack Change"

### Call Tree

```
User clicks "+" on empty slot
│
├── JS: _show_add_dialog (::1767)          ◄── Builds add dialog with recipe/size/pack fields
│   └── _on_recipe_change (::2159)         ◄── Fetches BOM data (yield, raw_materials) when recipe changes
│       └── get_recipe_bom_data (.py:1304)  ◄── Reads BOM.custom_yield + BOM.custom_raw_materails
│   └── _validate_pack_weights (::2232)    ◄── Real-time check: total_input vs pack quantities
│
├── PY: add_recipe (.py:875)               ◄── Endpoint: writes recipe data to child row
│   │
│   ├── find_draft_dp(day)                 ◄── Gets latest draft DP for this day
│   ├── find_slot(ws, round)               ◄── Finds "No Cooking" row at target slot
│   │   └── Guard: slot must exist + be No Cooking
│   ├── Guard: rq_status != Processing     ◄── Blocks if bg job running on this row
│   ├── Overwrite row fields               ◄── recipe_name, size, packs, produ_status="New Schedule"
│   │
│   └── dp.save()                          ◄── Persists all 64 rows to DB
│       ├── before_save (.py:179)
│       │   ├── _assign_link_id (::140)    ◄── Assigns R-YYYY-##### to any row missing one
│       │   └── _fill_missing_slots (::145)◄── Creates "No Cooking" rows for all unused slots
│       └── DB: INSERT/UPDATE tabCreate ProExl Items
│
│   (if dp.custom_submit_ref is set → create WOs NOW)
│   └── enqueue _background_create_mr       ◄── Pushes to Redis "long" queue
│
└── (later, when submitted + Create WO clicked)
    │
    ├── JS: _create_work_order_for_day (::2562)  ◄── Per-day button in View mode
    │
    ├── PY: process_day_dp (.py:777)        ◄── Endpoint: trigger WO creation for a day
    │   └── dp.process_manual_updates()     ◄── 9-step orchestrator
    │       │
    │       └── Step 8: _process_new_schedules (DP::301)
    │           │
    │           └── create_material_request (DP::356)
    │               │
    │               ├── _build_mr_header     ◄── Sets MR type=Manufacture, link_id, batch_size
    │               ├── _append_pack_items   ◄── Adds each pack_name to MR items with qty
    │               ├── _append_recipe_row   ◄── Adds recipe to MR custom_recipe_table
    │               │
    │               ├── mr.insert()          ◄── Frappe validates + saves MR
    │               ├── mr.submit()          ◄── Submits MR
    │               │   └── Frappe auto-creates:
    │               │       ├── Production Plan
    │               │       └── PP.submit() → Work Orders
    │               │           ├── Cook WO    (recipe item)
    │               │           ├── Pack WO × N (pack items)
    │               │           └── WIP WO × N  (intermediate BOM steps)
    │               │
    │               └── _write_back_to_row   ◄── Updates child row: mr_reference, wo_list
    │
    └── rq_status = "Done"                  ◄── JS detects → board refreshes
```

### Key Details
- **Auto-fill:** `_fill_missing_slots` creates "No Cooking" rows for ALL workstation/round combos from the Master Template. Every slot gets a row + link_id on first save.
- **WIP Handling:** WIP persists. Only `Reheat` type removes WIP via `remove_all_wip_wo`.
- **Draft DPs:** If no `custom_submit_ref` on DP, recipe saves without creating WOs. WOs are created later when submitted + Create WO clicked.
- **After Create WO:** All produ_status values cleared (single SQL UPDATE).

---

## 2. Recipe Change

### Purpose
User changes recipe/size/packs on a row that already has WOs. Old WOs cancelled, new WOs created. Quality data preserved and relinked.

### ⚠️ Pre-Check
Before saving, `check_cook_wo_completed` verifies the Cook WO is NOT Completed. If it is, save is **blocked** and error message shown.

### Call Tree

```
User selects "Recipe Change" in status dropdown
│
├── JS: status change handler               ◄── Fires check_cook_wo_completed immediately
│   └── If Completed → frappe.msgprint("🛑 Cannot change recipe...")
│   └── Guard: d._wo_checked prevents duplicate fires
│
User edits recipe → changes recipe/size/packs → Save
│
├── JS: primary_action PRE-CHECK
│   └── check_cook_wo_completed (async:false)
│       ├── If Completed → frappe.msgprint → return (SAVE BLOCKED)
│       └── If OK → _do_save() → proceeds
│
├── JS: _save_item_fields (::1600)          ◄── Saves field changes to DB
│   └── PY: save_item_fields (.py:710)      ◄── Uses db.set_value (Phase 2a optimized)
│
├── JS: detect recipe/size/packs changed
│   └── frappe.call("process_recipe_change")◄── Triggers bg job
│
├── PY: process_recipe_change (.py:1572)    ◄── Endpoint: enqueue bg worker
│   │
│   ├── Guard: rq_status != Processing      ◄── Blocker if already processing
│   ├── Guard: produ_status = Recipe Change ◄── Status must match
│   ├── Guard: mr_reference exists          ◄── Must have existing MR
│   ├── Guard: dp.custom_submit_ref exists  ◄── Must be submitted
│   │
│   └── enqueue _background_change_recipe   ◄── RQ "long" queue, 600s timeout
│
└── RQ Worker: _background_change_recipe (.py:1694)
    │
    ├── Guard: produ_status still "Recipe Change"
    ├── Guard: mr_reference still exists
    │
    └── CALL: process_recipe_change_or_size_change (change_size.py:79)
        │
        ├── For each "Recipe Change" row on this DP:
        │   │
        │   ├── 1. IDENTITY CHECK
        │   │   └── Guard: Cook WO not Already Completed
        │   │
        │   ├── 2. BACKUP QUALITY DATA
        │   │   └── _get_cook_quality_data_by_wo(old_cook)
        │   │
        │   ├── 3. CANCEL OLD WOs
        │   │   └── _cancel_work_orders_by_id (cancellation.py:194)
        │   │       ├── Guard: Cook WO not Completed (double-check)
        │   │       ├── _bulk_clean_stock_and_jobs(wos) — BOM depth ordered
        │   │       └── For each WO: Draft→delete, Submitted→cancel
        │   │
        │   ├── 4. CANCEL PRODUCTION PLAN
        │   │
        │   ├── 5. CREATE NEW MR + WOs
        │   │   └── recreate_mr_after_update_slot (DP::389)
        │   │       └── MR.submit() → PP → Cook+Pack+WIP
        │   │
        │   ├── 6. RELINK QUALITY
        │   │   └── _relink_quality_docs(quality_data, new_cook_wo)
        │   │
        │   └── 7. WRITE BACK
        │       └── _write_back_to_row_additive (DP::580)
        │
        └── rq_status = "Done" + produ_status preserved (not auto-cleared)
```

### Key Details
- **Pre-check blocks save:** If Cook WO is Completed, save never happens — no background job created.
- **Atomic MR creation:** New MR created BEFORE old MR is detached. If new MR fails, old data stays intact.
- **Quality preservation:** Reviews + Weight Records are backed up before cancel and relinked to new Cook WO.
- **Status preserved:** produ_status stays "Recipe Change" after completion — user can see the change was processed.

---

## 3. Pack Change

### Purpose
User changes pack quantities/names/remarks only. Old Pack WOs cancelled, new Pack WO created. Cook WO preserved.

### ⚠️ Pre-Check
Before saving, `check_pack_wo_completed` verifies NO Pack WO is Completed. If any is, save is **blocked** and error message shown.

### Call Tree

```
User selects "Pack Change" in status dropdown
│
├── JS: status change handler               ◄── Fires check_pack_wo_completed immediately
│   └── If any Pack Completed → frappe.msgprint("🛑 Cannot change packs...")
│   └── Guard: d._wo_checked prevents duplicate fires
│
User changes pack fields → Save
│
├── JS: primary_action PRE-CHECK
│   └── check_pack_wo_completed
│       ├── If any Pack Completed → frappe.msgprint → return (SAVE BLOCKED)
│       └── If OK → _do_save() → proceeds
│
├── JS: _save_item_fields (::1600)
│   └── save_item_fields (.py:710) → db.set_value
│
├── JS: detect packs changed
│   └── frappe.call("process_pack_change")
│
├── PY: process_pack_change (.py:1617)
│   │
│   ├── Guard: rq_status != Processing
│   ├── Guard: produ_status = Pack Change
│   ├── Guard: mr_reference exists
│   ├── Guard: dp.custom_submit_ref exists
│   │
│   └── enqueue _background_pack_change
│
└── RQ Worker: _background_pack_change (.py:1777)
    │
    └── CALL: process_pack_change_or_add (change_pack.py:9)
        │
        ├── For each "Pack Change" row:
        │   │
        │   ├── 1. CANCEL OLD PACK ONLY
        │   │   └── _cancel_cook_pack_by_id — Pack WOs only
        │   │       └── Draft→delete, Submitted→cancel (retry 2x)
        │   │
        │   ├── 2. CREATE NEW MR
        │   │   └── recreate_mr_after_update_slot → Cook+Pack+WIP
        │   │
        │   ├── 3. KEEP ONLY PACK
        │   │   └── _cleanup_everything_except_new_pack
        │   │       └── Cook+WIP → deleted/cancelled. Only new Pack WO survives.
        │   │
        │   └── 4. RWS
        │       └── rws(dp_doc, child_doctype)
        │
        └── rq_status = "Done" + produ_status preserved
```

### Key Details
- **Pack-only cancel:** Only Pack WOs are cancelled. Cook + WIP preserved.
- **New WO cleanup:** Newly created Cook + WIP are deleted/cancelled. Only new Pack WO is kept.
- **Status preserved:** produ_status stays "Pack Change" after completion.

---

## 4. Change Slot

### Purpose
User drags a recipe to an empty slot. Recipe data moves, WOs migrate to new slot via link_id transfer.

### Call Tree

```
User drags recipe to empty slot
│
├── JS: _handle_drop (::1128)               ◄── Drag-drop event handler
├── JS: _do_move_item (::1222)              ◄── Move to empty slot
│
├── PY: save_move_item (.py:356, has_wos)   ◄── Endpoint
│   │
│   ├── Guard: rq_status != Processing
│   ├── Guard: Cook WO not Completed
│   │
│   ├── Find source_row + target_nc
│   │   └── If no target_nc → create new "No Cooking" row
│   │
│   ├── Swap ws/round/link_id between rows
│   │
│   ├── _migrate_db_link_ids(old_link_id → source_row.link_id)
│   │   └── UPDATE tabWork Order, tabStock Entry (deadlock retry 3x)
│   │
│   ├── Set both rows: produ_status="Change Slot", rq_status="Processing"
│   ├── dp.save()
│   └── enqueue _background_move_wo_migration
│
└── RQ Worker: _background_move_wo_migration (.py:1647)
    │
    ├── Find ALL Processing rows for this DP
    │
    └── For each recipe row (skip No Cooking):
        │
        ├── _get_quality_data_by_id(link_id) ◄── Backup quality docs
        │
        ├── 1. CANCEL OLD WO ON NEW SLOT
        │   └── _cancel_cook_pack_by_id (rearrange::92)
        │
        ├── 2. CREATE NEW MR + WO
        │   └── recreate_mr_after_update_slot (DP::389)
        │
        ├── 3. CLEANUP NEW WIP
        │   └── _cleanup_redundant_wips (rearrange::130)
        │
        ├── 4. RELINK QUALITY
        │   └── _relink_quality_docs(quality_data, new_cook_wo)
        │
        ├── 5. CLEAR BOTH ROWS
        │   └── produ_status + custom_pair_id cleared on BOTH rows
        │
        └── rq_status = "Done"
```

### Key Details
- **Auto-clears:** After completion, both rows' `produ_status` and `custom_pair_id` are cleared.
- **No Cooking skipped:** In the bg worker, No Cooking rows are set to Done immediately.
- **Error messages:** Show actual server error (not generic "Save failed — reloading").

---

## 5. Rearrange

### Purpose
User drags a recipe onto another recipe. Both recipes swap positions. Both sets of WOs cancelled and recreated on swapped link_ids.

### Call Tree

```
User drags recipe onto another recipe
│
├── JS: _handle_drop (::1128)
├── JS: _swap_recipes (::1207)
│
├── PY: swap_recipes (.py:1026, has_wos)    ◄── Endpoint
│   │
│   ├── Guard: rq_status != Processing (both rows)
│   ├── Guard: Neither Cook WO Completed
│   │
│   ├── Swap recipe data between row_a ↔ row_b
│   │   └── SLOT FIELDS preserved: ws, round, link_id, idx
│   │
│   ├── Set both: produ_status="Rearrange", rq_status="Processing"
│   ├── dp.save()
│   └── enqueue _background_swap_recipes
│
└── RQ Worker: _background_swap_recipes (.py:1819)
    │
    ├── 1. BACKUP QUALITY DATA (both rows)
    │
    ├── 2. SWAP WOs IN DB
    │   └── _swap_db_link_ids — A→TEMP, B→A, TEMP→B (retry 3x)
    │
    ├── 3. CANCEL OLD WOs (both sides)
    │
    ├── 4. CREATE NEW MR + WOs (both rows)
    │   └── Each: MR.submit() → PP → Cook+Pack+WIP
    │
    ├── 5. CLEANUP NEW WIP (both rows)
    │
    ├── 6. RELINK QUALITY (crosswise)
    │   └── A's quality → B's new Cook, B's quality → A's new Cook
    │
    ├── 7. CLEAR BOTH ROWS
    │   └── produ_status + custom_pair_id + rq_status cleared on BOTH rows
    │
    └── rq_status = "Done"
```

### Key Details
- **Auto-clears:** After completion, both rows' `produ_status`, `custom_pair_id`, and `rq_status` are cleared.
- **Crosswise quality:** A's quality docs go to B's new Cook WO (recipes swapped positions).
- **Error messages:** Show actual server error (not generic "Save failed — reloading").

---

## 6. Cancelled

### Purpose
User cancels a recipe. All WOs destroyed. Row reset to "No Cooking", freeing the slot.

### ⚠️ Access
**"Cancelled" is NOT available from the status dropdown.** User must use the **"Cancel Recipe" button** in the edit dialog (Actions section). This ensures proper `cancel_item` flow with `rq_status = "Processing"` and background worker.

### Call Tree

```
User clicks "Cancel Recipe" button in edit dialog
│
├── JS: Cancel Recipe button handler
│   └── frappe.confirm("Cancel this recipe?")
│
├── PY: cancel_item (.py:1667)              ◄── Endpoint (Phase 2a optimized)
│   ├── Guard: row_data.rq_status != Processing
│   ├── frappe.db.set_value — produ_status="Cancelled", rq_status="Processing"
│   └── enqueue _background_cancel_item
│
└── RQ Worker: _background_cancel_item (.py:1730)
    │
    ├── Guard: produ_status still "Cancelled"
    │
    └── CALL: process_cancellations (cancellation.py:337)
        │
        ├── Find ALL "Cancelled" rows on this DP
        │
        └── For each row: _process_cancel_row
            │
            ├── 1. CANCEL ALL WOs (Cook+Pack+WIP)
            │   └── _cancel_work_orders_by_id (cancellation.py:194)
            │
            ├── 2. CANCEL PRODUCTION PLAN
            │
            ├── 3. CLEAR MR LINK
            │
            └── 4. RESET TO NO COOKING (slot freed)
```

### Key Details
- **Slot freed:** After cancellation, row becomes "No Cooking" — ready for a new recipe.
- **All WOs destroyed:** Cook + Pack + WIP all cancelled. MR link cleared. PP cancelled.
- **Cancel NOT in dropdown:** Only accessible via Cancel Recipe button to ensure proper flow.

---

## 7. Only Remark

### Purpose
User changes only recipe_note or pack remarks. No WOs touched. Just field update.

### Call Tree

```
User edits row → changes note/remarks → status "Only Remark" → Save
│
├── JS: _show_edit_dialog (::1286)
├── JS: _save_item_fields (::1600)
│
├── PY: save_item_fields (.py:710)
│   ├── Find DP + child row
│   ├── db.set_value (single row, Phase 2a)
│   └── commit
│
└── _load_week() → board refresh
```

No MR, no PP, no WO. No background job. **Synchronous field update.**

### Key Details
- **Status preserved:** "Only Remark" stays after save — user can see the remark was applied.
- **In DP form:** rws() syncs notes to WOs but status is NOT auto-cleared.
- **After Create WO:** Status cleared along with all others.

---

## 8. Single WO

### ⚠️ Hidden
"Single WO" has been **removed from the status dropdown.** The code still exists but the option is hidden.

---

## WIP Cancellation Summary

| Status | Old WIP | New WIP | Mechanism |
|--------|---------|---------|-----------|
| New Schedule | N/A | **Persists** | First-time creation |
| **Recipe Change** | **Cancelled** | **Persists** | `_cancel_work_orders_by_id` cancels all old |
| Pack Change | Preserved | **Deleted** | `_cleanup_everything_except_new_pack` |
| Change Slot | Preserved | **Deleted** | `_cleanup_redundant_wips` (Draft+Submitted) |
| Rearrange | Preserved | **Deleted** | `_cleanup_redundant_wips` (Draft+Submitted) |
| **Cancelled** | **Cancelled** | N/A | `_cancel_work_orders_by_id` destroys all |
| Only Remark | N/A | N/A | No WOs |
| Single WO | N/A | N/A | Hidden |

---

## Background Workers

| Worker | Delegates to | Statuses | Key Feature |
|--------|-------------|----------|-------------|
| `_background_change_recipe` | `process_recipe_change_or_size_change` | Recipe Change | Quality backup + relink, Cook pre-check |
| `_background_pack_change` | `process_pack_change_or_add` | Pack Change | Pack-only cancel, Pack pre-check |
| `_background_cancel_item` | `process_cancellations` | Cancelled | Slot reset after cancel |
| `_background_create_mr` | `_process_new_schedules` | New Schedule | Batch MR creation |
| `_background_swap_recipes` | Direct | Rearrange | Crosswise quality, status auto-clear |
| `_background_move_wo_migration` | Direct | Change Slot | NO_COOKING skip, pair auto-clear |
| `_background_process_dp` | `process_manual_updates` | All (catch-all) | Batch all changes, used for retry |

---

## The MR → WO Chain

Every status that creates WOs eventually calls the same pipeline:

```
create_material_request (DP::356)
or
recreate_mr_after_update_slot (DP::389)
│
├── Build MR document
│   ├── _build_mr_header (DP::435)
│   │   ├── material_request_type = "Manufacture"
│   │   ├── custom_link_id = row.link_id
│   │   ├── custom_batch_size = row.size
│   │   └── custom_recipe_reference = dp.name
│   │
│   ├── _append_pack_items (DP::462)
│   │   └── For each pack_name: mr.append("items", {pack data})
│   │
│   └── _append_recipe_row (DP::502)
│       └── mr.append("custom_recipe_table", {recipe data})
│
├── mr.insert()                              ◄── Frappe validates + saves
│
├── mr.submit()                              ◄── Frappe submits
│   │
│   └── Internal Frappe flow:
│        MR.submit()
│          └─ Creates Production Plan (auto)
│               └─ PP.submit()
│                    ├── Cook WO
│                    ├── Pack WO × N
│                    └── WIP WO × N (BOM sub-assembly)
│
└── Write back to child row
    └── _write_back_to_row_additive (DP::580)
        ├── Merge new WOs with existing
        ├── Filter out docstatus=2 (cancelled)
        └── db.set_value(child_row, wo_list + wo_list_with_type)
```
