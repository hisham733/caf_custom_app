# Production Schedule — QA Test Plan (Ship Readiness)

## How to Use

- Run each test step by step
- Mark ✅ if it passes, ❌ if it fails
- For failures, note exactly what you see and which step
- Test with a week that has existing data (not a fresh empty week)
- **New since last run:** Clear slot button (Sec 17), Copy→Paste (Sec 18), WhatsApp PNG templates New/Old (Sec 19), Caf Settings WAHA config + Test button (Sec 20), Send Schedule to WhatsApp (Sec 21)

---

## Section 1: Page Load & Navigation


| #   | Action                      | Expected Result                                                                    | Status |
| --- | --------------------------- | ---------------------------------------------------------------------------------- | ------ |
| 1.1 | Open `/production-schedule` | Page loads with current week, View Schedule mode                                   |        |
| 1.2 | Check round columns         | Each day shows R1, R2, R3 (or more if extra rounds exist)                          |        |
| 1.3 | Check workstation list      | All workstations listed in Metabase order                                          |        |
| 1.4 | Change week number          | Board reloads for the new week                                                     |        |
| 1.5 | Change year                 | Board reloads for the new year                                                     |        |
| 1.6 | Check day colors            | Mon-Sat have different background tints (blue, green, purple, yellow, orange, red) |        |
| 1.7 | Check past days             | Past days are grayed out with 60% opacity                                          |        |


---



## Section 2: View Mode (Read-Only)


| #   | Action                            | Result                                                                                         | Status |
| --- | --------------------------------- | ---------------------------------------------------------------------------------------------- | ------ |
| 2.1 | In View mode, click a recipe item | Opens **View** dialog — all fields greyed out, no Save button                                  |        |
| 2.2 | Check Yield (KG)                  | Shows correct BOM yield value                                                                  |        |
| 2.3 | Check Total Input (KG)            | Shows `raw_materials × size` value (e.g. size=50 → ~6500)                                      |        |
| 2.4 | Check Total Output (KG)           | Shows `Total Input × Yield (KG)` value (e.g. ~6500 × 1.2)                                      |        |
| 2.5 | Check Layout                      | Production → Recipe Note → Production Info (Yield → Total Input → Total Output) → Pack Details |        |
| 2.6 | Close dialog                      | Dialog closes, no save, board unchanged                                                        |        |


---



## Section 3: Edit Mode — Switch


| #   | Action                           | Result                                                          | Status |
| --- | -------------------------------- | --------------------------------------------------------------- | ------ |
| 3.1 | Switch to **Edit Schedule** mode | "Creating draft production plans..." freeze overlay shown       |        |
| 3.2 | Wait for load                    | Board reloads with draft DPs, "+" buttons appear on empty slots |        |
| 3.3 | Check "Add Extra Rounds" button  | Visible only in Edit mode, hidden in View mode                  |        |
| 3.4 | Switch back to View Schedule     | Board reloads with submitted DPs                                |        |


---



## Section 4: Add Recipe


| #    | Action                                   | Result                                                                              | Status |
| ---- | ---------------------------------------- | ----------------------------------------------------------------------------------- | ------ |
| 4.1  | In Edit mode, click "+" on an empty slot | Add Recipe dialog opens                                                             |        |
| 4.2  | Check workstation/round                  | Correct workstation and round shown (read-only)                                     |        |
| 4.3  | Check status                             | Default is "New Schedule"                                                           |        |
| 4.4  | Select a recipe                          | Recipe dropdown shows Recipe + WIP Floss items                                      |        |
| 4.5  | After selecting recipe                   | Yield (KG)                                                                          |        |
| 4.6  | Check Layout                             | Production → Recipe Note → Production Info → Pack Details → Number of Packs → Packs |        |
| 4.7  | Fill size, packs, and click Add          | Green "Recipe added" alert, board reloads                                           |        |
| 4.8  | Check board                              | New recipe appears in correct slot                                                  |        |
| 4.9  | Try Add without recipe                   | Error "Please select a recipe"                                                      |        |
| 4.10 | Try Add without size                     | Error "Please enter a valid size"                                                   |        |


---



## Section 5: Edit Recipe — Dialog


| #   | Action                           | Result                                                                                 | Status |
| --- | -------------------------------- | -------------------------------------------------------------------------------------- | ------ |
| 5.1 | Click a recipe item in Edit mode | Edit dialog opens                                                                      |        |
| 5.2 | Check top buttons                | **Copy** (filled slots) and **Clear** (no-WO slots) buttons appear side-by-side at top |        |
| 5.3 | Check Layout                     | Production → Recipe Note → Production Info → Pack Details → Number of Packs → Packs    |        |
| 5.4 | Check fields locked              | When no status selected, only `produ_status` dropdown is editable                      |        |
| 5.5 | Check "Recipe Change" status     | All production fields unlock                                                           |        |
| 5.6 | Check "Pack Change" status       | Only pack fields + number_of_pack unlock                                               |        |
| 5.7 | Check "Only Remark" status       | Only recipe_note + pack_remark fields unlock                                           |        |
| 5.8 | Change recipe_note, save         | Board reloads, note appears in Note column                                             |        |
| 5.9 | Edit size when locked            | Cannot edit — field is greyed out                                                      |        |


---



## Section 6: Statuses and Restrictions


| #   | Action                                  | Result                                                  | Status |
| --- | --------------------------------------- | ------------------------------------------------------- | ------ |
| 6.1 | Open edit dialog for recipe WITH WOs    | Status options: Recipe Change, Only Remark, Pack Change |        |
| 6.2 | Confirm "Cancelled" NOT in dropdown     | Cancelled option not visible                            |        |
| 6.3 | Confirm "Single WO" NOT in dropdown     | Single WO option not visible                            |        |
| 6.4 | Open edit dialog for recipe WITHOUT WOs | Status options: New Schedule, Recipe Change             |        |
| 6.5 | Open edit dialog for No Cooking slot    | Status options: New Schedule only                       |        |
| 6.6 | Select "Pack Change" on row with WOs    | Only pack fields editable                               |        |
| 6.7 | Change pack qty on "Pack Change"        | After save, board reloads, bg worker processes          |        |


---



## Section 7: Cancel Recipe


| #   | Action                       | Result                                            | Status |
| --- | ---------------------------- | ------------------------------------------------- | ------ |
| 7.1 | Edit a recipe that has WOs   | "Cancel Recipe" button visible in Actions section |        |
| 7.2 | Edit a recipe WITHOUT WOs    | "Cancel Recipe" button hidden                     |        |
| 7.3 | Click "Cancel Recipe" button | Confirm dialog appears                            |        |
| 7.4 | Cancel it                    | `rq_status` shows "Processing", board reloads     |        |
| 7.5 | After bg job completes       | Row reset to "No Cooking" (empty slot)            |        |


---



## Section 8: Change Slot & Rearrange


| #   | Action                                       | Result                                                                          | Status |
| --- | -------------------------------------------- | ------------------------------------------------------------------------------- | ------ |
| 8.1 | Drag recipe to another empty slot (same day) | "Save failed" shows real error OR "Moved" success                               |        |
| 8.2 | Drag recipe to slot in different day         | Cross-day move succeeds (no WOs) or fails with clear error (has WOs)            |        |
| 8.3 | After swap/rearrange                         | Both rows' produ_status and custom_pair_id cleared                              |        |
| 8.4 | Try to drag Completed Cook WO                | Error "Cook Work Order is already Completed. Cannot change slot." shown clearly |        |
| 8.5 | Try to drag Processing row                   | Error about processing shown                                                    |        |


---



## Section 9: Add Extra Rounds


| #   | Action                                        | Result                                                                | Status |
| --- | --------------------------------------------- | --------------------------------------------------------------------- | ------ |
| 9.1 | In Edit mode, click "Add Extra Rounds" button | Dialog opens with Day, Workstation, Total Rounds                      |        |
| 9.2 | Enter total_rounds = 2                        | Red alert "Total rounds must be greater than 3" — dialog stays open   |        |
| 9.3 | Enter total_rounds = 100                      | Red alert "Total rounds cannot exceed 99" — dialog stays open         |        |
| 9.4 | Pick a day, workstation, total_rounds = 5     | Green alert, board reloads                                            |        |
| 9.5 | Check that day                                | Extra round columns R4, R5 appear (but only for that workstation)     |        |
| 9.6 | Check other workstations                      | R4, R5 show "—" (not "+") — cannot add recipes to non-existing rounds |        |
| 9.7 | Day column colors still correct               | All columns have proper day tints                                     |        |
| 9.8 | Check Schedule Change Log                     | Log entry shows "Add Rounds" action with workstation and rounds       |        |


---



## Section 10: Submit Week


| #    | Action                            | Result                                                      | Status |
| ---- | --------------------------------- | ----------------------------------------------------------- | ------ |
| 10.1 | In Edit mode, click "Submit Week" | Confirm dialog appears                                      |        |
| 10.2 | Confirm submit                    | All DPs set to Submitted state, board switches to View mode |        |
| 10.3 | All empty rows (No Cooking only)  | Submit fails with "All rows have No Cooking — not allowed"  |        |


---



## Section 11: Create Work Orders


| #    | Action                                   | Result                                                     | Status |
| ---- | ---------------------------------------- | ---------------------------------------------------------- | ------ |
| 11.1 | In View mode, "Create WO" button visible | Each day shows button                                      |        |
| 11.2 | Click "Create WO" for a day with changes | Confirm → Loading → Success alert → board reloads          |        |
| 11.3 | After WO creation                        | All produ_status values cleared (rows back to clean state) |        |
| 11.4 | Create WO on day with no changes         | Should still succeed (no-op)                               |        |


---



## Section 12: Error Messages & Edge Cases


| #    | Action                                              | Result                                                                         | Status |
| ---- | --------------------------------------------------- | ------------------------------------------------------------------------------ | ------ |
| 12.1 | Trigger a validation error (e.g. drag Completed WO) | Error message shows actual server error, NOT generic "Save failed — reloading" |        |
| 12.2 | Wait for bg job to finish                           | `rq_status` shows "Done" or "Failed" with error in badge                       |        |
| 12.3 | Click "Failed" badge on a row                       | Error dialog opens showing `custom_wo_error`                                   |        |
| 12.4 | Click "Retry" on failed row                         | Background job re-queued                                                       |        |
| 12.5 | Refresh page mid-edit                               | Should not corrupt data (autosave or clear)                                    |        |


---



## Section 13: Pack Weight Validation


| #    | Action                                               | Result                                                  | Status |
| ---- | ---------------------------------------------------- | ------------------------------------------------------- | ------ |
| 13.1 | Add recipe with 2+ packs where total weight > output | Inline red error appears below pack fields (add dialog) |        |
| 13.2 | Same in edit dialog                                  | Red message shown when saving (edit dialog)             |        |
| 13.3 | Reduce pack qty                                      | Error clears when total weight fits                     |        |
| 13.4 | Increase size                                        | Error clears when output is sufficient                  |        |


---



## Section 14: DP Form (Daily Production)


| #    | Action                                   | Result                                                                                                         | Status |
| ---- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------ |
| 14.1 | Open a DP from View mode (click DP link) | DP form loads with all rows                                                                                    |        |
| 14.2 | Check grid columns                       | Workstation → Cook Round → Produ Status → Recipe → Size → Yield → Total Input → Total Output → Number of Packs |        |
| 14.3 | Check problem workstation rows           | Red tint + 65% opacity, all fields locked                                                                      |        |
| 14.4 | Select a recipe                          | `total_input = raw_materials × size` and `total_output = total_input × yield` populate                         |        |
| 14.5 | Change size                              | `total_input` and `total_output` recompute                                                                     |        |
| 14.6 | Set produ_status and save                | Auto-processing triggers if WOs exist (loading overlay)                                                        |        |
| 14.7 | Check "Add Extra Round" button           | Visible on DP form, filtered to machine table workstations                                                     |        |
| 14.8 | Try total_rounds = 2                     | Blocked with red alert                                                                                         |        |
| 14.9 | Add valid extra round                    | Rows added, form reloads                                                                                       |        |


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
| 16.1 | All 7 scenarios                | No errors                       |        |
| 16.2 | `process_manual_updates` works | Creates MR + WOs without errors |        |
| 16.3 | `add_extra_round` works        | Adds multiple rounds correctly  |        |
| 16.4 | Cancellation works             | WOs cancelled, row reset        |        |
| 16.5 | Swap works                     | Recipes swap correctly          |        |


---



## Section 17: Clear Slot Button


| #    | Action                                                      | Result                                                                  | Status |
| ---- | ----------------------------------------------------------- | ----------------------------------------------------------------------- | ------ |
| 17.1 | Edit dialog of a recipe slot WITHOUT Work Orders (no MR/PP) | "Clear" button visible at the top, side-by-side with "Copy"             |        |
| 17.2 | Edit dialog of a recipe slot WITH Work Orders (MR set)      | "Clear" button hidden                                                   |        |
| 17.3 | Click "Clear"                                               | Slot resets immediately (no confirm) — recipe/size/packs/status cleared |        |
| 17.4 | After clear                                                 | Row shows the "+" empty slot; board reloads                             |        |
| 17.5 | Add dialog on an empty slot                                 | "Clear" button also present at the top                                  |        |
| 17.6 | Click Clear in the Add dialog                               | Slot stays / becomes a clean No Cooking slot                            |        |
| 17.7 | Clear while `rq_status` is Processing                       | Blocked with "Work Orders are being processed. Please wait."            |        |


---



## Section 18: Copy & Paste Slot


| #     | Action                                   | Result                                                                                      | Status |
| ----- | ---------------------------------------- | ------------------------------------------------------------------------------------------- | ------ |
| 18.1  | Edit dialog of a filled recipe slot      | "Copy" button visible at the top, side-by-side with "Clear"                                 |        |
| 18.2  | Click "Copy"                             | Dialog closes; board enters paste mode (empty slots highlight green dashed + status banner) |        |
| 18.3  | Click an empty slot                      | **Add dialog opens PRE-FILLED** with the copied recipe, size, packs, type, urgent, note     |        |
| 18.4  | Verify no auto-save                      | Board is NOT updated until you click Add                                                    |        |
| 18.5  | Click "Add" in the pre-filled dialog     | Recipe saved to that slot with "New Schedule"; board reloads                                |        |
| 18.6  | Source slot unchanged                    | Original recipe still in its slot                                                           |        |
| 18.7  | Paste, then click "Clear" instead of Add | Slot cleared (nothing saved)                                                                |        |
| 18.8  | Press Esc during paste mode              | Paste cancelled; banner clears; board back to normal                                        |        |
| 18.9  | Click a FILLED slot during paste mode    | Paste cancelled (no edit dialog opens)                                                      |        |
| 18.10 | Copy button on a No Cooking slot         | Copy button not shown (only for filled recipe slots)                                        |        |
| 18.11 | Verify target keeps its own `link_id`    | Pasted slot's link_id is NOT taken from the source                                          |        |


---



## Section 19: WhatsApp PNG Template


| #    | Action                                        | Result                                                                                                                               | Status |
| ---- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| 19.1 | Caf Settings → DP WhatsApp Template = **New** | Sent PNG has NO Recipe column; per round **Product then Size**; Product shows the recipe name without the word "Recipe" (e.g. "IBS") |        |
| 19.2 | Caf Settings → DP WhatsApp Template = **Old** | Sent PNG shows **Recipe                                                                                                              | Size   |
| 19.3 | Workstation labels                            | "Cooker 2 Oil" → "C2", "Cooker 7 Gas" → "C7" (index extracted despite Oil/Gas suffix)                                                |        |
| 19.4 | Switch template, then send again              | Next notification uses the selected template                                                                                         |        |


---



## Section 20: Caf Settings — WAHA Config & Test


| #    | Action                                                | Result                                                               | Status |
| ---- | ----------------------------------------------------- | -------------------------------------------------------------------- | ------ |
| 20.1 | Open `/app/caf-settings`                              | Form loads with WhatsApp (WAHA) + Daily Production WhatsApp sections |        |
| 20.2 | Enter base_url, chat_ids (one per line), api_key      | Saves successfully                                                   |        |
| 20.3 | Enter more than one chat ID                           | Multiple IDs accepted (one per line)                                 |        |
| 20.4 | Click "Test WhatsApp" with typed values (BEFORE save) | Test message sent to each chat ID using the typed values             |        |
| 20.5 | Save, reload the page, click "Test WhatsApp" AGAIN    | Still sends — API key falls back to the saved record (masked field)  |        |
| 20.6 | Enter a wrong API key                                 | Real error shown (e.g. "HTTP 401: ..."), no retry                    |        |
| 20.7 | Test with empty base_url / no chat IDs                | Clear validation message                                             |        |
| 20.8 | Test while "WhatsApp Enabled" is unchecked            | Still works (test bypasses the enabled flag)                         |        |


---



## Section 21: Send Schedule to WhatsApp


| #    | Action                                  | Result                                                            | Status |
| ---- | --------------------------------------- | ----------------------------------------------------------------- | ------ |
| 21.1 | Toolbar "Send Schedule" button          | Dialog opens with a day list; days with WOs show "✓ WO"           |        |
| 21.2 | Pick a day with no Daily Production     | Error "No Daily Production for ..."                               |        |
| 21.3 | Pick a day that is not Submitted        | Error "... is not Submitted yet. Please Submit it first."         |        |
| 21.4 | Pick a day Submitted but no Work Orders | Error "Work Orders are not created ... Please Create WO first."   |        |
| 21.5 | Pick a valid day (Submitted + WOs)      | Green alert; WhatsApp receives the DP schedule image for that day |        |


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
| 17. Clear Slot           | Yes       |        |
| 18. Copy & Paste         | Yes       |        |
| 19. WhatsApp Template    | No        |        |
| 20. Caf Settings / WAHA  | No        |        |
| 21. Send Schedule        | No        |        |


**All critical sections must pass to ship.**