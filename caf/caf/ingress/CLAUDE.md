# The Ingress importer

Reads FingerTec Ingress (MySQL 5.5.8 on a Windows desktop) and turns punches into
Finger Logs, which become Attendance. **Read-only against the machine, always.**

| file | |
|---|---|
| `source.py` | `LiveSource` (the LAN MySQL) and `SnapshotSource` (a CSV). One interface |
| `sync.py` | `manual_import` · `check_amendments` · `revert_batch` · the `_Batch` manifest |
| `inspect.py` | ad-hoc reads for diagnosis |

## The rules this obeys

- **FBR44 — import is a human act.** No scheduled fetch. The Ingress PC is HR's
  own desktop and is off outside her hours, so a nightly job would fail more often
  than it succeeded. If she forgets, employees see the gap and say so.
- **FBR43 — today is never importable.** Today's punches are half-written.
  Refused **loudly**, never silently clamped to yesterday.
- **FBR49 — `attendance` is NOT maintained in real time.** Raw taps land in
  `auditdata`; the `attendance` table is materialised only when somebody runs the
  day in Ingress. So "yesterday is importable" is necessary but **not
  sufficient** — the day must also have been *processed*. Detected per import and
  reported on `unprocessed_dates`.
- **FBR63 — the join is `attendance_device_id` AND `status = "Active"`, both.**
  Device id alone would resurrect a leaver's attendance, because Ingress keeps
  emitting rostered days for people who left years ago.
- **FDR10 — punches are never rewritten.** A re-resolve recomputes the
  *interpretation* (day type, hours, OT) and leaves the observation alone.

## Gotchas that cost real time

- 🔴 **`_c`, not `_x`, is the flag that moves when a punch is edited.** `_x` looks
  like an override flag and never moves on an HR edit. Proven by a controlled
  edit: `att_out` 17:58→19:45, `out_o` kept 17:58, `out_c` 0→1, `out_x` never
  moved. ⚠️ And **both live SELECTs must fetch the `_c` columns** — when they
  disagreed with `EDIT_FLAGS`, every live row silently read *"not adjusted"* while
  the suite stayed green on synthetic fixtures. Guarded by `C6-SQL-SELECTS-EDIT-FLAGS`.
- **A whitelisted method receives STRINGS, including `""`.** `parse_json("")`
  raises; `filters` arrives as a JSON string. Use `cint`, never `int()`. This
  broke the main import path while 208 assertions stayed green.
- **`skipped_no_employee` counts INGRESS accounts with no ERPNext employee** —
  measured: 220 of them, 1,528 rows, every one punchless ex-staff. It says nothing
  about CAF's own people. An **ERPNext** employee with a blank device id produces
  no count at all and receives no attendance ever — that silence is the hazard
  (FBR41/FBR62), and it is why every batch carries a note naming anyone unmapped.
- **The manifest never updates.** A row is a record of one run; fix the log and
  submit it a week later and the row still says `Held`. For *what is still
  outstanding*, use the **Attendance Follow-Up** report.
- **The batch is created BEFORE the source is probed**, so an unreachable machine
  leaves a `Failed` batch rather than nothing at all.
- **Unreachable is normal**, not a fault — the PC sleeps and auto-locks. Ask MG to
  unlock it.

## Credentials

`Ingress Sync Settings` (HR Manager only — it holds the machine's DB password).
⚠️ `db_password` is a **Password** field: `get_password()`, never the raw doc
value, or you get `***` and an access-denied that looks like a network fault.

⚠️ **T-2 is still open** — the credential in use holds `ALL PRIVILEGES ON *.*` on
that server, not just `ingress`. `erp_ro` exists with zero privileges and is one
`GRANT` short; it must be run as root **at Natalie's own desk**, because
`root@localhost` cannot be reached over the LAN.
