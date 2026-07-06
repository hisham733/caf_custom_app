# Production Schedule — User Guide

## Access

Navigate to **Production Schedule** from the CAF module or directly at `/app/production-schedule`.

## Modes

### Edit Schedule (default)

Use this mode to plan and edit recipes for the upcoming week. You can:

- Add new recipes to any slot
- Drag recipes between slots (same-day only)
- Edit recipe details (size, packs, status, notes)
- Cancel recipes
- Submit the week

### View Schedule

Toggle to this mode to see submitted DPs in read-only form. Click any recipe to open the full ERPNext DP form in a new tab.

---

## The Board Layout

The board matches the Metabase "Meta - Multi DP Schedule" layout:

- **Rows** = Workstations grouped by type (Cookers, Kettles, Fryers)
- **Columns** = Monday through Saturday
- **Slots per day** = R1, R2, R3 (3 recipe slots per workstation)
- **Note column** = Combined recipe notes for the workstation/day
- **Pack column** = Combined pack remarks for the workstation/day

Each recipe card shows:
- Recipe name
- Status badge (emoji + text)
- Size (batch quantity)

---

## Adding a Recipe

1. Click the **"+ R1/R2/R3"** button in the slot where you want to add a recipe
2. In the dialog:
   - **Recipe**: Select from the item list (type to search)
   - **Size**: Enter batch quantity (required)
   - **Number of Pack**: How many pack variants (0 if none)
   - **Status**: Choose an option (see Statuses below)
   - **Production Type**: Optional classification
   - **Urgent**: Check if urgent
   - **Recipe Note**: Optional note
   - **Pack fields**: Fill pack name/qty/remark for each pack variant
   - **Production Plane**: Optional
3. Click **Save**

After saving with status "New Schedule", the system creates a Material Request and Work Orders in the background. A processing indicator shows while this runs.

---

## Editing a Recipe

Click any existing recipe card to open the edit dialog. You can modify:

- **Status** (see Statuses below)
- **Recipe** (only editable when status is "Recipe Change")
- **Size** (editable when status is "Recipe Change" or empty)
- **Number of Pack** and pack details
- **Production Type, Urgent, Recipe Note, Production Plane**

When you change the recipe with status "Recipe Change":
- Size is automatically cleared to 0
- All pack fields are cleared
- After save, Work Orders are reprocessed in the background

### Important: Field Entry

After typing in any field, click elsewhere or tab out before clicking **Save**. This ensures the value is captured. The page also auto-finalizes fields on save, but it's best practice to blur fields manually.

---

## Drag-and-Drop

1. Make sure you're in **Edit Schedule** mode
2. Click and drag a recipe card to a different slot
3. Drop it on an empty slot (R1/R2/R3 on the same day)
4. The recipe moves to the new slot; the old slot becomes available
5. Both slots are marked "Change Slot"
6. Work Orders are migrated and reprocessed in the background

**Rules:**
- You can only move recipes within the **same day** (cross-day moves are not supported)
- The recipe swaps position with the "No Cooking" placeholder at the target slot
- The slot's original workstation and round are preserved

---

## Statuses

| Status | Meaning | When to Use |
|--------|---------|-------------|
| *(empty)* | No action needed | Default for existing recipes with no pending change |
| New Schedule | A new recipe added to the board | When adding a brand-new recipe for the week |
| Change Slot | Recipe moved to a different slot | Set automatically by drag-drop (not user-selectable) |
| Rearrange | Recipes swapped between slots | Set automatically by drag-drop (not user-selectable) |
| Recipe Change | Recipe recipe/size was changed | When the recipe itself needs to change |
| Cancelled | Remove this recipe from production | When a recipe should not be produced |

### Status Workflow

1. Add recipes with **New Schedule** → background creates MR + WOs
2. Edit as needed with **Recipe Change** → background reprocesses WOs
3. Drag recipes → **Change Slot** set automatically → background migrates WOs
4. To remove → set **Cancelled** → background cancels WOs, slot resets

---

## Cancelling a Recipe

1. Click the recipe card to open edit dialog
2. Set **Status** to "Cancelled"
3. Click **Save**
4. The system cancels all associated Work Orders in the background
5. The slot resets to "No Cooking" and becomes available for new recipes

---

## Submitting the Week

1. Ensure all recipes have the correct status
2. Click **Submit Week** button (visible only in Edit Schedule mode)
3. Only DPs with at least one status change are submitted
4. Past days (before today) are skipped
5. After submission, recipes move to **View Schedule** mode

---

## Creating a New Week

1. Click **Create Week** button
2. A new set of draft DPs is created from the latest submitted versions
3. Past days are automatically removed (you can only edit current/future days)
4. The new week appears in **Edit Schedule** mode

---

## Quick Reference

| Action | How |
|--------|-----|
| Add recipe | Click "+" in an empty slot |
| Edit recipe | Click the recipe card |
| Move recipe | Drag and drop to another slot (same day) |
| Cancel recipe | Edit → Status = "Cancelled" → Save |
| Change recipe recipe | Edit → Status = "Recipe Change" → Change recipe → Save |
| Submit week | Click "Submit Week" |
| Create week | Click "Create Week" |
| Switch mode | Use the toggle (Edit / View) |

## Troubleshooting

| Issue | Likely Cause | Solution |
|-------|-------------|----------|
| Save button does nothing | Field not blurred | Click another field first, then Save |
| Background processing stuck | RQ worker not running | Contact admin to start `bench worker` |
| Drag-drop doesn't work | Cross-day move attempted | Only same-day moves are allowed |
| Recipe not showing after add | Page needs refresh | Reload the page |
| "Failed" status on card | Background job error | Check error logs, retry the operation |
| "No Cooking" appears after cancel | Cancel completed normally | Slot is free for new recipe |
