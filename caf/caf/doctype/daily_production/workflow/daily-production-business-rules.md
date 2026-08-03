# Daily Production — Business Rules Guide

A non-technical reference for production planners. Explains what each status means, when to use it, and what the system does behind the scenes.

> **Last updated:** 2027-01-18 — Workflow states, pre-checks, auto-clearing, hidden statuses

---

## What is Daily Production?

Daily Production (DP) is your daily cooking schedule. It tells each workstation:
- **What recipe** to cook
- **How much** (batch size)
- **How many packs** to produce
- **Which round** (1st, 2nd, or 3rd cook of the day)

One DP covers one day (Monday through Saturday). The system creates one DP per date automatically when you switch to Edit mode.

---

## Draft vs Submitted

Unlike traditional Frappe documents, a DP never gets "submitted" in the database sense. It uses a **Workflow State** instead:

| State | Meaning | What you can do |
|-------|---------|-----------------|
| **Draft** | Editable — you can add, move, change recipes | Full editing |
| **Submitted** | Locked — ready for Work Order creation | View only, Create WO per day |
| **Obsolete** | Old version, superseded | View only |

Switching mode changes the state automatically:
- **Edit Schedule** → sets state to **Draft**
- **Submit Week** → sets state to **Submitted**

---

## The 6 Statuses — When to Use Each

### 1. New Schedule

**When to use:** You are adding a recipe to a slot for the first time.

**Example:** You open Monday's schedule. Cooker 1, Round 1 is empty (shows "No Cooking"). You click the "+" button and add "BBQ Chicken" with size 30 and 2 packs. Set status to **New Schedule**.

**What happens:** When you click "Create WO," the system creates a Material Request, Production Plan, and Work Orders (Cook + Pack) for this recipe.

**Rule:** New Schedule rows MUST have a pack assigned (name + count) before you can create Work Orders.

**After completion:** Status stays visible so you can see it was a new schedule.

---

### 2. Recipe Change

**When to use:** You already have Work Orders for this slot, but you need to change the recipe or batch size.

**Example:** "BBQ Chicken" (size 30) is scheduled for Monday. The customer changes their order. You need "Grilled Chicken" (size 40) instead. Edit the row, change the recipe and size, set status to **Recipe Change**, and save.

**What happens:** The system cancels the old Cook and Pack Work Orders, then creates new ones with the new recipe and size. Quality records (Quality Review, Weight Record) are transferred to the new Cook Work Order.

**What gets cancelled:** Old Cook WO + Pack WOs + WIP WOs + Stock Entries + Job Cards. Old Production Plan also cancelled.

**What gets created:** New MR → new PP → new Cook WO + Pack WOs + WIP WOs.

**What stays:** `link_id` (same identity, new WOs), workstation, round.

**⚠️ Pre-check:** The system checks if the Cook Work Order is already **Completed** BEFORE saving. If it is completed, your change is blocked and you see an error message. You must cancel the entire row instead.

**After completion:** Status stays visible. After clicking "Create WO", all statuses are cleared.

---

### 3. Pack Change

**When to use:** The recipe and size are correct, but you need to change which packs are produced or how many.

**Example:** "BBQ Chicken" (size 30) was supposed to produce 2 packs. Now you need 3 packs. Edit the row, update the pack fields, set status to **Pack Change**, and save.

**What happens:** The system cancels only the Pack Work Orders (the Cook Work Order stays untouched). New Pack Work Orders are created with the updated pack configuration.

**⚠️ Pre-check:** The system checks if any Pack Work Order is already **Completed** BEFORE saving. If any is completed, your change is blocked.

**After completion:** Status stays visible.

---

### 4. Change Slot

**When to use:** You need to move a recipe from one workstation/round to another empty slot.

**Example:** "BBQ Chicken" is on Cooker 1/Round 1. You need it on Cooker 2/Round 2 instead. Drag "BBQ Chicken" from Cooker 1/R1 to Cooker 2/R2 (which shows "No Cooking").

**What happens:** The recipe moves to the new slot. If Work Orders exist, the system migrates them to the new slot (a background job runs). If no Work Orders exist yet, only the recipe data moves.

**What gets cancelled:** Old Cook WO + Pack WOs + Stock Entries + Job Cards for the recipe at its new position. WIP WOs preserved.

**What gets recreated:** New MR → new PP → new Cook WO + Pack WOs. New WIP WOs are created then deleted.

**Rule:** You can only move to an empty (No Cooking) slot. If the target already has a recipe, use **Rearrange** instead.

**After completion:** Both slots' statuses are automatically cleared.

---

### 5. Rearrange

**When to use:** You need to swap two recipes between their slots.

**Example:** "BBQ Chicken" is on Cooker 1/R1. "Beef Burger" is on Cooker 2/R2. You want to swap them. Drag one recipe onto the other.

**What happens:** The system swaps all recipe data between the two rows. If Work Orders exist, both sets are cancelled and recreated at their new slots. Quality records cross-relink (each recipe's quality data follows it).

**What gets cancelled:** Old Cook WO + Pack WOs + Stock Entries + Job Cards for BOTH slots. WIP WOs are preserved (not cancelled).

**What gets recreated:** New MR → new PP → new Cook WO + Pack WOs for BOTH slots. New WIP WOs are created then deleted (original WIP is kept).

**What stays:** Workstation and round (slot position) — fixed. `link_id` — follows the slot.

**Rule:** Both slots must have recipes. If one is empty, use **Change Slot** instead.

**After completion:** Both slots' statuses are automatically cleared.

---

### 6. Cancelled

**When to use:** You need to remove a recipe entirely. The order is no longer needed.

**⚠️ Important:** You CANNOT select "Cancelled" from the status dropdown. You MUST use the **"Cancel Recipe" button** inside the edit dialog (in the Actions section at the bottom). This ensures the proper cancellation flow runs.

**What happens:** All Work Orders (Cook + Pack + WIP) for this slot are cancelled. Stock Entries and Job Cards are also cancelled. The row resets to "No Cooking" — the slot is now free.

**Rule:** You cannot cancel if the Cook Work Order is already completed.

---

### 7. Only Remark

**When to use:** You want to add a note to a recipe without changing anything else.

**Example:** You need to remind the cook: "Check internal temperature before packaging." Edit the row, add the note to the Recipe Note field, set status to **Only Remark**, and save.

**What happens:** The note is saved and synced to the linked Work Orders. No Work Orders are created or changed.

**After completion:** Status stays visible so you can see the remark was applied. After clicking "Create WO", it is cleared with all other statuses.

---

## Status Summary Table

| Status | When to Use | What System Does | WOs Affected? | Auto-Cleared? |
|--------|-------------|------------------|---------------|---------------|
| New Schedule | Adding recipe first time | Creates MR → PP → WOs | Created | ❌ Kept |
| Recipe Change | Changing recipe or size | Cancels old, creates new | Replaced | ❌ Kept |
| Pack Change | Changing packs only | Cancels Pack WOs, creates new | Pack only | ❌ Kept |
| Change Slot | Moving recipe to empty slot | Migrates WOs to new slot | Migrated | ✅ Cleared |
| Rearrange | Swapping two recipes | Swaps WOs between slots | Swapped | ✅ Cleared |
| Cancelled | Removing recipe entirely | Cancels all WOs, frees slot | Cancelled | ✅ Slot reset |
| Only Remark | Adding a note | No WO action | None | ❌ Kept |

**"Create WO" button**: Clears ALL statuses after successful processing.

---

## The Weekly Workflow — Step by Step

### Step 1: Open Edit Schedule Mode

1. Go to the Production Schedule page
2. Select the year and ISO week number
3. Switch to **Edit Schedule** mode
4. The system shows "Creating draft production plans..." and creates DPs for Mon-Sat (if they don't exist)

### Step 2: Arrange Your Recipes

For each day, you can:
- **Add recipes** — Click "+" on empty slots, select recipe, set size and packs
- **Edit recipes** — Click a recipe card to change size, packs, or status
- **Move recipes** — Drag a recipe to a different slot (Change Slot)
- **Swap recipes** — Drag one recipe onto another (Rearrange)
- **Add extra rounds** — Click "Add Extra Rounds" to increase round count for a workstation
- **Cancel recipes** — Click "Cancel Recipe" button to remove a recipe

### Step 3: Submit Week

When all days are arranged:
1. Click **Submit Week**
2. Confirm the submission
3. All DPs move to **Submitted** state
4. The page switches to **View Schedule** mode

**Important:** Submitting does NOT create Work Orders. It only locks the schedule.

### Step 4: Create Work Orders (Per Day)

In View Schedule mode:
1. Click **Create WO** on each day column
2. The system processes all statuses for that day (New Schedule, Recipe Change, Pack Change, Change Slot, Rearrange, Cancelled, Only Remark)
3. After completion, the button shows "Created WO (001)"

### Step 5: Production Plan Buttons (Optional)

After Work Orders are created, you can generate:
- **Recipe (Requisition)** — raw material requirements
- **TIM Form** — Work-in-Progress transfer
- **WIP Form** — WIP material transfer

---

## Production Info — Yield, Total Input, Total Output

When you select a recipe, the system calculates:

| Field | Formula | Example |
|-------|---------|---------|
| **Yield (KG)** | From BOM | 1.22 |
| **Total Input (KG)** | raw_materials × size | 101.99 × 50 = 5,099.6 |
| **Total Output (KG)** | Total Input × Yield | 5,099.6 × 1.22 = 6,221.5 |

These are read-only — computed automatically from the recipe's BOM data.

---

## Important Rules

### Pack Requirements
- Every recipe MUST have at least 1 pack assigned before creating Work Orders
- If you have 2+ packs, each pack needs a quantity
- Max packs is 7, or the BOM's actual pack count (whichever is less)

### Weight Validation
- Total pack weight (qty × pack weight) must NOT exceed Total Output
- If it does, you'll see an error telling you to increase the size
- Validation runs when you change size, number of packs, or pack qtys

### Link IDs

Every recipe slot (workstation + round) gets a permanent unique ID. **1 link_id = 1 workstation + 1 round.** It never changes.

```
Cooker 1, R1 → R-2026-00001
Cooker 1, R2 → R-2026-00002  
Cooker 2, R1 → R-2026-00003
Cooker 3, R1 → R-2026-00004  (even "No Cooking" slots have one)
```

**Why link_id exists:**

| Purpose | How it helps |
|---------|-------------|
| Find all WOs for a slot | `WHERE custom_link_id = 'R-2026-07261'` — one query, no matter how many times the recipe changed |
| Track across recipe changes | Old WOs cancelled, new WOs created — same link_id keeps continuity |
| Move recipe to another slot | link_id migrates with the recipe |
| Swap two recipes | Swap link_ids = swap all WOs instantly |
| Cancel all WOs for a slot | Cancel everything by link_id |
| Audit trail | traceable from creation through all changes |

**link_id vs WO name:**
- WO name (`MFG-WO-2026-30250`) — changes with every recreate, tells you which document this is
- link_id (`R-2026-07261`) — stays constant, tells you which SLOT this belongs to

### Production Types

When adding or editing a recipe, you can set the **Production Type** in the dropdown. Each type tells the system and the operator how to handle the production.

| Type | When to use | What happens |
|------|-------------|-------------|
| **New** | Normal production — making from raw materials | Full MR → PP → WO chain. All WIP sub-assembly WOs created. Operator uses all raw items from BOM. |
| **Recook** | Recipe was rejected or is a balance — needs recooking | Operator clicks **Recook** button on the Cook WO to add the rejected recipe as an extra input line (via a Material Transfer Stock Entry from scrap/balance warehouse → WIP). Original BOM items stay. |
| **Reheat** | Entire cooker/kettle/fryer output rejected → sent to chiller/reject warehouse | **System auto-deletes all WIP WOs** after creation — sub-assembly items not needed. Operator uses the rejected recipe itself as input, deletes raw BOM items, adds only 1-2 extras (water, color). |
| **Repack** | Repackaging existing product without recooking | Same as New — label only. No special behavior. |

**How it propagates:** Production Type flows from the DP row → Material Request (`custom_operation_type`) → Production Plan → Work Order. Each WO knows its original type.

**Key difference — Recook vs Reheat:**

| | Recook | Reheat |
|---|--------|--------|
| Who triggers | Operator on the WO | Planner on the DP row |
| Original BOM items | Stay — recook adds extra on top | Operator deletes them |
| WIP WOs | Not deleted | System auto-deletes (`remove_all_wip_wo()`) |
| Main input | All BOM items + rejected recipe as extra | Rejected recipe becomes the main input |

### Work Order Guards
- You CANNOT change recipe if the Cook WO is already completed — the system blocks the save
- You CANNOT change packs if any Pack WO is already completed — the system blocks the save
- You CANNOT move or swap a recipe if a background job is still processing
- You CANNOT submit a week if any row has "Processing" status

### Problem Workstations
- If a workstation's status is set to "Problem" in ERPNext, its entire row is locked
- Red-tinted background, all fields read-only
- You cannot add, edit, move, or drag recipes on problem workstations

### No Cooking
- An empty slot placeholder. Every workstation×round combination always has a row.
- Choose "New Schedule" from the status dropdown to add a recipe to a No Cooking slot

### View Mode
- In View mode, clicking a recipe opens a **read-only** dialog
- Yield, Total Input, and Total Output values are loaded from BOM data
- No editing is possible

---

## Frequently Asked Questions

**Q: What happens if I forget to set packs?**
A: The system checks before creating Work Orders and tells you to set the pack name and count.

**Q: Can I move a recipe across days (Monday to Tuesday)?**
A: Only if neither day has Work Orders created yet. If WOs exist, you cannot move across days.

**Q: What does "Processing" mean on a recipe card?**
A: A background job is working on that recipe. Wait — it usually takes a few seconds. The badge changes to "Done" or "Failed."

**Q: What does "Failed" mean?**
A: The background job encountered an error. Click the badge to see the error. You can retry from the dialog.

**Q: Can I undo a Change Slot or Rearrange?**
A: Yes, and the status will be cleared from both slots after it completes.

**Q: How do I add extra rounds (R4, R5)?**
A: Click the **"Add Extra Rounds"** button in Edit mode. Select the day, workstation, and total rounds (e.g., 5 adds R4 and R5). The new empty slots appear only for that workstation.

**Q: Why can't I select "Cancelled" from the status dropdown?**
A: Cancellation requires a specific flow (background job + WO cleanup). Use the **"Cancel Recipe" button** instead — it's in the Actions section at the bottom of the edit dialog.

**Q: Why does my status stay visible after processing?**
A: Statuses like "Recipe Change", "Pack Change", "New Schedule", and "Only Remark" remain visible so you can see what was processed. They are cleared when you click "Create WO" or when the operation finishes (for move/swap operations).

**Q: Why is the slot showing "—" instead of "+"?**
A: That workstation doesn't have that round in its DP. Use "Add Extra Rounds" to add rounds for that specific workstation.

---

## Color Coding

| Badge | Meaning |
|-------|---------|
| No badge | Normal — no background activity |
| Processing (orange) | Background job running |
| Done (green) | Background job completed |
| Failed (red) | Background job failed — click for error |
| Red-tinted row | Problem workstation — all editing locked |
| "+" on empty slot | Clickable — add a recipe |
| "—" on empty slot | Not available — round doesn't exist for this workstation |
