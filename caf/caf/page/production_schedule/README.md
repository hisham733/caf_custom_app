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
  ├─ edit ──────► save_update_item(id, field, value)
  │
  ├─ add ───────► add_recipe(day, recipe, size, cooker, pack_count, round)
  │
  └─ submit ────► submit_week(week_monday) → submit_dp_week()
```

## Integration

| Existing Component | Board Interaction |
|--------------------|-------------------|
| `rearrange_and_change_slot.py` | Board moves rows directly. On submit, produ_status drives Change Slot/Rearrange |
| `change_size.py` | Board edits size. On submit, produ_status drives Recipe Change |
| `cancellation.py` | Not triggered by board. User sets produ_status="Cancelled" via edit dialog |
| `submit_dp_week_by_number()` | Board's Submit Week delegates to `submit_dp_week()` |
| Metabase | Sets `trigger_metabase_refresh` cookie after save |

## Files

```
apps/caf/caf/caf/page/production_schedule/
├── __init__.py              Empty
├── README.md                Blueprint (this file)
├── production_schedule.json Page DocType metadata (name: production-schedule)
├── production_schedule.py   Server endpoints (7 whitelisted methods)
├── production_schedule.js   Client: grid + drag-drop + dialogs
└── production_schedule.css  Pivoted grid styling
```

## Server Endpoints

| Method | Args | Purpose |
|--------|------|---------|
| `get_workstations` | — | All active Cooker/Kettle/Fryer workstations sorted |
| `get_week_data` | `year, week_number, mode` | Full pivoted schedule data |
| `save_move_item` | `item_id, source_date, target_date, target_cooker, target_round` | Move a recipe between slots |
| `save_update_item` | `item_id, field, value` | Single field update |
| `add_recipe` | `day, recipe, size, cooker, pack_count, round_num` | Add new recipe row |
| `submit_week` | `week_monday` | Submit all draft DPs via `submit_dp_week()` |
| `get_dp_row_url` | `dp_name, row_name` | ERPNext URL for View mode click-through |
