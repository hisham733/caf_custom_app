# Production Schedule Board

A drag-and-drop scheduling board matching the Metabase "Meta - Multi DP Schedule" layout.
Accessible at `/app/production-schedule`.

## Purpose

Replace the "edit 6 separate DPs" workflow with a single visual board matching
the Metabase weekly view, supporting both **Edit** (draft DPs, drag-drop) and
**View** (submitted DPs, click-through to ERPNext) modes.

## Layout (matches Metabase SQL)

```
WSCook   |     Mon 22           |     Tue 23         | ... |     Sat 27
         | Date R1  R2  R3 N P  | Date R1 R2 R3 N P  |     | Date R1 R2 R3 N P
─────────┼───────────────────────┼────────────────────┼─────┼────────────────
Cooker 1 | 22Jun 🟢Rx 🩷Ry — n p | 23Jun 🔴Rz —  — n p|
Cooker 2 | ...                  | ...                |
Kettle 1 | ...                  | ...                |
Fryer 1  | ...                  | ...                |
```

- **Rows**: Workstations from `tabWorkstation` (Cooker → Kettle → Fryer, sorted by class then numeric index)
- **Columns per day** (6 sub-columns): Date, R1, R2, R3, Note, Pack
- **R1/R2/R3 cells**: Recipe name + status emoji + size badge
- **Note/Pack**: Combined recipe notes and pack remarks per workstation/day
- **Mode toggle**: Edit Schedule (draft DPs) / View Schedule (submitted DPs)

## Mode Behavior

| Feature | Edit Schedule | View Schedule |
|---------|--------------|---------------|
| DPs shown | Draft only (docstatus=0) | Submitted only (docstatus=1) |
| Drag-drop | Yes, between R1/R2/R3 slots | No |
| Click recipe | Edit dialog (status, size, packs) | Open ERPNext DP form in new tab |
| Click "+" | Add recipe dialog | Not shown |
| Click Note/Pack | Inline edit dialog | Read-only |
| Submit Week btn | Visible | Hidden |

## Data Flow

```
Board
  │
  ├─ load ──────► get_week_data(year, week, mode)
  │                   1. ISO week → Mon-Sat dates
  │                   2. Per-day latest DP (draft or submitted)
  │                   3. Get workstations from tabWorkstation
  │                   4. For each (ws, day), group into R1/R2/R3 + notes/packs
  │
  ├─ drag ──────► save_move_item(id, source_date, target_date, cooker, round)
  │
  ├─ edit ──────► save_item_fields(id, fields)   (batch save)
  │                ├─ process_recipe_change()      if status="Recipe Change"
  │                └─ process_dp_updates()         if status triggers changes
  │
  ├─ add ───────► add_recipe(day, recipe, size, cooker, pack_count, round)
  │                └─ _background_create_mr()      if status="New Schedule"
  │
  └─ submit ────► submit_week(week_monday) → submit_dp_week()
```

## Integration

| Existing Component | Board Interaction |
|--------------------|-------------------|
| `rearrange_and_change_slot.py` | Background workers call `_migrate_db_link_ids`, `_cancel_cook_pack_by_id`, `_relink_quality_docs` during drag-drop WO migration |
| `change_size.py` | Not used directly; `create_material_request_after_change_size` handles WO recreation after recipe change |
| `cancellation.py` | `_background_cancel_item` calls `process_cancellations()` to cancel WOs, then resets the row to No Cooking |
| `submit_dp_week_by_number()` | Board's Submit Week delegates to `submit_dp_week()` |
| Metabase | Sets `trigger_metabase_refresh` cookie after save |

## Documentation

| File | Audience | Contents |
|------|----------|----------|
| [`README.md`](README.md) | Developers | Blueprint, layout, data flow, endpoints, integration |
| [`workflow.md`](workflow.md) | Developers | Technical workflows, background jobs, state machine, race conditions |
| [`user-guide.md`](user-guide.md) | End users | How to add/edit/move/cancel recipes, submit week, troubleshooting |

## Files

```
apps/caf/caf/caf/page/production_schedule/
├── __init__.py              Empty
├── README.md                Blueprint (this file)
├── workflow.md              Technical workflow documentation
├── user-guide.md            User-facing guide
├── production_schedule.json Page DocType metadata (name: production-schedule)
├── production_schedule.py   Server endpoints + background workers (16 whitelisted methods)
├── production_schedule.js   Client: grid + drag-drop + dialogs
└── production_schedule.css  Pivoted grid styling
```

## Server Endpoints

| Method | Args | Purpose |
|--------|------|---------|
| `get_workstations` | — | All active Cooker/Kettle/Fryer workstations sorted |
| `get_week_data` | `year, week_number, mode` | Full pivoted schedule data |
| `save_move_item` | `item_id, source_date, target_date, target_cooker, target_round` | Move a recipe between slots (same-day only) |
| `save_item_fields` | `item_id, fields[]` | Save multiple fields in a single `dp.save()` call |
| `save_update_item` | `item_id, field, value` | Single field update (legacy) |
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
| `get_dp_row_url` | `dp_name, row_name` | ERPNext URL for View mode click-through |
