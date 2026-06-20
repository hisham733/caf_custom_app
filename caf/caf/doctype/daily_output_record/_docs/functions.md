# `daily_output_record/` — Function Reference

## Controller: `daily_output_record.py`

---

### `DailyOutputRecord.process_all()`

**What it does:** Called from the "Process All" button. Iterates all rows in `self.items`:
- **Done rows** -> calls `_validate_row()` to check actual_qty vs produced_qty (warning + comment on mismatch), then skips processing
- **Pending rows** -> processes each link_id through the full production pipeline: WIP WO (submit -> Transfer SE -> Job Cards -> Manufacture SE) -> Cook WO (submit -> Transfer SE -> Job Cards -> Recook -> Manufacture SE) -> Pack WO (submit -> Transfer SE -> Job Cards -> Manufacture SE with balance/actual_qty)

**Links to:** 
- `caf.caf.overrides.work_order.make_stock_entry()`
- `caf.caf.overrides.work_order.create_recook_stock_entry_backend()`
- `frappe.get_all()` for finding WOs by link_id
- `_validate_row()` for Done rows

**Inputs:** None (reads `self.items`)

**Output / Return:** JSON `{"success": bool, "message": str}` or `{"success": false, "error": str, "failed_row": int, "link_id": str}`

**Stops on first error** — remaining rows and WOs are skipped. Error message includes the failing WO name.

---

### `DailyOutputRecord._process_row(row)`

**What it does:** Processes a single row: WIP -> Cook -> Pack WO for that link_id. For Pack WOs, iterates pack slots (1..number_of_pack) matching each Pack WO by its production_item to the slot's pack_name / pack_name_N. Falls back to single-field mode if number_of_pack is 0 (legacy data). Before processing, if the slot has a pack_workstation set, it updates the Pack WO's operations that have an empty workstation.

**Pack slot matching logic:**
- If `number_of_pack` > 0: iterates idx 0..N-1, matching `wo.production_item` against `row.pack_name` (idx=0) or `row.pack_name_{idx+1}` (idx>0). Uses the matched slot's `actual_qty` / `actual_qty_{idx+1}` and `pack_workstation` / `pack_workstation_{idx+1}`.
- If `number_of_pack` = 0: legacy single-field mode using `row.pack_name`, `row.actual_qty`, `row.pack_workstation`.

**Balance distribution:** Only the **last** Pack WO (in sorted order) receives `row.balance` as `total_balance` for its Manufacture SE. All earlier Pack WOs get `total_balance=0` (scrap items removed from their SE).

**Inputs:**
- `row` — Daily Output Item child table row

**Links to:** `_process_single_wo()`, `_complete_wip_wo()`, `_set_workstation()`

---

### `DailyOutputRecord._validate_row(row)`

**What it does:** Validates a "Done" row by comparing the user-entered `actual_qty` (per pack slot) against the submitted Pack WO's `produced_qty`. On mismatch, shows a `frappe.msgprint` alert and adds a comment to the DOR timeline documenting the mismatch (WO name, expected produced_qty, entered actual_qty). Silently passes if everything matches.

**Pack slot matching logic:**
- If `number_of_pack` > 0: iterates idx 0..N-1, matching `pwo["production_item"]` against `row.pack_name` (idx=0) or `row.pack_name_{idx+1}` (idx>0). Skips slots where `actual_qty` is 0 or blank.
- If `number_of_pack` = 0: legacy single-field mode using `row.pack_name` + `row.actual_qty`.

**Inputs:**
- `row` — Daily Output Item child table row (must have status="Done")

**Links to:** `frappe.get_all("Work Order")`, `frappe.msgprint()`, `self.add_comment()`

---

### `DailyOutputRecord._process_single_wo(wo_name, total_balance, total_pack_qty, do_recook, recook_qty)`

**What it does:** Processes a single Work Order: submit -> Material Transfer SE -> Job Cards -> (Recook) -> Manufacture SE.

**Notes:**
- Material Transfer SE does **not** receive `total_balance` or `total_pack_qty` — it uses default fallback qty (`WO.qty - WO.produced_qty`)
- `total_balance` and `total_pack_qty` are only passed to the Manufacture SE

**Inputs:**
- `wo_name` (str) — Work Order name
- `total_balance` (float, default 0) — balance qty for Manufacture SE (Pack only)
- `total_pack_qty` (float, default 0) — pack qty for Manufacture SE (Pack only)
- `do_recook` (bool, default False) — whether to recook (Cook only)
- `recook_qty` (float, default 0) — recook quantity (Cook only)

**Links to:** `make_stock_entry()`, `create_recook_stock_entry_backend()`, `_process_job_cards()`

---

### `DailyOutputRecord._complete_wip_wo(wo_name)`

**What it does:** Processes a WIP Work Order: submit (if draft) -> Material Transfer SE -> Job Cards -> Manufacture SE. Same pipeline as `_process_single_wo` without recook/balance/pack_qty.

**Inputs:**
- `wo_name` (str) — Work Order name

**Links to:** `make_stock_entry()`, `_process_job_cards()`

---

### `DailyOutputRecord._set_workstation(wo_name, workstation)`

**What it does:** Helper that loads the Pack WO document and assigns the given `workstation` to any operation that has an empty workstation field. Saves only if changes were made.

**Inputs:**
- `wo_name` (str) — Pack Work Order name
- `workstation` (str) — Workstation name to assign

**Links to:** `frappe.get_doc("Work Order")`

---

### `DailyOutputRecord._process_job_cards(wo_name)`

**What it does:** Finds all draft Job Cards for a Work Order and processes each: creates start time log, creates complete time log with completed qty, saves, then submits.

**Inputs:**
- `wo_name` (str) — Work Order name

**Links to:** `frappe.get_all("Job Card")`

---

## Client Script: `daily_output_record.js`

---

### `refresh(frm)`

**What it does:** When the document is submitted and has items:
1. Sets up **indicator colors** on the Status field in the child table grid via `grid.get_field("status").get_indicator` — blue for Done, red for Failed, orange for Pending
2. Adds a **"Process All"** button that calls `process_all()` synchronously with a freeze overlay ("Processing Work Orders..."). On success -> shows "All rows processed successfully" + reloads. On failure -> shows error with row number + reloads.

**Links to:** `DailyOutputRecord.process_all()`

---

### `date_of_output(frm)`

**What it does:** Auto-fetches **all** Cook WOs for the selected date (both draft and submitted — cancelled excluded), fetches sibling Pack WOs (also all except cancelled) and their operations, then populates one row per link_id with:
- link_id, work_order, workstation, round, size
- number_of_pack = count of Pack WOs for that link_id
- pack_name_N / pack_workstation_N for each pack slot (1..number_of_pack)
- **status = "Done"** if all Pack WOs for that link_id are already submitted (docstatus=1)

Leaves recook, balance, actual_qty_N, raw_matl empty for user input.

**Links to:** `frappe.client.get_list()` (Work Order), `frappe.client.get()` (Work Order with operations)

---

### `number_of_pack(frm, cdt, cdn)` (Daily Output Item)

**What it does:** When the user changes Number Of Pack, clears unused pack slot fields (pack_name_N, actual_qty_N, pack_workstation_N for N > new value) to avoid stale data.

**Links to:** `frappe.model.set_value()`
