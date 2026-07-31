# Production Schedule — Technical Workflow

## Page Routes

| Route | Mode | Description |
|-------|------|-------------|
| `/app/production-schedule` | default | Loads whichever week was last viewed (stored in localStorage) |
| `/app/production-schedule?year=2026&week=27` | explicit | Loads a specific ISO week |
| `/app/production-schedule?mode=View+Schedule` | view | Shows submitted DPs only, view-only mode |

## Layout

- **Rows**: Workstations from `tabWorkstation` (Cooker → Kettle → Fryer, sorted by class then numeric index), excluding exhaust hoods and "cooker database"
- **Columns per day** (Mon–Sat): Date label, R1, R2, R3, Note, Pack
- **R1/R2/R3 cells**: Recipe name + status emoji + size badge
- **Note/Pack**: Combined recipe notes and pack remarks per workstation/day

## Server Endpoints

| Method | Args | Purpose |
|--------|------|---------|
| `get_workstations` | — | All active Cooker/Kettle/Fryer workstations sorted |
| `get_week_data` | `year, week_number, mode` | Full pivoted schedule data |
| `save_move_item` | `item_id, source_date, target_date, target_cooker, target_round` | Move a recipe between slots (same-day only) |
| `save_item_fields` | `item_id, fields[]` | Save multiple fields in a single `dp.save()` call |
| `save_update_item` | `item_id, field, value` | Single field update (legacy, kept for compatibility) |
| `add_recipe` | `day, recipe, size, cooker, pack_count, round_num, **kwargs` | Add new recipe row |
| `submit_week` | `week_monday` | Submit all draft DPs via `submit_dp_week()` |
| `create_week_version` | `week_number` | Create fresh draft DPs from latest submitted |
| `swap_recipes` | `source_id, target_id` | Swap recipe data between two rows in same DP |
| `undo_pair` | `pair_id, original_link_id, original_source_date` | Reverse a Change Slot or Rearrange |
| `get_recipe_bom_data` | `recipe_name` | Fetch BOM yield + raw materials |
| `get_row_status` | `item_id` | Lightweight poll for `wo_status` and `mr_reference` |
| `cancel_item` | `item_id` | Cancel item + enqueue background WO cancellation |
| `process_recipe_change` | `item_id` | Enqueue background WO reprocessing after recipe change |
| `process_dp_updates` | `item_id` | Enqueue `process_manual_updates` on parent DP |

## Mode Behavior

| Feature | Edit Schedule | View Schedule |
|---------|--------------|---------------|
| DPs shown | Draft only (docstatus=0) | Submitted only (docstatus=1) |
| Drag-drop | Yes, between R1/R2/R3 slots | No |
| Click recipe | Edit dialog (status, size, packs, cancel) | Open ERPNext DP form in new tab |
| Click "+" | Add recipe dialog | Not shown |
| Click Note/Pack | Inline edit dialog | Read-only |
| Submit Week btn | Visible | Hidden |
| Create Week btn | Visible | Hidden |

## Drag-Drop Flow (`save_move_item`)

### Same-day swap (within one DP)

1. Frontend identifies source row and target slot (workstation + round)
2. No Cooking row at target slot is located
3. Recipe row inherits target slot's `recipe_cook_workstaion` and `recipe_cook_round`
4. No Cooking row inherits source slot's workstation and round
5. `link_id` values are swapped (link_id is static to the slot, not the recipe)
6. If target No Cooking row has no `link_id`, a new one is auto-generated (`R-.YYYY.-.#####`)
7. Both rows get `produ_status = "Change Slot"` and a shared `custom_pair_id`
8. Quality data is captured from old `link_id` before migration
9. WOs are migrated via `_migrate_db_link_ids` (reassigns WO references from old link_id to new)
10. Both rows get `custom_wo_status = "Processing"`
11. DP is saved
12. `_background_move_wo_migration` enqueued (cancels Cook/Pack for new link_id, recreates, relinks quality docs)

### Cross-day moves

Cross-day moves are allowed when **neither** the source DP nor the target DP has Work Orders created (`custom_submit_ref` is empty on both).

**Block rule**: If either DP has `custom_submit_ref` filled, the cross-day move is rejected with: _"Both days must have no Work Orders to move across days"_.

**Move to empty slot**:
1. Frontend checks `dp_submit_refs` for both days — blocks if either has WOs
2. Backend fetches target DP (draft, docstatus=0)
3. Backend validates neither DP has `custom_submit_ref`
4. Source row is cleared to "No Cooking" (keeps its link_id and slot position), no status set
5. Target "No Cooking" row receives the recipe data (keeps its own link_id and slot position)
6. Target row gets `produ_status = "Change Slot"`; source row gets no status
7. No background WO processing needed (no WOs exist)

**Rearrange (swap two recipes)**: Also allowed across days under the same rule — both DPs must have no WOs. Simple data swap with no status or background processing.

## Swap (Rearrange) Flow (`swap_recipes`)

Swapping is triggered when dragging a recipe onto **another recipe** (not onto an empty No Cooking slot). Both rows must have recipes.

### Synchronous phase (fast, no UI freeze)

1. Locate both rows in the same draft DP
2. Identify `SLOT_FIELDS` (static to position, never swapped): `name, parent, parentfield, parenttype, doctype, idx, link_id, recipe_cook_workstaion, recipe_cook_round, required_date`
3. Compute `swappable` fields: all child table fields **except** SLOT_FIELDS
4. Swap every swappable field between the two rows:
   - `recipe_name`, `size`, `produ_status`, `number_of_pack`, all pack fields, etc.
5. Save DP, commit
6. If **either** row has an `mr_reference` (existing WOs):
   - Set both rows' `custom_wo_status = "Processing"`
   - Save DP again, commit
   - Enqueue `_background_swap_recipes(row_a_name, row_b_name)` to `long` queue, timeout 600s
   - Return `"Rearranging — background processing started"` immediately
7. If **neither** row has `mr_reference`: return `"Recipes swapped"` (no WO work needed)

### Client-side (JS)

- **No `freeze: true`** — the swap call returns instantly
- Board reloads immediately (shows swapped recipes with "Processing" badge)
- `_poll_row_status` polls every 5s until `wo_status` is no longer "Processing", then reloads the board

### Background worker (`_background_swap_recipes`)

```
Guard 1: Read both rows' custom_wo_status from DB
         → If either ≠ "Processing": clear both to "", commit, return

Guard 2: Load DP, get both row docs from memory
         → If either missing: clear both to "", commit, return

Step 1: Capture quality data (Quality Reviews + Weight Records)
        qual_a = _get_quality_data_by_id(row_a.link_id)   ← pre-swap link_id
        qual_b = _get_quality_data_by_id(row_b.link_id)

Step 2: _swap_db_link_ids(row_a.link_id, row_b.link_id)
        SQL: WOs at id_a → temp → id_a(gets id_b's WOs), id_b → id_b(gets id_a's WOs)

Step 3: Cancel Cook+Pack at both link_ids
        _cancel_cook_pack_by_id(row_a.link_id)  ← cancels old-B's Cook/Pack now at A's slot
        _cancel_cook_pack_by_id(row_b.link_id)  ← cancels old-A's Cook/Pack now at B's slot
        (WIP WOs are NOT cancelled — they survive and stay in place)

Step 4: Recreate WOs for both rows
        new_wos_a = dp.recreate_mr_after_update_slot(row_a.recipe_name, [row_a])
        new_wos_b = dp.recreate_mr_after_update_slot(row_b.recipe_name, [row_b])
        → Creates fresh WIP + Cook + Pack WOs at each link_id

Step 5: Clean up redundant WIPs
        _cleanup_redundant_wips(new_wos_a, row_a, …)  ← deletes NEW WIP (old WIP survives)
        _cleanup_redundant_wips(new_wos_b, row_b, …)

Step 6: Relink quality docs cross-wise
        new_cook_a = get_wo_by_type(row_a.link_id, "Cook")
        new_cook_b = get_wo_by_type(row_b.link_id, "Cook")
        _relink_quality_docs(qual_b, new_cook_a)  ← old-B's quality → A's new Cook WO
        _relink_quality_docs(qual_a, new_cook_b)  ← old-A's quality → B's new Cook WO

Success: set both rows custom_wo_status = "Done"
Failure: set both rows custom_wo_status = "Failed", commit
```

### Link ID Ownership After Swap

| Before Swap | After Swap |
|---|---|
| Slot A (link_id=X) has recipe Alpha, with WOs at link_id=X | Slot A (link_id=X) has recipe Beta |
| Slot B (link_id=Y) has recipe Beta, with WOs at link_id=Y | Slot B (link_id=Y) has recipe Alpha |

After `_swap_db_link_ids`: WOs at X now belong to Beta's old slot, WOs at Y now belong to Alpha's old slot. After cancel + recreate: each slot gets fresh new WOs with the correct recipe. Old WIP WOs survive in place.

## Edit Dialog Flow (`save_item_fields`)

1. Frontend calls `save_item_fields(item_id, fields)` — all fields sent in one batch
2. Server finds the row in the draft DP
3. If `produ_status = "New Schedule"`, clears `mr_reference`, `wo_list`, `wo_list_with_type`
4. All fields applied, then single `dp.save()` call
5. After save, if status is **"Recipe Change"** and recipe changed: calls `process_recipe_change` endpoint
6. After save, if status is one of change-triggering statuses: calls `process_dp_updates` endpoint

### Client-side checks before save

- `document.activeElement.blur()` forces Frappe to finalize typed-but-not-blurred field values
- `d.get_values()` re-read after blur to capture all values
- If recipe changed to a non-No-Cooking value and status is "Recipe Change": auto-clears `size=0`, `number_of_pack=1`, all pack_name/pack_qty/pack_remark (1–7)
- Size is required when recipe is set and is not "No Cooking"
- Enter key does NOT submit dialog forms (prevented in `_apply_dialog_restrictions`)

## Add Recipe Flow (`add_recipe`)

1. Locates draft DP for the given day
2. Checks if a No Cooking row already exists at target workstation+round — reuses it if found, otherwise appends a new row
3. Sets recipe, size, workstation, round, pack_count, produ_status, production_type, urgent, note, production_plane
4. If `produ_status = "New Schedule"`: sets `custom_wo_status = "Processing"` and enqueues `_background_create_mr`
5. Saves DP and returns the new item data

## Background Jobs

| Worker Function | Triggered By | Purpose |
|----------------|-------------|---------|
| `_background_create_mr` | `add_recipe` with "New Schedule" | Creates MR + WOs for the new row |
| `_background_process_dp` | `process_dp_updates` (after edit save) | Runs `process_manual_updates()` |
| `_background_move_wo_migration` | `save_move_item` (after change slot) | Cancels old Cook/Pack WOs, recreates for new slot, relinks quality docs |
| `_background_swap_recipes` | `swap_recipes` (after rearrange) | Swaps link_ids, cancels old Cook/Pack for both rows, recreates, cleans up WIPs, relinks quality cross-wise |
| `_background_change_recipe` | `process_recipe_change` (after recipe edit) | Cancels existing Cook/Pack, recreates for new recipe |
| `_background_cancel_item` | `cancel_item` | Processes WO cancellations, resets row to No Cooking |

### `_background_create_mr`

- Loads the DP, checks row still has `produ_status = "New Schedule"` (if moved/dragged before job ran, returns early)
- Calls `dp._process_new_schedules()` which handles MR + WO creation
- Sets `custom_wo_status = "Done"` on success, `"Failed"` on error

### `_background_process_dp`

- Loads DP, calls `dp.process_manual_updates()` (handles Change Slot, Rearrange, Recipe Change, Cancelled)
- Sets `custom_wo_status = "Done"` on all rows on success, `"Failed"` on error

### `_background_move_wo_migration`

- Loads row, checks `mr_reference`:
  - If present: cancels Cook/Pack WOs via `_cancel_cook_pack_by_id`
  - If absent: skips cancel (fresh creation)
- Calls `dp.recreate_mr_after_update_slot()` to create new WOs
- Cleans up redundant WIP WOs via `_cleanup_redundant_wips`
- If MR existed: finds new Cook WO and relinks captured quality data
- Sets `custom_wo_status = "Done"` on success, `"Failed"` on error

### `_background_swap_recipes`

- Same pattern as native DP's `_process_one_switch_pair` (rearrange_and_change_slot.py)
- Guard: re-reads both rows' `custom_wo_status` from DB — must be "Processing"
- Guard early-return: clears status to `""` + commit on both rows
- Captures quality data from both link_ids (before swap/cancel)
- `_swap_db_link_ids`: SQL-level swap of WO `custom_link_id` between slots
- `_cancel_cook_pack_by_id` on both link_ids (Cook+Pack only, WIP untouched)
- `recreate_mr_after_update_slot` on both rows (creates MR + fresh WOs)
- `_cleanup_redundant_wips` on both rows (deletes newly created WIP WOs, old WIP survives)
- Relinks quality docs cross-wise: old-A quality → new-B Cook WO, old-B quality → new-A Cook WO
- Sets both rows `custom_wo_status = "Done"` on success, `"Failed"` on error with commit

### `_background_change_recipe`

- Loads DP, cancels existing Cook/Pack via `_cancel_cook_pack_by_id`
- Creates new WOs via `dp.recreate_mr_after_update_slot()`
- Cleans up redundant WIPs
- Sets `custom_wo_status = "Done"` or `"Failed"`

### `_background_cancel_item`

- Calls `process_cancellations()` to cancel all WOs for the row
- Resets the row to clean "No Cooking" state: clears recipe, size, packs, mr_reference, wo_list, produ_status, custom_wo_status, production_type, urgent, note
- The slot becomes reusable by add dialog or drag-drop
- Sets `custom_wo_status = "Done"` on success, `"Failed"` on error

## Undo Flow (`undo_pair`)

### Rearrange (undo swap of two recipes)

- Finds both rows by `custom_pair_id`
- Swaps all swappable fields back to original positions
- Clears `produ_status` and `custom_pair_id` on both rows
- **Note**: Does NOT reverse WO changes — WOs remain at their post-swap link_ids

### Change Slot — Same Day

- Swaps workstation and round back to original
- Clears `produ_status` and `custom_pair_id`

### Change Slot — Cross Day

- Copies all swappable data from target row back to source row
- Restores source row's original `link_id`
- Deletes the target row from its DP
- Clears `produ_status` and `custom_pair_id`

## State Machine — `produ_status`

```
(empty) ──────────► "New Schedule" ──► (clear after MR creation)
        │                                  ▲
        ├─► "Change Slot"  ──► submit ────┘
        ├─► "Rearrange"    ──► submit ────┘
        ├─► "Recipe Change" ─► submit ────┘
        ├─► "Cancelled"    ──► submit ────┘
        └─► remains empty for No Cooking rows
```

- "Change Slot" and "Rearrange" are set by drag-drop only (not available in add/edit dialog)
- "New Schedule" is available in add dialog but hidden from edit dialog when `mr_reference` exists
- "Recipe Change" makes recipe and size editable in edit dialog
- Changing recipe when status is "Recipe Change" auto-clears size to 0 and all pack info

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Batch save (`save_item_fields`) | Sequential per-field saves caused inter-field validation races (e.g., `number_of_pack` saved before `pack_name`) |
| link_id static to slot, not recipe | Allows undo, quality doc relinking, and WO tracking by slot position |
| Cross-day moves gated on WOs | Prevents complex WO migration across DPs; only allowed when neither DP has WOs |
| All WO processing enqueued | UI never blocks; errors set `custom_wo_status = "Failed"` |
| Row reset to No Cooking after cancel | Frees the slot for new schedules without requiring page reload |
| `document.activeElement.blur()` before save | Forces Frappe control finalization for typed-but-not-blurred values |
| RQ worker required | Without running `bench worker`, background jobs sit in queue forever |
| "Change Slot"/"Rearrange" not in dialog dropdown | These statuses are meaningful only in drag-drop context |

## Race Condition Mitigations

| Scenario | Mitigation |
|----------|------------|
| User drags a row after clicking Add (before bg job runs) | `_background_create_mr` checks `produ_status` is still "New Schedule"; returns early if changed |
| RQ worker delayed, row moved before MR created | `_background_move_wo_migration` handles both with/without MR case |
| User clicks Save twice rapidly | Batch save is idempotent; background jobs check current row state on load |
| Cancel + re-add same slot before bg cancel completes | Cancel clears the row to No Cooking; re-add checks for existing No Cooking row |
| Recipe change submitted before WO reprocessing | `custom_wo_status = "Processing"` set synchronously; submit checks status |
| User swaps two recipes in rapid succession | `_background_swap_recipes` guards on `custom_wo_status = "Processing"`; second swap waits for first to finish or gets guard-cleared |

## Relevant Files

```
apps/caf/caf/caf/page/production_schedule/
├── __init__.py              Empty
├── README.md                Blueprint
├── production_schedule.json Page DocType metadata
├── production_schedule.py   Server endpoints + background workers
├── production_schedule.js   Client: grid + drag-drop + dialogs
├── production_schedule.css  Pivoted grid styling
├── workflow.md              This file
└── user-guide.md            User documentation

apps/caf/caf/caf/doctype/daily_production/
├── daily_production.py      DP DocType (validate, submit, MR creation)
├── rearrange_and_change_slot.py   Slot migration, quality relink, WO cleanup
├── cancellation.py          WO cancellation logic
├── wo_helpers.py            WO lookup helpers
└── change_size.py           Size change MR processing
```
