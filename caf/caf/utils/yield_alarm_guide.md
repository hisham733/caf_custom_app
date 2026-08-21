# Yield Deviation Alarm

The Yield Deviation alarm is a configurable morning report that flags cooking runs
whose actual yield deviates by more than a set amount from the expected (BOM)
yield — **in either direction** (too low OR too high). It runs automatically and
sends a warning to WhatsApp and/or Telegram.

It mirrors the **Yield Calculation** query used in Metabase so that the numbers you
see in the alarm match the numbers you see in the dashboard.

---

## How yield is calculated

For each production run, a **Cook Work Order** and its linked **Pack Work Orders** are
joined together by a shared `custom_link_id`. The actual yield is:

```
Yield % = (Total_Weighted_Pack_Production + Pack_Balance + Total_Weighted_Pack_Rejects)
          / Cook_Total_Material_Input × 100
```

Where:

| Term | Meaning |
|------|---------|
| **Cook_Total_Material_Input** | Total weight (kg) of all raw materials consumed in the Cook WO's `Manufacture` Stock Entry, including recook, normalized to kg (grams ÷ 1000). |
| **Recook_Counter** | Weight of the recipe item itself added back as an input (recook) in kg. |
| **Total_Weighted_Pack_Production** | Sum over completed Pack WOs of `produced_qty × item weight`. Item weight comes from the **Weight** variant attribute, falling back to `Item.weight_per_unit`. Items in the **WIP FLOSS** item group count as weight 1. |
| **Pack_Balance** | Sum of scrap items ( `is_scrap_item = 1` ) transferred to `Prod Balance - CAF` across all linked Pack WOs. |
| **Total_Weighted_Pack_Rejects** | Sum of items transferred to `Prod Reject - CAF` across linked Pack WOs, multiplied by their item weight. |

Only runs where **the Cook WO is Completed AND all of its Pack WO(s) are Completed**
are considered.

---

## The expected (BOM) yield

Each recipe has an expected yield stored on its default, submitted BOM in the
`custom_yield` field (stored as a fraction, e.g. `0.8` = 80%). The alarm compares the
actual yield against it:

```
Expected % = custom_yield × 100
```

The BOM matched is: `BOM` where `item = Cook production_item`, `is_default = 1`, and
`docstatus = 1` (submitted).

---

## What triggers the alarm

A cooking run is flagged when its actual yield deviates from the BOM expected yield
by **more than the threshold, in either direction**:

```
abs(Actual Yield % − Expected (BOM) %) > Yield Deviation Threshold
```

`Yield Deviation Threshold` default = **3**. Examples:

| Actual | BOM | Deviation | Threshold 3 | Alarm? |
|--------|-----|-----------|-------------|--------|
| 76%    | 80% | −4        | 4 > 3       | ✅ Yes (Low) |
| 84%    | 80% | +4        | 4 > 3       | ✅ Yes (High) |
| 82%    | 80% | +2        | 2 > 3       | ❌ No  |
| 78%    | 80% | −2        | 2 > 3       | ❌ No  |

Both **unusually low** and **unusually high** yields are reported, each tagged
`below expected` or `above expected` in the message.

---

## What data range it checks

A morning run checks the **last completed days**:

- **End date** = yesterday
- **Start date** = end date − (Look Back Days − 1)

| Look Back (Days) | Checked range |
|------------------|---------------|
| 1 (default)      | yesterday only |
| 3                | the last 3 completed days |

Set **Look Back (Days)** in Caf Settings to widen or narrow the window.

---

## How the report selects and filters the work orders

The report does **not** loop over every Work Order one by one in Python. Instead it
runs **one SQL query** that selects, filters, and groups everything in the database,
then applies the deviation check to the handful of grouped results. Here is the
exact selection and filtering logic, step by step.

### 1. Which Work Orders are pulled in (initial pool)

The query starts from **every** Work Order that:

- has `custom_item_type` = **`Cook`** or **`Pack`**, **and**
- is **not Cancelled** (`status <> 'Cancelled'`).

Both the Cook WO and its sibling Pack WO(s) are read, because the yield formula needs
output from both sides. Groups that end up with **no** completed Cook or **no**
completed Pack are later dropped (see step 4).

### 2. What data is joined to each Work Order

For every Work Order in that pool, the query joins:

- **`tabItem`** — to read the item group (used for the WIP FLOSS weight rule).
- **`tabItem Variant Attribute`** (weight) — to get each item's weight.
- **Manufacture Stock Entries** (`mnf_sum`) — the Cook WO's **total material input**
  and its **recook weight** (summed from submitted `Manufacture` Stock Entries,
  normalized to kg: grams ÷ 1000).
- **Balance / scrap** (`bfp`) — scrap items transferred to `Prod Balance - CAF`
  across the linked Pack WOs.
- **Rejects** (`pr`) — items transferred to `Prod Reject - CAF` across the linked
  Pack WOs.

These joins are keyed on the Work Order name and on `custom_link_id` (the shared
group id across a Cook and its Packs).

### 3. Grouping — one row per production run

The result is **grouped by `custom_link_id`**. Aggregates are built inside the group:

- `Cook_Work_Order` / `Cook_Production_Item` = the **Completed** Cook WO in the group.
- `Cook_Total_Material_Input` = the Cook WO's total material input (kg).
- `Total_Weighted_Pack_Production` = ∑ over Completed Pack WOs of `produced_qty × weight`.
- `Pack_Balance` = ∑ scrap → Prod Balance over Completed Pack WOs.
- `Total_Weighted_Pack_Rejects` = ∑ rejects → Prod Reject over Completed Pack WOs.

### 4. Hard filters (HAVING) — only fully-finished runs

A `HAVING` clause keeps a group only if **all** of these are true:

- it has **at least one Completed Cook WO**, **and**
- it has **at least one Pack WO**, **and**
- **every** Pack WO in the group is **Completed** (no open/Draft/In Process packs).

So the alarm only judges a run when the Cook is done **and all of its Pack(s) are
done too**. If any Pack is still open, that run is skipped.

### 5. Attach reference + BOM, then the date-range filter

The grouped rows are joined again to:

- the **reference Cook WO** (`wo_ref`) — to read batch size, round, planned_start_date,
  and its workstation (first operation), and
- the **BOM** (`bom_ref`) — the default, submitted BOM for the Cook production_item,
  to get `custom_yield` (the expected yield).

Finally, the date filter is applied:

```
WHERE DATE(wo_ref.planned_start_date) BETWEEN start_date AND end_date
```

So only cooking runs whose **Cook WO's planned date falls inside the configured
range** (e.g. yesterday for Look Back = 1) are kept.

### 6. The deviation check (in Python, over grouped rows only)

The SQL returns **one row per cooking run** (already filtered to the date range and
to completed Cook+Pack groups). Python then loops over those rows and keeps only
the ones outside the expected range:

```python
if bom and abs(actual - bom) > yield_deviation_threshold:
    flagged.append(row)
```

The heavy work — pulling all Work Orders, joining Stock Entries, grouping by link,
filtering to the range — happens **inside the database**. Python only compares the
few resulting rows against the BOM yield and formats the message.

### Selection summary (what counts / what is ignored)

| Factor | Included | Excluded |
|--------|----------|----------|
| Work Order type | Cook + Pack | other types |
| Status | Cook Completed + **all** Pack(s) Completed | Cancelled; Cook open, or any Pack still open/Draft/In Process |
| Date | Cook WO `planned_start_date` within the range | outside the range |
| Group (link_id) | ≥1 Completed Cook AND ≥1 Completed Pack | incomplete groups |
| Deviation | `abs(actual − BOM) > threshold` (high or low) | within the threshold |

---

## Configuration (Caf Settings → Reports → Yield Deviation)

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| **Enabled** | Check | On | Master switch for the report. You cannot enable it without a threshold. |
| **Send Time** | Time | 08:00 | Time of day the report sends (matched against the site clock). |
| **Look Back (Days)** | Int | 1 | How many days back to examine (1 = yesterday only). |
| **Yield Deviation Threshold** | Float | 3 | How many percentage points the yield must deviate (high or low) from the BOM yield to trigger the alarm. |
| **Yield Drop → WhatsApp** | Check | On | Send the alarm via WhatsApp. |
| **Yield Drop → Telegram** | Check | On | Send the alarm via Telegram. |
| **This Report → WhatsApp Chats** | Small Text | blank | Optional: only send to these WhatsApp chats. Leave blank to use the shared WhatsApp chats. |
| **This Report → Telegram Chats** | Small Text | blank | Optional: only send to these Telegram chats. Leave blank to use the shared Telegram chats. |

### Validation rules
- **Enabled** cannot be turned on if **Yield Deviation Threshold** is empty.
- **Enabled** cannot be turned on if both **WhatsApp** and **Telegram** are off.

---

## Scheduling

Frappe cron is static, so the send time is handled by a dispatcher:

- A periodic cron (`0,30 5-12 * * *`) calls `morning_dispatcher.run_due_reports()`.
- The dispatcher reads each report's **Enabled** flag and **Send Time** from
  Caf Settings.
- When the current time matches a report's configured **Send Time**, it queues that
  report's runner in the background.
- The runner (`yield_report.send_yield_warning`) computes the deviations and, if any
  exist, sends via the configured channels.

If **Enabled** is off, or there are **no** runs outside the range, nothing is sent
(silent).

---

## Sample message

```
📊 *Yield Deviation*
📅 2026-08-20 08:00
🔻 Threshold: more than 3 points from BOM yield (either direction)
--------------------------

🔎 2 Cooking run(s) outside the expected yield range:

*Recipe SS* | 🔗 R-2026-06090
  🏭 Cook WO: MFG-WO-2026-26944
  ⚙️ Workstation: M Kettle 6
  🔢 Round: 1
  📏 Batch Size: 60.0
  🎯 Yield: 82% (BOM: 90%) ⛔ Deviation: 8% below expected
  📦 Packs: B-MC, HK, SS code
  🗓️ Planned: 2026-07-03 05:47:47

*Recipe BPC* | 🔗 R-2026-05989
  🏭 Cook WO: MFG-WO-2026-26493
  ⚙️ Workstation: Cooker 1
  🔢 Round: 1
  📏 Batch Size: 4.0
  🎯 Yield: 71% (BOM: 66%) ⛔ Deviation: 5% above expected
  📦 Packs: BPC
  🗓️ Planned: 2026-07-02 01:31:27
```

---

## Related files

| File | Purpose |
|------|---------|
| `caf/utils/yield_report.py` | Yield calculation, deviation detection, message builder, and senders. |
| `caf/utils/morning_dispatcher.py` | Time-based dispatch of the configured reports. |
| `caf/utils/notifications.py` | Channel dispatch (`_send_report_message`) and WAHA/Telegram senders. |
| `caf_settings.json` (Reports → Yield Deviation) | Configuration fields. |

## Manual trigger (testing)

From the console/terminal:

```bash
# Preview yesterday's/range deviations without sending
bench --site <site> execute caf.caf.utils.yield_report.get_yield_drops

# Send the warning now (respects threshold + channels)
bench --site <site> execute caf.caf.utils.yield_report.manual_yield_warning
```
