# `daily_output_record/` — Daily Output Record DocType

## Purpose

Captures actual production output per link ID. After the production team executes work on the floor, the user selects a date, the system auto-fetches all Cook WOs for that date (including already-submitted ones), and the user fills in actual_qty per pack slot, recook, balance, and raw_matl. Rows whose Pack WOs are already submitted are auto-marked "Done" so the user can still enter actual quantities for reporting. A "Process All" button enqueues a background job that automates Stock Entry creation for pending rows, validates qty match for already-Done rows, and writes any errors as comments to the DOR timeline.

## Location

```
apps/caf/caf/caf/doctype/daily_output_record/
```

## Files

| File | Purpose |
|------|---------|
| `daily_output_record.json` | DocType definition — fields, permissions, naming series, processing_status/processing_error |
| `daily_output_record.py` | Python controller — `process_all()`, `enqueue_process_all()`, `run_process_all_background()`, pack slot matching, validation |
| `daily_output_record.js` | Client script — background enqueue, status polling, indicator colors, auto-populate pack slots on date change |
| `__init__.py` | Package init (empty) |

## Child Table

| File | Location |
|------|----------|
| `daily_output_item/daily_output_item.json` | Child table fields: link_id, work_order, workstation, round, size, number_of_pack, pack_name_N, pack_workstation_N, actual_qty_N (N=1..7), recook, balance, raw_matl, status |
| `daily_output_item/daily_output_item.py` | Child table controller (empty) |

## How It Works

1. User opens Daily Output Record form
2. Client Script auto-fetches **all** Cook WOs for selected `date_of_output` (draft + submitted, cancelled excluded)
3. One row per link_id is created: Cook WO name, workstation, round, size, `number_of_pack`, and pack slots (pack_name_N, pack_workstation_N) populated from sibling Pack WOs
4. Rows auto-marked **"Done"** (blue) if all Pack WOs for that link_id are already submitted
5. User enters: recook, balance, actual_qty per pack slot, raw_matl
6. User submits the document
7. User clicks **"Process All"** -> job is **enqueued as a background RQ job** (no browser freeze)
8. Button changes to "Processing...", form polls every 3s for status updates
9. Server-side `run_process_all_background()` calls `process_all()` which iterates rows:
   - **Pending rows** -> processes WIP -> Cook -> Pack per link_id; each Pack WO matched to its slot by production_item; Material Transfer + Manufacture SEs created and submitted; Job Cards time-logged and submitted
   - **Done rows** -> validates actual_qty vs Pack WO produced_qty; on mismatch shows warning + adds comment to DOR timeline
10. On completion -> form auto-reloads with success or failure message
11. On failure -> error stored in `processing_error` field + comment added to DOR timeline
12. Each row gets status: `Done` (blue), `Pending` (orange), or `Failed` (red)

## Test Coverage

19 tests in `test_daily_output_record.py`:
- 8 `_validate_row` tests (match, mismatch, multi-slot, legacy, no WOs, no actual_qty)
- 4 `_set_workstation` tests (empty op, already set, no ops, mixed ops)
- 3 `process_all` integration tests (no WOs, already done, mixed rows)
- 4 enqueue/background tests (throws if in progress, sets status + queues, completed on success, failed with comment)

Run: `bench --site development.localhost run-tests --skip-before-tests --module caf.caf.doctype.daily_output_record.test_daily_output_record`

## Dependencies

- `caf.caf.overrides.work_order.make_stock_entry` — custom SE generation
- `caf.caf.overrides.work_order.create_recook_stock_entry_backend` — recook logic
- `frappe.enqueue` / RQ workers — background job processing
- `Work Order`, `Job Card`, `Stock Entry` — standard ERPNext doctypes
