# Why WPD Needs Background Jobs (RQ)

## The Problem

Planners make changes to production slots — edit recipe, change size, modify packs, swap slots, rearrange. Each change must be "documented" all the way to Work Orders (WO). If a Planner makes two changes to the same slot (e.g., change size, then 2 minutes later change number of packs), the **first change must complete before the second can start**.

## The Pipeline: Status → MR → PP → WO

Every status change triggers a chain:

```
Recipe Change / Pack Change / New Schedule / Cancelled / Rearrange
  ↓
Material Request (MR) creation
  ↓
Production Plan (PP) creation (BOM explosion)
  ↓
Work Order (WO) creation (Cook + Pack + WIP WOs)
  ↓
Write-back to row (mr_reference, wo_list, link_id)
```

## Why Not Synchronous?

| Approach | Time | UX |
|----------|------|-----|
| **Synchronous** (wait for complete) | 5–15 seconds per edit | Page freezes, browser blocked |
| **Async (RQ)** | 0.5–1 second return, 5–15s background | "Processing" badge, user can continue working |

The DP form uses synchronous processing with a loading overlay — acceptable for one DP. WPD handles 6 DPs × 64 rows = 384 slots. Blocking for 5-15 seconds per edit is unbearable.

## Why Sequential? (Why must recipe change complete before pack change?)

Each slot has a `link_id` (R-2026-XXXXX) that ties all its WOs together:

```
Slot: Cooker 3 Oil, Round 1, Recipe IB
  link_id: R-2026-07261
    ├── Cook WO:  MFG-WO-28547 (Recipe IB, type=Cook)
    ├── Pack WO:  MFG-WO-28548 (Bag IB, type=Pack)
    ├── Pack WO:  MFG-WO-28549 (CLS IB, type=Pack)
    ├── WIP WO:   MFG-WO-28550 (TIM IB 1, type=WIP)
    └── WIP WO:   MFG-WO-28551 (TIM MST, type=WIP)
```

**Scenario: Planner changes size, then changes packs**

```
1:00 PM: Planner changes size from 50 to 60
  → RQ enqueues _background_change_recipe
  → Cancels old Cook/Pack WOs (link_id: R-2026-07261)
  → Creates new MR → PP → Cook WO + Pack WOs
  → New link_id points to new WOs
  → Time: ~5 seconds

1:02 PM: Planner changes number_of_pack from 3 to 5
  → RQ enqueues _background_pack_change
  → Checks: are WOs for link_id R-2026-07261 ready?
  → If recipe change job still running → old WOs partially cancelled → ERROR
  → If recipe change job completed → new WOs exist → cancel old Pack WOs → recreate
```

**Without proper sequencing:** The pack change tries to modify WOs that are being cancelled/recreated by the recipe change. This corrupts the WO chain.

## How RQ Ensures Sequencing

1. Planner saves status change
2. `rq_status` set to `"Processing"` immediately
3. Background job enqueued
4. UI shows "Processing" badge — Planner sees slot is busy
5. Planner tries to edit again → blocked because `rq_status == "Processing"`
6. Background job completes → `rq_status = "Done"` or `"Failed"`
7. Slot unlocked — Planner can make next change

## What Happens Under Each Status

| Status | Background Worker | What It Does | Time |
|--------|------------------|-------------|------|
| **New Schedule** | `_background_create_mr` | Build full MR→PP→WO chain, 8+ WOs with BOM explosion | 2–5s |
| **Recipe Change** | `_background_change_recipe` | Cancel old Cook/Pack, recreate full chain | 3–8s |
| **Pack Change** | `_background_pack_change` | Cancel only Pack WOs, recreate only Pack WOs | 0.5–2s |
| **Cancelled** | `_background_cancel_item` | Cancel ALL WOs/SEs/JCs, reset slot to No Cooking | 5–15s 🚨 |
| **Rearrange** | `_background_swap_recipes` | Swap link_ids between two slots, recreate | 5–10s |
| **Change Slot** | `_background_move_wo_migration` | Migrate link_id from source to target | 0.5–2s |

## When Is RQ Absolutely Necessary?

### Critical: MUST use RQ
- **Recipe Change** + **Pack Change** on same slot within minutes
- **New Schedule** → immediate WO creation needed for next planner action
- **Cancel** → frees the slot for reuse
- Two planners editing adjacent slots → race condition

### Optional: Could be synchronous
- Final edit before "Create WO" button (processing all changes at once)
- "Only Remark" changes (no WO impact)
- Single Edit mode where planner works alone

## Current State

| Item | Status |
|------|--------|
| RQ for WPD status changes | ✅ Active |
| DP form auto-processing | ✅ Synchronous with overlay |
| Performance | 2–15s per job |
| Cancellation | Slowest — needs optimization |
| All workers on `long` queue | No priority separation |

## Could We Remove RQ?

**Yes, if we:**

1. Make all edits synchronous with loading overlay (like DP form)
2. Accept 5–15 second freezes per edit
3. Remove the ability to make sequential edits to the same slot
4. OR combine all changes into a single "batch process" action

**No, because:**

1. WPD handles 6× more data than a single DP form
2. Planners routinely make sequential changes (size → packs → recipe)
3. Multiple planners may work on the same week simultaneously
4. 15-second freezes on a schedule board are unacceptable UX
