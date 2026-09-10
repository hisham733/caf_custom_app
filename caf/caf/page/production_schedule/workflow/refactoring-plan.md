# Production Schedule — Performance Refactoring Summary

## What We Did

The Production Schedule page and Daily Production form were slow — every click took 1-2 seconds and created 150+ database queries. We reduced most operations by **90%+**.

## Results: Before vs After

| Action | Before | After | Improvement |
|--------|--------|-------|-------------|
| Loading the week page | 16 queries | **7 queries** | 56% faster |
| Editing one field (save) | 162 queries | **14 queries** | 91% faster |
| Cancelling a recipe | 105 queries | **9 queries** | 91% faster |
| Adding a new recipe | 106 queries | **9 queries** | 92% faster |
| Swapping two recipes | 8 queries | **8 queries** | already fast |

## What Changed (Simple Terms)

### Phase 1 — Load Page Faster
- Instead of asking the database 6 times (once per day), we ask once for all 6 days
- Saved 10 queries per page load

### Phase 2 — Save Edits Faster  
- Instead of loading the entire document (64 rows) just to change 1 field, we update only the changed row
- 3 functions rewritten: `save_item_fields`, `save_update_item`, `cancel_item`

### Phase 3 — Stop Reloading the Same Data
- Functions were loading the same document from the database multiple times
- Now we pass the already-loaded document around instead of re-loading it
- Fixed a bug where Material Requests were submitted twice

### Phase 4 — Batch Operations
- Removed duplicate processing calls (`rws` was called 3 times, now called once)
- Changed "query each item one-by-one" to "query all at once" in several places

### Phase 6 — Cleanup  
- Removed 63 debug print statements
- Removed 5 unused imports

## Files Changed

| File | What |
|------|------|
| `production_schedule.py` | Main page logic — refactored saves, log, add rounds |
| `daily_production.py` | DP document — refactored updates, workflow, validation |
| `change_size.py` | Recipe/size changes — stop reloading |
| `change_pack.py` | Pack changes — stop reloading |
| `rearrange_and_change_slot.py` | Swap/rearrange — stop reloading, clear status after done |
| `rws.py` | Note sync — accept doc object |
| `production_schedule.js` | WPD page JS — add rounds dialog, freeze overlay, day colors fix, dialog layout |
| `daily_production.js` | DP form JS — auto-save processing, pack validation, workstation status |
| `production_schedule.css` | Removed hardcoded column colors |
| `create_proexl_items.json` | Added `total_input` and `total_output` fields |
| `production_plan.py` | Fixed double-submit bug |
| `production_schedule_change_log.js` | Show Add Rounds in log page |

## How to Test

```bash
bench --site development.localhost execute caf.caf.page.production_schedule.workflow.perf_test.perf_test
```

This runs 7 test scenarios and shows queries + time for each. Run before and after any future changes to compare.

## What Was NOT Done

- **Phase 5 (JS optimization)**: Debouncing, targeted DOM updates, `async: false` removal — too risky to change
- **Full cancellation overhaul**: The cancellation code still has per-WO loads — complex and risky

## Notes for IT

- Back up the database before applying changes
- Test on a staging site first
- If something breaks: all changes are in the `caf` app under `apps/caf/caf/`
- The `perf_test.py` script automatically creates test data — safe to run multiple times
