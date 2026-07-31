# Production Schedule v2 — Technical Workflow

## Overview

The page has two modes: **Edit Schedule** and **View Schedule**. Edit mode is for planning recipes. View mode is read-only with per-day "Create Work Order" buttons that run `process_manual_updates` synchronously.

## Mode States

```
                    ┌─────────────────────┐
                    │    Page Loads        │
                    │  Default: View Mode  │
                    └──────┬──────────────┘
                           │
                     Load submitted DPs
                     (docstatus=1)
                           │
                    Show Create WO buttons
                    (per day, where enabled)
                           │
          User switches mode to "Edit Schedule"
                           │
                           ▼
               Has draft DPs for the week?
                    │              │
                   YES             NO
                    │              │
                    ▼              ▼
             Load existing    Has submitted DPs
             draft DPs        with custom_submit_ref?
                                   │
                              YES       NO
                               │         │
                               ▼         ▼
                        create_week_  create fresh
                        version       draft DPs
                        (copies data  (blank week)
                         from latest
                         submitted DP)
```

## Page Load / Initialization

When the page loads, it defaults to **View Schedule** mode:

1. Load submitted DPs (docstatus=1) for the week
2. Display read-only board
3. Show "Create Work Order" buttons per day (enabled only when `custom_submit_ref` is empty)

**No auto-creation happens on page load.** Versions are created only when the user explicitly switches to Edit Schedule mode.

### When user switches to Edit Schedule:

1. Check if draft DPs (docstatus=0) exist for Mon–Sat of the target week
2. **If drafts exist**: load them — user was already editing this week
3. **If no drafts**: check for submitted DPs (docstatus=1) with `custom_submit_ref` filled (WOs were created for a previous version)
   - **Yes**: call `create_week_version(week_number)` → creates new draft copies from the latest submitted DPs (versioning: DP-YYYY-MM-DD-0001 → 0002 → 0003 ...)
   - **No**: create fresh blank draft DPs (version 0001, first time for the week)

### Versioning

DP autoname is `DP-YYYY-MM-DD-####` (serial by date). Each time a new draft is created from a submitted DP, the serial auto-increments.

| Action | DP Name | custom_submit_ref |
|--------|---------|-------------------|
| First time, create fresh drafts | DP-2026-07-06-0001 | (empty) |
| Submit | DP-2026-07-06-0001, docstatus=1 | (empty) |
| Create WO | DP-2026-07-06-0001, docstatus=1 | "DP-2026-07-06-0001" |
| Edit mode again → new version | DP-2026-07-06-0002 (draft) | "DP-2026-07-06-0001" (copied from source) |
| Submit | DP-2026-07-06-0002, docstatus=1 | "DP-2026-07-06-0001" |
| Create WO | DP-2026-07-06-0002, docstatus=1 | "DP-2026-07-06-0001" (not updated, already filled) |

`custom_submit_ref` is copied to new draft versions — the Create WO button displays the serial from this field (e.g., `"Create WO (0001)"`).

---

## Edit Mode

### What the user can do

- Drag-drop recipes between slots (Change Slot and Rearrange)
- Click "+" to add new recipes (New Schedule)
- Click recipes to edit (status, size, packs, recipe change, cancel)
- Edit recipe notes and pack remarks inline

### How changes are processed

**All WO processing runs in background (RQ workers)** — UI never freezes:

| Action | Endpoint | Background Worker |
|--------|----------|-------------------|
| Drag to empty slot (Change Slot) | `save_move_item` | `_background_move_wo_migration` |
| Drag onto another recipe (Rearrange) | `swap_recipes` | `_background_swap_recipes` |
| Add recipe (New Schedule) | `add_recipe` | `_background_create_mr` |
| Save edits | `save_item_fields` + `process_dp_updates` | `_background_process_dp` |
| Recipe change | `process_recipe_change` | `_background_change_recipe` |
| Cancel recipe | `cancel_item` | `_background_cancel_item` |

### Submit Button

Visible only in Edit mode. When clicked:

```
_submit_page()
  │
  ├─ 1. frappe.flags.skip_wo_creation = True
  │
  ├─ 2. For each day Mon–Sat:
  │      Find draft DP → dp.submit()
  │
  ├─ 3. frappe.flags.pop('skip_wo_creation')
  │
  └─ 4. state.mode = "View Schedule"
         _load_week()
```

**Key**: `frappe.flags.skip_wo_creation` prevents `on_submit` in `daily_production.py` from triggering `process_manual_updates()`. Submit only sets `docstatus=1` and `workflow_state="Submitted"`.

---

## View Mode

### Layout

- Submitted DPs (docstatus=1) displayed read-only
- No drag-drop, no add, no edit
- Clicking a recipe opens the DP form in ERPNext
- Each day column header shows a "Create Work Order" button

### Create Work Order Buttons

One button per day (Mon–Sat), placed in the day column header.

**Visibility**: Always shown in View mode.

**Enabled when**:
1. Mode is View Schedule
2. DP for that day is submitted (docstatus=1)
3. `custom_submit_ref` is empty

**Disabled when**:
- No DP for that day
- DP is draft (shouldn't happen in View mode)
- `custom_submit_ref` is already filled (WOs already created)

**Button label**:
- `"Create WO"` — when `custom_submit_ref` is empty
- `"Create WO (0001)"` — when `custom_submit_ref` has a value (shows the serial number from the DP name stored in `custom_submit_ref`)

### Create WO Flow (per day)

```
User clicks "Create WO" for Monday
  │
  ├─ Frontend:
  │   freeze: true, freeze_message: "Creating Work Orders..."
  │   frappe.call("process_day_dp", { week_monday, day_index: 0 })
  │
  ├─ Backend (process_day_dp):
  │   1. Calculate target day from week_monday + day_index
  │   2. Find submitted DP for that day (docstatus=1)
  │   3. If not found → error
  │   4. If custom_submit_ref already filled → error
  │   5. dp.process_manual_updates()
  │      → process_cancellations
  │      → process_recipe_change_or_size_change
  │      → process_slot_swaps (Change Slot)
  │      → process_switch (Rearrange)
  │      → process_pack_change_or_add
  │      → rws
  │      → _process_new_schedules (creates MRs + WOs)
  │      → _obsolete_older_records
  │   6. custom_submit_ref = dp.name (set inside process_manual_updates)
  │   7. Return { success: true }
  │
  └─ Frontend callback:
      hide_loading_overlay
      show_alert("Done")
      _load_week() → button now disabled (custom_submit_ref filled)
```

**Key**: `process_day_dp` runs **synchronously** — all WO creation (New Schedule, Change Slot, Rearrange, Recipe Change, Cancelled) for that day happens in the HTTP request. The page is frozen with a loading overlay until complete.

---

## Switching Back to Edit Mode

After WOs have been created (view mode), user can switch to Edit mode:

1. Dropdown changes to "Edit Schedule"
2. `create_week_version(week_number)` is called
3. For each day: finds the latest submitted DP, creates a new draft copy
   - Copies all rows (recipe, size, packs, link_ids, etc.)
   - **Copies `custom_submit_ref`** from source DP
4. `_load_week()` loads the new draft DPs

User can now drag-drop, add, edit — all in background as before.

---

## State Machine

### Page Mode

```
┌──────────────┐    Submit     ┌──────────────┐
│  EDIT MODE   │ ────────────► │  VIEW MODE    │
│              │               │               │
│ draft DPs    │               │ submitted DPs │
│ docstatus=0  │               │ docstatus=1   │
│              │  Mode switch  │               │
│              │ ◄──────────── │               │
│              │ (creates new  │               │
│              │  draft copies)│               │
└──────────────┘               └───────────────┘
```

### Daily Production — `custom_submit_ref`

```
 empty ──► (Submit) ──► empty (submitted, no WOs)
                              │
                     (Create WO click)
                              │
                              ▼
                      filled (WOs exist)
                              │
                     (Edit mode → new version)
                              │
                              ▼
                      copied to new draft
                              │
                     (Submit with flag)
                              │
                              ▼
                      filled (submitted, WOs from previous version exist)
                              │
                     (Create WO click)
                              │
                              ▼
                      process_manual_updates runs
                      (_obsolete_older_records marks old DP)
```

---

## Endpoints Reference

| Endpoint | Mode | Purpose |
|----------|------|---------|
| `get_week_data` | Both | Load week data, now includes `custom_submit_ref` per day |
| `create_week_version` | Edit | Create new draft copies from latest submitted DPs |
| `save_move_item` | Edit | Drag to empty slot (Change Slot) — bg worker |
| `swap_recipes` | Edit | Drag onto recipe (Rearrange) — bg worker |
| `add_recipe` | Edit | Add new recipe — bg worker |
| `save_item_fields` | Edit | Batch save edits |
| `cancel_item` | Edit | Cancel recipe — bg worker |
| `process_recipe_change` | Edit | Recipe change — bg worker |
| `process_dp_updates` | Edit | Trigger DP updates — bg worker |
| `submit_page` | Edit | Submit all draft DPs (with skip_wo_creation flag) |
| `process_day_dp` | View | Sync WO creation for one day |
| `get_row_status` | Both | Poll wo_status for bg job completion |

---

## Race Conditions & Guards

| Scenario | Mitigation |
|----------|------------|
| User drags before bg job runs | All bg workers check `produ_status` / `custom_wo_status` from DB before acting |
| User clicks Create WO twice | `process_day_dp` checks `custom_submit_ref` is empty; returns error if already filled |
| User submits while bg jobs running | Submit sets `skip_wo_creation` flag; bg jobs set `custom_wo_status = "Done"/"Failed"` independently |
| Rapid mode switches | `create_week_version` skips days that already have draft DPs |
| New draft created while RQ still queued | `custom_wo_status` cleared on new draft copy; old bg jobs guard on `custom_wo_status = "Processing"` |
| Create WO button shown for day with no DP | Button disabled; `process_day_dp` returns error if no DP found |

---

## Files to Modify

```
apps/caf/caf/caf/page/production_schedule/
├── production_schedule.py      ← process_day_dp, submit_page, get_week_data +custom_submit_ref
├── production_schedule.js      ← mode handling, Create WO buttons, submit_page, toolbar
├── new_page_workflow.md        ← This file

apps/caf/caf/caf/doctype/daily_production/
├── daily_production.py         ← on_submit: check skip_wo_creation flag
```

---

## Behavior Comparison: Old vs New

| Aspect | Old (Current) | New (v2) |
|--------|--------------|----------|
| Default mode | View Schedule | View Schedule (same) |
| Page load | Loads submitted DPs | Loads submitted DPs + shows Create WO buttons per day |
| Submit button | Submits + switches to view | Same — submits with `skip_wo_creation` flag + switches to view |
| Create WO button | Only on DP form | On page, per day, in view mode when `custom_submit_ref` empty |
| WO creation | DP form only (sync) | Page button per day (sync) |
| Drag-drop WO processing | Background (RQ) | Same — background (RQ) |
| Versioning | Manual (Create Week button) | Auto on Edit mode entry |
| `custom_submit_ref` on new draft | Copied from source | Same — copied from source |
| `on_submit` behavior | Runs WO if ref filled | Checks `skip_wo_creation` flag from Submit button |
