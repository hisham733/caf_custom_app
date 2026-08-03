# Production Schedule — QA Test Plan (Ship Readiness)

## How to Use

- Run each test step by step
- Mark ✅ if it passes, ❌ if it fails
- For failures, note exactly what you see and which step
- Test with a week that has existing data (not a fresh empty week)

---

## Section 1: Page Load & Navigation


| #   | Action                      | Expected Result                                                                    | Status                                     |
| --- | --------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------ |
| 1.1 | Open `/production-schedule` | Page loads with current week, View Schedule mode                                   | pass                                       |
| 1.2 | Check round columns         | Each day shows R1, R2, R3 (or more if extra rounds exist)                          | pass                                       |
| 1.3 | Check workstation list      | All workstations listed in Metabase order                                          | pass                                       |
| 1.4 | Change week number          | Board reloads for the new week                                                     | pass                                       |
| 1.5 | Change year                 | Board reloads for the new year                                                     | pass                                       |
| 1.6 | Check day colors            | Mon-Sat have different background tints (blue, green, purple, yellow, orange, red) | colors so light can not see the diff easly |
| 1.7 | Check past days             | Past days are grayed out with 60% opacity                                          | pass                                       |


---



## Section 2: View Mode (Read-Only)


| #   | Action                            | Result                                                                                         | Status |
| --- | --------------------------------- | ---------------------------------------------------------------------------------------------- | ------ |
| 2.1 | In View mode, click a recipe item | Opens **View** dialog — all fields greyed out, no Save button                                  | pass   |
| 2.2 | Check Yield (KG)                  | Shows correct BOM yield value                                                                  | pass   |
| 2.3 | Check Total Input (KG)            | Shows `raw_materials × size` value (e.g. size=50 → ~6500)                                      | pass   |
| 2.4 | Check Total Output (KG)           | Shows `Total Input × Yield (KG)` value (e.g. ~6500 × 1.2)                                      | pass   |
| 2.5 | Check Layout                      | Production → Recipe Note → Production Info (Yield → Total Input → Total Output) → Pack Details | pass   |
| 2.6 | Close dialog                      | Dialog closes, no save, board unchanged                                                        | pass   |


---



## Section 3: Edit Mode — Switch


| #   | Action                           | Result                                                          | Status |
| --- | -------------------------------- | --------------------------------------------------------------- | ------ |
| 3.1 | Switch to **Edit Schedule** mode | "Creating draft production plans..." freeze overlay shown       | pass   |
| 3.2 | Wait for load                    | Board reloads with draft DPs, "+" buttons appear on empty slots | pass   |
| 3.3 | Check "Add Extra Rounds" button  | Visible only in Edit mode, hidden in View mode                  | pass   |
| 3.4 | Switch back to View Schedule     | Board reloads with submitted DPs                                | pass   |


---



## Section 4: Add Recipe


| #    | Action                                   | Result                                                                              | Status |
| ---- | ---------------------------------------- | ----------------------------------------------------------------------------------- | ------ |
| 4.1  | In Edit mode, click "+" on an empty slot | Add Recipe dialog opens                                                             | pass   |
| 4.2  | Check workstation/round                  | Correct workstation and round shown (read-only)                                     | pass   |
| 4.3  | Check status                             | Default is "New Schedule"                                                           | pass   |
| 4.4  | Select a recipe                          | Recipe dropdown shows Recipe + WIP Floss items                                      | pass   |
| 4.5  | After selecting recipe                   | Yield (KG)                                                                          | pass   |
| 4.6  | Check Layout                             | Production → Recipe Note → Production Info → Pack Details → Number of Packs → Packs | pass   |
| 4.7  | Fill size, packs, and click Add          | Green "Recipe added" alert, board reloads                                           | pass   |
| 4.8  | Check board                              | New recipe appears in correct slot                                                  | pass   |
| 4.9  | Try Add without recipe                   | Error "Please select a recipe"                                                      | pass   |
| 4.10 | Try Add without size                     | Error "Please enter a valid size"                                                   | pass   |


---



## Section 5: Edit Recipe — Dialog


| #   | Action                           | Result                                                                              | Status |
| --- | -------------------------------- | ----------------------------------------------------------------------------------- | ------ |
| 5.1 | Click a recipe item in Edit mode | Edit dialog opens                                                                   | pass   |
| 5.2 | Check Layout                     | Production → Recipe Note → Production Info → Pack Details → Number of Packs → Packs | pass   |
| 5.3 | Check fields locked              | When no status selected, only `produ_status` dropdown is editable                   | pass   |
| 5.4 | Check "Recipe Change" status     | All production fields unlock                                                        | pass   |
| 5.5 | Check "Pack Change" status       | Only pack fields + number_of_pack unlock                                            | pass   |
| 5.6 | Check "Only Remark" status       | Only recipe_note + pack_remark fields unlock                                        | pass   |
| 5.7 | Change recipe_note, save         | Board reloads, note appears in Note column                                          | pass   |
| 5.8 | Edit size when locked            | Cannot edit — field is greyed out                                                   | pass   |


---



## Section 6: Statuses and Restrictions


| #   | Action                                  | Result                                                  | Status |
| --- | --------------------------------------- | ------------------------------------------------------- | ------ |
| 6.1 | Open edit dialog for recipe WITH WOs    | Status options: Recipe Change, Only Remark, Pack Change | pass   |
| 6.2 | Confirm "Cancelled" NOT in dropdown     | Cancelled option not visible                            | pass   |
| 6.3 | Confirm "Single WO" NOT in dropdown     | Single WO option not visible                            | pass   |
| 6.4 | Open edit dialog for recipe WITHOUT WOs | Status options: New Schedule, Recipe Change             | pass   |
| 6.5 | Open edit dialog for No Cooking slot    | Status options: New Schedule only                       | pass   |
| 6.6 | Select "Pack Change" on row with WOs    | Only pack fields editable                               | pass   |
| 6.7 | Change pack qty on "Pack Change"        | After save, board reloads, bg worker processes          | pass   |


---



## Section 7: Cancel Recipe


| #   | Action                       | Result                                            | Status |
| --- | ---------------------------- | ------------------------------------------------- | ------ |
| 7.1 | Edit a recipe that has WOs   | "Cancel Recipe" button visible in Actions section | pass   |
| 7.2 | Edit a recipe WITHOUT WOs    | "Cancel Recipe" button hidden                     | pass   |
| 7.3 | Click "Cancel Recipe" button | Confirm dialog appears                            | pass   |
| 7.4 | Cancel it                    | `rq_status` shows "Processing", board reloads     | pass   |
| 7.5 | After bg job completes       | Row reset to "No Cooking" (empty slot)            | pass   |


---



## Section 8: Change Slot & Rearrange


| #   | Action                                       | Result                                                                          | Status |
| --- | -------------------------------------------- | ------------------------------------------------------------------------------- | ------ |
| 8.1 | Drag recipe to another empty slot (same day) | "Save failed" shows real error OR "Moved" success                               | pass   |
| 8.2 | Drag recipe to slot in different day         | Cross-day move succeeds (no WOs) or fails with clear error (has WOs)            | pass   |
| 8.3 | After swap/rearrange                         | Both rows' produ_status and custom_pair_id cleared                              | pass   |
| 8.4 | Try to drag Completed Cook WO                | Error "Cook Work Order is already Completed. Cannot change slot." shown clearly | pass   |
| 8.5 | Try to drag Processing row                   | Error about processing shown                                                    | pass   |


---



## Section 9: Add Extra Rounds


| #   | Action                                        | Result                                                                | Status |
| --- | --------------------------------------------- | --------------------------------------------------------------------- | ------ |
| 9.1 | In Edit mode, click "Add Extra Rounds" button | Dialog opens with Day, Workstation, Total Rounds                      | pass   |
| 9.2 | Enter total_rounds = 2                        | Red alert "Total rounds must be greater than 3" — dialog stays open   | pass   |
| 9.3 | Enter total_rounds = 100                      | Red alert "Total rounds cannot exceed 99" — dialog stays open         | pass   |
| 9.4 | Pick a day, workstation, total_rounds = 5     | Green alert, board reloads                                            | pass   |
| 9.5 | Check that day                                | Extra round columns R4, R5 appear (but only for that workstation)     | pass   |
| 9.6 | Check other workstations                      | R4, R5 show "—" (not "+") — cannot add recipes to non-existing rounds | pass   |
| 9.7 | Day column colors still correct               | All columns have proper day tints                                     | pass   |
| 9.8 | Check Schedule Change Log                     | Log entry shows "Add Rounds" action with workstation and rounds       | pass   |


---



## Section 10: Submit Week


| #    | Action                            | Result                                                      | Status |
| ---- | --------------------------------- | ----------------------------------------------------------- | ------ |
| 10.1 | In Edit mode, click "Submit Week" | Confirm dialog appears                                      | pass   |
| 10.2 | Confirm submit                    | All DPs set to Submitted state, board switches to View mode | pass   |
| 10.3 | All empty rows (No Cooking only)  | Submit fails with "All rows have No Cooking — not allowed"  | pass   |


---



## Section 11: Create Work Orders


| #    | Action                                   | Result                                                     | Status       |
| ---- | ---------------------------------------- | ---------------------------------------------------------- | ------------ |
| 11.1 | In View mode, "Create WO" button visible | Each day shows button                                      | pass         |
| 11.2 | Click "Create WO" for a day with changes | Confirm → Loading → Success alert → board reloads          | pass         |
| 11.3 | After WO creation                        | All produ_status values cleared (rows back to clean state) | pass         |
| 11.4 | Create WO on day with no changes         | Should still succeed (no-op)                               |              |


---



## Section 12: Error Messages & Edge Cases


| #    | Action                                              | Result                                                                         | Status |
| ---- | --------------------------------------------------- | ------------------------------------------------------------------------------ | ------ |
| 12.1 | Trigger a validation error (e.g. drag Completed WO) | Error message shows actual server error, NOT generic "Save failed — reloading" | pass   |
| 12.2 | Wait for bg job to finish                           | `rq_status` shows "Done" or "Failed" with error in badge                       | pass   |
| 12.3 | Click "Failed" badge on a row                       | Error dialog opens showing `custom_wo_error`                                   | pass   |
| 12.4 | Click "Retry" on failed row                         | Background job re-queued                                                       | pass   |
| 12.5 | Refresh page mid-edit                               | Should not corrupt data (autosave or clear)                                    |        |


---



## Section 13: Pack Weight Validation


| #    | Action                                               | Result                                                  | Status |
| ---- | ---------------------------------------------------- | ------------------------------------------------------- | ------ |
| 13.1 | Add recipe with 2+ packs where total weight > output | Inline red error appears below pack fields (add dialog) | pass   |
| 13.2 | Same in edit dialog                                  | Red message shown when saving (edit dialog)             | pass   |
| 13.3 | Reduce pack qty                                      | Error clears when total weight fits                     | pass   |
| 13.4 | Increase size                                        | Error clears when output is sufficient                  | pass   |


---



## Section 14: DP Form (Daily Production)


| #    | Action                                   | Result                                                                                                         | Status |
| ---- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------ |
| 14.1 | Open a DP from View mode (click DP link) | DP form loads with all rows                                                                                    | pass   |
| 14.2 | Check grid columns                       | Workstation → Cook Round → Produ Status → Recipe → Size → Yield → Total Input → Total Output → Number of Packs | pass   |
| 14.3 | Check problem workstation rows           | Red tint + 65% opacity, all fields locked                                                                      | pass   |
| 14.4 | Select a recipe                          | `total_input = raw_materials × size` and `total_output = total_input × yield` populate                         | pass   |
| 14.5 | Change size                              | `total_input` and `total_output` recompute                                                                     | pass   |
| 14.6 | Set produ_status and save                | Auto-processing triggers if WOs exist (loading overlay)                                                        | pass   |
| 14.7 | Check "Add Extra Round" button           | Visible on DP form, filtered to machine table workstations                                                     | pass   |
| 14.8 | Try total_rounds = 2                     | Blocked with red alert                                                                                         | pass   |
| 14.9 | Add valid extra round                    | Rows added, form reloads                                                                                       | pass   |


---



## Section 15: Performance Check

Run before and after to compare:

```bash
bench --site development.localhost execute caf.caf.page.production_schedule.workflow.perf_test.perf_test
```


| Scenario              | Acceptable Queries | Status |
| --------------------- | ------------------ | ------ |
| Page Load             | ≤ 10               |        |
| Single Edit           | ≤ 20               |        |
| Cancel                | ≤ 15               |        |
| Swap                  | ≤ 15               |        |
| Add Recipe            | ≤ 160              |        |
| WO Pipeline (clean)   | ≤ 30               |        |
| WO Pipeline (changes) | ≤ 35               |        |


---



## Section 16: Python Backend (run once)

```bash
bench --site development.localhost execute caf.caf.page.production_schedule.workflow.perf_test.perf_test
```


| #    | Check                          | Expected                        | Status |
| ---- | ------------------------------ | ------------------------------- | ------ |
| 16.1 | All 7 scenarios pass           | No errors                       |        |
| 16.2 | `process_manual_updates` works | Creates MR + WOs without errors |        |
| 16.3 | `add_extra_round` works        | Adds multiple rounds correctly  |        |
| 16.4 | Cancellation works             | WOs cancelled, row reset        |        |
| 16.5 | Swap works                     | Recipes swap correctly          |        |


---



## Summary


| Section                  | Critical? | Status |
| ------------------------ | --------- | ------ |
| 1. Page Load             | Yes       |        |
| 2. View Mode             | Yes       |        |
| 3. Edit Mode Switch      | Yes       |        |
| 4. Add Recipe            | Yes       |        |
| 5. Edit Dialog           | Yes       |        |
| 6. Statuses              | Yes       |        |
| 7. Cancel                | Yes       |        |
| 8. Change Slot/Rearrange | Yes       |        |
| 9. Add Extra Rounds      | No        |        |
| 10. Submit Week          | Yes       |        |
| 11. Create WO            | Yes       |        |
| 12. Errors               | Yes       |        |
| 13. Pack Validation      | No        |        |
| 14. DP Form              | No        |        |
| 15. Performance          | No        |        |
| 16. Python Backend       | No        |        |


**All critical sections must pass to ship.**