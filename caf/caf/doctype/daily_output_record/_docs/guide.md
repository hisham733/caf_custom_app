# Daily Output Record — User Guide

> How to enter production data and process Work Orders.

## Step 1: Create a New Record

1. Go to **Daily Output Record** list
2. Click **Add Daily Output Record**
3. Set **Date Of Output** to the production date

## Step 2: Auto-Fetch Work Orders & Pack Slots

When you select a date, the system automatically:
- Fetches **all Cook WOs** with that planned_start_date (both draft and already submitted — cancelled WOs are excluded)
- Looks up the sibling **Pack WO(s)** for each link_id (both draft and submitted — cancelled excluded)
- Fetches each Pack WO's first operation workstation
- Creates **one row per link_id** (not per Pack WO)
- Populates **Number Of Pack** with the count of Pack WOs found
- Fills each **pack slot** (1..Number Of Pack) with:
  - **Pack Name** / **Pack Name N** — the Pack WO's production item
  - **Pack Workstation** / **Pack Workstation N** — the Pack WO's first operation workstation
- **Auto-marks Status as "Done"** (blue) if all Pack WOs for that link_id are already submitted — this lets you re-enter actual quantities for reporting without re-processing

If no WOs are found for the date, a message will appear.

## Step 3: Enter Production Data

For each row, fill in the **pack slots** that appear based on **Number Of Pack**:

| Slot | Fields (show when Number Of Pack >= N) |
|------|----------------------------------------|
| Pack 1 | **Pack Name**, **Actual QTY**, **Pack Workstation** |
| Pack 2 | **Pack Name 2**, **Actual QTY 2**, **Pack Workstation 2** |
| Pack 3 | **Pack Name 3**, **Actual QTY 3**, **Pack Workstation 3** |
| Pack 4 | **Pack Name 4**, **Actual QTY 4**, **Pack Workstation 4** |
| Pack 5 | **Pack Name 5**, **Actual QTY 5**, **Pack Workstation 5** |
| Pack 6 | **Pack Name 6**, **Actual QTY 6**, **Pack Workstation 6** |
| Pack 7 | **Pack Name 7**, **Actual QTY 7**, **Pack Workstation 7** |

Pack names and workstations are auto-filled — do not edit them. Enter only **Actual QTY** for each pack that was produced.

Row-level fields (independent of pack slots):

| Field | What to enter |
|-------|---------------|
| **Recook** | Recook quantity (0 if none) |
| **Balance** | Balance quantity for the Pack Manufacture SE |
| **Raw Mat'l** | Raw material consumed |

### Changing Number Of Pack

If you adjust **Number Of Pack** after auto-fetch, unused slot fields are automatically cleared. For example, changing from 3 to 1 clears Pack 2 and Pack 3 data.

## Step 4: Submit

Click **Save** then **Submit** to submit the document. The "Process All" button only appears on submitted documents.

## Step 5: Process All (Background)

Click the **Process All** button in the toolbar. The job runs **in the background** — you can continue working on other things while it processes.

**What happens:**
1. A blue alert "Processing started in background" appears
2. The button changes to **"Processing..."** and is disabled
3. The **Processing Status** field (in the Background Processing section) shows "In Progress"
4. The form polls every 3 seconds for updates
5. When done -> the form auto-reloads and a message appears:
   - **Success** -> "All rows processed successfully"
   - **Failure** -> "Processing failed: <error details>" + a comment is added to the DOR timeline

> Closing the browser tab does NOT cancel the job — it continues running in the RQ worker queue (up to 10 minutes timeout).

**For rows with Status = "Pending":** The system processes work orders per link_id in this order:

**Per link_id:**

1. **WIP WO** -> Submit (if draft) -> Material Transfer SE -> Job Cards -> Manufacture SE
   - Created by Production Planning, auto-completed if already done

2. **Cook WO** -> Submit (if draft) -> Material Transfer SE -> Job Cards -> Recook (if > 0) -> Manufacture SE

3. **Pack WO(s)** -> Submit (if draft) -> Material Transfer SE -> Job Cards -> Manufacture SE
   - Each Pack WO is matched to its slot by **Pack Name** / **Pack Name N**
   - Pack Workstation is applied to empty operations before processing
   - The slot's **Actual QTY** and row-level **Balance** are applied to the Manufacture SE only

**For rows with Status = "Done" (already processed):** The system does NOT re-process them. Instead it **validates** that the entered **Actual QTY** matches the Pack WO's `produced_qty`:
- If they match -> silent pass
- If they mismatch -> a warning alert is shown and a comment is added to the DOR timeline documenting the mismatch (WO name, expected qty, entered qty)

The **Status** column updates as each row is processed (with color indicators):
- **Done** (blue) — completed successfully or already processed
- **Pending** (orange) — not yet processed
- **Failed** (red) — error occurred (processing stops)

## Error Handling

If a row fails:
- Processing stops at the failed row (no remaining WOs in that row are processed)
- The row shows status **Failed** (red)
- The error message includes the Work Order name that caused the failure
- The **Processing Status** field shows "Failed" with the error in **Processing Error**
- A **comment** is added to the DOR timeline with the full error details
- Fix the issue (e.g., insufficient stock, missing workstation) and try again with a new record
