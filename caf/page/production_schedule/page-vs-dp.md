# Production Schedule Page vs Daily Production Form

## The Simple Version

Think of it like **Google Sheets**:

- The **DP doctype** = the actual spreadsheet (the data)
- The **Production Schedule page** = a pretty view/form on top of that spreadsheet

Both show and edit the **same data**. There is only one copy.

---

## How It Works

```
User edits on Board (page)
        │
        ▼
production_schedule.js  (board UI)
        │
        ▼
frappe.call() to Python
        │
        ▼
production_schedule.py  (opens DP, saves fields)
        │
        ▼
DP document saved to database  (tabDaily Production + child table)
        │
        ▼
User opens DP form
        │
        ▼
daily_production.js  (reads same data from database)
```

---

## Why There Are Two JS Files

| File | What it does |
|------|-------------|
| `production_schedule.js` | Board UI — validates packs, recipe, size, status when editing on the board |
| `daily_production.js` | DP form — validates the same fields when editing the DP directly |

**Same data, two entry points.** Both must have matching validation.

---

## Example: Pack Qty Rule

When user sets 3 packs:

| Pack | Qty Required? | Where enforced |
|------|--------------|----------------|
| Pack 1 | Yes | `daily_production.js` + `production_schedule.js` + `daily_production.py` |
| Pack 2 | Yes | Same three places |
| Pack 3 (last) | No | Same three places |

If you only fix one file, the other entry point will have a gap.

---

## Key Rule

**Every validation must exist in three places:**

1. `production_schedule.js` — board edit/add dialogs
2. `daily_production.js` — DP form child table handlers
3. `daily_production.py` — server-side on submit

If you change something in one, check the other two.
