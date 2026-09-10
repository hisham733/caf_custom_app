# Material Shortage Alarm (Raw Material Insufficient)

The shortage alarm watches all **Work Orders planned for today** and warns on
**WhatsApp and/or Telegram** whenever a raw material is short in its source
warehouse. It runs automatically every hour and sends nothing when everything
has enough stock.

It mirrors the **"not enough material" Metabase report**, with three differences:

1. Only Work Orders whose `planned_start_date` is **today**.
2. Items with **no stock record** (no Bin row) are treated as a shortage
   (`actual_qty = 0`) instead of being silently skipped.
3. A short item is **ignored** when the same item is *produced by another Work
   Order under the same `custom_link_id`* (an in-house pre-step such as TIM/WIP
   that runs before the recipe consumes it) — that stock is still in flight and
   will be available by the time the consuming WO runs.

---

## Schedule

Defined in `hooks.py`:

```
"0 8-18 * * *": [ "caf.caf.utils.shortage_report.send_shortage_warning" ]
```

Runs at **minute 0 of every hour from 8:00 to 18:00** (8 am – 6 pm, hourly).
Entry point: `send_shortage_warning()`.

---

## Flow

```
Every hour (8–18h)
   └─ send_shortage_warning()            shortage_report.py
        ├─ _is_enabled()                 Caf Settings > "Check Raw Material for Work Orders" (shortage_enabled)
        │    (default on if not set)
        ├─ get_material_shortages()      runs SHORTAGE_SQL → rows where required > available
        │    ├─ compute shortage = required_qty − actual_qty
        │    └─ drop rows covered by an in-house producer WO (see below)
        ├─ if no rows → return (silent)
        ├─ build_shortage_message()      group rows by Work Order
        └─ _send_report_message("shortage", msg)   notifications.py → WhatsApp/Telegram
```

---

## What counts as a shortage

The core query (`SHORTAGE_SQL`):

```sql
FROM `tabWork Order` wo
JOIN `tabWork Order Item` wi ON wo.name = wi.parent
LEFT JOIN `tabBin` b ON wi.item_code = b.item_code
                    AND wi.source_warehouse = b.warehouse
LEFT JOIN `tabItem` it ON wi.item_code = it.name
WHERE wi.required_qty > COALESCE(b.actual_qty, 0)
  AND wo.status NOT IN ('Cancelled', 'Closed', 'Completed')
  AND DATE(wo.planned_start_date) = today
  AND (it.item_group IS NULL OR it.item_group <> 'Recipe')
```

A row is a shortage when all of these are true:

| Condition | Detail |
|-----------|--------|
| Not enough stock | `required_qty > actual_qty` (Bin qty for that item in the source warehouse) |
| Work Order active | `status` is not Cancelled / Closed / Completed |
| Planned today | `DATE(planned_start_date) = today` |
| Not a recipe item | item group is not `Recipe` |

`LEFT JOIN` on Bin means an item with **no Bin row at all** gets `actual_qty = 0`
→ it counts as fully short (this is the Metabase-report difference #2).

### In-house pre-step (TIM/WIP) exclusion

After the query, `_get_items_with_producer_wo()` builds the set of
`(custom_link_id, item_code)` pairs, then checks whether any **other** Work
Order under the **same `custom_link_id`** produces that same item
(`production_item`) and is not Cancelled/Closed. If so, the short row is
skipped — the stock is in flight and not yet on-hand.

This prevents false alarms for workflows like: *Cook `R-…` produces WIP item X
in a pre-step, and a later Cook WO under the same link consumes X.*

---

## Message format

```
🔴 Material Insufficient — 2026-08-22 09:00
2 WO(s), 3 item(s) short

• 🏭 CURRY CHICKEN | R-2026-04835
  ⚠️ CHICKEN LEG MEAT: req 12.000, have 5.000, short 7.000
  ⚠️ GLUCOSE SYRUP: req 3.000, have 0.000, short 3.000

• 🏭 CHICKEN FLAVOUR | R-2026-04849
  ⚠️ VEG OIL: req 40.000, have 12.000, short 28.000
```

One block per Work Order, one line per short item, quantities to 3 decimals.

---

## Channel routing

`_send_report_message("shortage", msg)` (in `caf/caf/utils/notifications.py`)
uses these Caf Settings toggles/lists:

| Field | Meaning |
|-------|---------|
| `shortage_enabled` | Master switch (default ON if unset) |
| `shortage_wa` | Send via WhatsApp |
| `shortage_tg` | Send via Telegram |
| `shortage_wa_chats` | Per-report WhatsApp chat IDs (blank → shared list) |
| `shortage_tg_chats` | Per-report Telegram chat IDs (blank → shared list) |

- At least one channel must be ON when the report is enabled (enforced in
  `CafSettings.validate` / `_require_channel`).
- If the report's own chat list is blank, it falls back to the **shared**
  WhatsApp/Telegram chats.

### Connection config

- **WhatsApp (WAHA):** Caf Settings `waha_enabled`, `waha_base_url`,
  `waha_chat_ids`, `waha_api_key` — fallback to `site_config["waha"]`.
- **Telegram:** Caf Settings `telegram_enabled`, `telegram_bot_token`,
  `telegram_chat_ids` — fallback to `site_config` `telegram_bot_token` /
  `telegram_chat_id`.

Outbound failures are logged (`What's App/Telegram connection failed`) and never
block the scheduler.

---

## Manual trigger (for testing)

Whitelisted method — call it from the browser/console to send immediately:

```
/api/method/caf.caf.utils.shortage_report.manual_shortage_warning
```

Returns `{success, count, message}` or *"No material shortages found."* when
nothing is short. It bypasses the scheduler but still respects the channel
routing and disabled-toggle checks (via `_send_report_message`).

---

## Related files

| File | Role |
|------|------|
| `caf/caf/caf/utils/shortage_report.py` | Query, WIP/TIM exclusion, message builder, scheduler + manual entry points |
| `caf/caf/caf/utils/notifications.py` | `_send_report_message` + WAHA/Telegram senders and channel config |
| `caf/caf/doctype/caf_settings/caf_settings.py` | Validation (must have ≥1 channel when enabled) |
| `caf/caf/hooks.py` | Cron entry (`0 8-18 * * *`) |