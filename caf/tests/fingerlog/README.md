# CAF Finger Log / OT / Leave overhaul — test suite

Executable form of `CAF_fingerlog_test_plan.md`, following the convention of
`caf/tests/appraisal/`. Each chunk adds the scenarios it makes testable, as it
lands — which is what turns the throwaway verification scripts into permanent
assets. **Chunk T** then runs the whole matrix together.

## Running

```powershell
cd caf/tests/fingerlog
.\test_chunk2b.ps1
```

Credentials are **not** stored here. The suite reads `credentials.ps1` from this
folder if present, otherwise falls back to `..\appraisal\credentials.ps1`.

Finger Log is restricted to HR Manager + System Manager (D40), and none of these
scenarios turn on permissions — they are server logic and document lifecycle —
so the suite runs as the HR Manager fixture user throughout. Where a scenario
*does* depend on a role, follow the appraisal suite's rule and give it its own
per-role token: `Administrator` bypasses every check in Frappe and would pass
identically against a broken model.

## Coverage

| Scenario | What it proves | Chunk |
|---|---|---|
| **W2** | approved OT within the approval submits, `final_ot` set | control for W4 |
| **W3** | past the gate with **no** approval → cannot submit (FBR11) | 2b |
| **W4** | OT **exceeds** the approved duration → refused | 2b |
| **W8** | `caf_allow_ot = 0` → `ot_in_hour = 0`, submits, **no error** | 2b |
| **E1** | no shift at all → refuses **loudly**, does not guess | 2b |
| **E2** | public holiday on a shift's rest day → **Restday wins** | 2b |
| **E3** | one Saturday, two employees, opposite verdicts — OD-52 | 2b |
| **C1** | a rest Saturday's hours are **all** OT — FBR4 | Chunk 2 checkpoint |
| **C2** | same date, different `day_type` per employee — FDR6 | Chunk 2 checkpoint |

| **A1–A5**, **B3** | a late correction reaching a **submitted** appraisal — including the number going **DOWN** | 5 |
| **LOCK · SUBM · IDEM** | the OD-44 unlock is no wider than two cells; the FBR39 window actually closes; a no-op refresh writes nothing | 5 |

Still to come: W1/W5–W7/W9/W10, L1–L3, B1–B2 and E4/E6 from **Chunk 3**;
S1–S4 and E5 from **Chunk 4**; E7 from **Chunk 6**.

## Running the server-side suites

Chunks 3–5 run inside bench rather than over REST — fixture cleanup needs
`flags.ignore_links`, which the REST API cannot set:

```powershell
wsl docker exec -w /workspace/development/frappe-bench frappe bench --site development.localhost execute caf.tests.fingerlog.test_chunk5_appraisal.run
```

`test_chunk3_decisions.run` (21/21) · `test_chunk4_reresolve.run` (10/10) ·
`test_chunk5_appraisal.run` (15/15).

⚠️ **Chunk 5 writes to a doctype that holds live data.** Its `cleanup()` is scoped
to two employees, three dates and one cycle — never to an employee alone. Purging
by employee ate ~50 rows of imported July data once, and the run reported green
while doing it.

## Two things this suite learned the hard way

**A scenario can pass for the wrong reason.** The first draft ran W3 on
2026-06-10, where `HR-EMP-00016` already had a **pre-existing 1.5 h OT
Approval** among dev's 7,006. The Finger Log did refuse to submit — but because
2.0 h exceeded that approval, not because no approval existed. That is W4's
assertion wearing W3's label. Two guards now exist:

- the dates moved to **September 2026**, past the seeded data's last `work_date`
  of 2026-08-06
- **`FIX`** asserts the count of pre-existing approvals is 0 and fails the run if
  it is not, rather than leaving the next person to discover it

W3 and W4 also assert the **reason** in the error body, not just the refusal.

**A missing error body reads as a passing silence.** PowerShell 7 puts the
response body on `$_.ErrorDetails.Message`; the raw response stream has usually
been consumed by then and reading it yields `""`. Every "did it say why?"
assertion then quietly evaluates false — the server *had* explained itself and
the test never looked.

## Fixtures

| | Employee | Why |
|---|---|---|
| OT-eligible | `HR-EMP-00016` | `8am Schedule` — `caf_allow_ot 1`, gate 30, round 30 |
| no OT | `HR-EMP-00011` | `8:30am Schedule` — `caf_allow_ot 0` |
| **no shift at all** | `HR-EMP-00002` | the one active employee with no `default_shift` — a director who never punches, deliberately left empty in Chunk 0 (OD-24) |
| Mon–Fri | `HR-EMP-00127` | `8am no OT no Sat` — Saturday is a rest day |
| the swap | `HR-EMP-00003` | carries seeded rest-Saturday Shift Assignments |
| rest-day OT | `HR-EMP-00042` | `Special 8-5`, rests onto `special` — which **keeps** OT eligibility |

That last row is load-bearing. Two of CAF's three no-Saturday shifts carry
`caf_allow_ot = 0`, so assigning one to a rest Saturday would silently revoke OT
eligibility from an employee whose own shift grants it — and **all rest-day work
is OT (FBR4)**. `seed_rest_saturdays.pick_rest_shift()` matches `caf_allow_ot`
before start time for exactly this reason, and **C1 is the test that would catch
a regression**.

## Prerequisites

`C1` and `E3` need the rest-Saturday assignments:

```powershell
wsl docker cp <snapshot>/attendance.csv.gz frappe:/tmp/attendance.csv.gz
wsl docker exec -w /workspace/development/frappe-bench frappe bench --site development.localhost execute caf.scripts.seed_rest_saturdays.seed
```

Both scripts are re-runnable and clean up **first**, not last.
