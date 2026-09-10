# PowerShell REST role suite

The **permission** gate. Every probe here runs as a **real role over HTTP**, using
a per-role API token — never as Administrator.

## Why this exists separately from the Python suites

From the suite's own README, and it is the whole point:

> `Administrator` bypasses every permission check in Frappe — `has_permission`
> hooks, `permission_query_conditions`, role gates and `permlevel` filtering. A
> permission test run as Administrator **passes identically against a correct
> model and a completely broken one. It proves nothing.**

The Python suites use `frappe.set_user`, which exercises the permission model but
**not** the HTTP/whitelist layer. Anything that can be reached by URL — a report,
a whitelisted method, a doctype API — belongs here.

## Running

```powershell
cd \\wsl$\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\appraisal
.\probe_2_10b.ps1        # one probe
.\run_all.ps1            # everything — completes since T-21 (2026-09-10)
```

Run from **PowerShell**, not the Bash tool: these are `.ps1`, and the Bash tool
mangles the UNC path.

| file | covers |
|---|---|
| `test_2_1_to_2_4.ps1` | supervisor flow · HR flow · rejection loop · subtree |
| `test_2_5_to_2_8.ps1` | score toggle · BR6 · edge cases · `reports_to` rules |
| **`test_supervisor_page.ps1`** | ⭐ **T-38, built 2026-09-10 — 11/11.** The four whitelisted endpoints of `/app/supervisor-appraisal`. Runs on the **real** org tree (`SupC2`/`SupA2`/`EmpB2`), owns **A's direct reports in cycle 2026-08**, and cleans both ends |
| `probe_2_10a.ps1` | HR Settings permlevel |
| `probe_2_10b.ps1` | Finger Log restriction (D40) **+ Attendance Follow-Up report roles** |
| `probe_2_10bc.ps1` | EPF permlevel · KRA permissions · workflow present |
| `probe_2_10e.ps1` | cross-checks — did any permission change leak past its scope? |

Role keys in `credentials.ps1` (**gitignored**): `HRMgr` `SupA` `EmpB` `SupC`
`EmpD` `HRUser` `Admin`, plus `HRMgr2` (second HR Manager) and `EmpBb` (spare
second leaf).

🔴 **A MISSING KEY IS THE MOST DANGEROUS FAILURE HERE, and it has happened
twice.** `$T[$role]` on an absent key returns `$null`, so `token ` goes out,
Frappe treats the caller as **Guest**, and everything returns 403 — which makes
every test that *expects* 403 pass having proved nothing. It hit `T-J10` once and
`SP2` on 2026-09-10 when the T-37 re-point renamed `SupA2` → `SupA`.
✅ **`CafHeader` / `Req` now `throw` on a missing key** in every script. A warning
in a document did not stop it twice; the throw will.

## ✅ T-21 CLOSED 2026-09-10 — `run_all.ps1` completes

## 🔴 SP11 is DELIBERATELY RED — do not weaken it

**89 passed, 1 failed.** The one failure is **SP11**, and it reproduces the bug
MG hit by hand on the supervisor page:

> *production1@ opens the appraisal of his OWN report whose
> `reported_by = HR-EMP-00001` → **403***

**The cause is not the page.** `production1@` carries a **self-scoping Employee
User Permission** (`allow = Employee, for_value = HR-EMP-00008, apply_to_all_doctypes = 1`),
so any document holding a Link to a *different* Employee — and `reported_by` is
one — falls outside his permitted set.

⭐ **Measured: he is the ONLY supervisor affected — and he has 61 direct reports.**
92 of the site's 94 Employee User Permissions are self-scoping, but the other 91
are on people with **no reports**, where self-scoping is exactly right.

🔴 **The assertion states the DESIRED behaviour** — a supervisor must be able to
open the appraisal of somebody who reports to them. Fixing it is a **policy**
decision (should a supervisor carry a self-scoping Employee User Permission at
all?), not a test edit. **Do not make it green by changing what it asks.**

## ✅ The other 89 — green since T-37 (2026-09-10)

```
   test_2_1_to_2_4      21 · test_2_5_to_2_8      21 · test_supervisor_page 11
   probe_2_10a           7 · probe_2_10b          12 · probe_2_10bc         12
   probe_2_10e           6
```

**The suite now runs on CAF's REAL org tree**, not the retired hand-built one.
`reports_to` is production-bound data and was not touched — the suite moved:

| role | employee | user | why |
|---|---|---|---|
| **C** | HR-EMP-00008 Ow Yong Nin Geet | `production1@` | 61 reports, **no** HR-side role |
| **A** | HR-EMP-00036 Nurulfarehah | `quality@` | 9 reports, reports to C |
| **B** | HR-EMP-00171 Siti Noratikah | — | **Employee role only**, leaf under A |
| **D** | HR-EMP-00009 Seow Zi Ying | — | disjoint branch; **needs no token** |

🔴 **`ow.yong@` is deliberately NOT the senior supervisor** — he holds HR Manager,
so every subtree assertion would pass on a *role* rather than the tree. He is
`HRMgr2`, the second HR Manager the two-person rule needs.

⭐ **The mapping lives in `credentials.ps1` (`$CAF_EMP`)** and every script reads
it from there. The next re-point is one file.

**The cycle moved to 2026-07** — the month the fixture employees actually have
Finger Logs for (38 each) *and* a month that has ended, which BR6 requires before
anything submits. T-A2's baseline was re-measured against real data:
`1, 17, 27` / `` / `23.5 h` / `27 working days`, asserted exactly.

⚠️ **Two expectations were wrong in a way a green suite would have hidden**:
T-D2 required C to see D (true only in the old tree — D is now deliberately
disjoint), and T-H6's leak list named HR-EMP-00036, who **is** A. Both corrected.

⚠️ **`$CURRENT` in `test_2_5_to_2_8` rots.** It sat at `2026-08` until 2026-09-10,
six weeks after that month ended, so T-F2 was asserting that a legal submit gets
refused. **Re-check it whenever a BR6 test fails.**

## T-38 — what covering the supervisor page actually established

🔴 **`save_appraisal_kra` and `submit_for_review` carry no `check_permission`
call** — only `get_appraisal_doc` got one (v1.1). ✅ **Measured: both are still
refused (403)** — but by `doc.save()` and `apply_workflow()` downstream, **not**
by anything the endpoint does itself. ⚠️ **That protection is incidental.** An
`ignore_permissions=True` added to either call would open the hole with nothing
to catch it — which is exactly what SP5 and SP6 now watch.

⚠️ **A theory I had, disproved the same day, recorded so nobody re-proposes it.**
92 of the site's 94 Employee User Permissions are self-scoping
(`apply_to_all_doctypes = 1`), and I expected one to break the page for its
holder. **It does not — `production1@` sees all 61 of his reports.** User
Permissions bite at the list/report layer and in `check_permission`; this
endpoint uses `frappe.db.exists` / `get_value` / `get_doc`, which do not consult
them. MG's failing document was a **pre-existing** appraisal whose `reported_by`
was an Employee outside his permitted set — narrower than "the page is broken",
and still owed a probe (**T-38b**).

```
   test_2_1_to_2_4    0 passed   1 failed   ← stops on T-ORG, by design
   test_2_5_to_2_8   14 passed   7 failed   ← all 7 are T-ORG or downstream
   probe_2_10a        7 passed   0 failed
   probe_2_10b        9 passed   0 failed
   probe_2_10bc      12 passed   0 failed   ← T-I2 green since 2026-09-10
   probe_2_10e        6 passed   0 failed
```

**The reset owns a list, not the site.** `_cleanup.ps1` used to `GET
/api/resource/Appraisal?limit_page_length=0` and delete the lot. It now removes
only the fixtures the suite creates, declared in two places at the top of that
file:

| declaration | what it is |
|---|---|
| `$CAF_FIXTURE_APPRAISALS` | the 9 **(employee, cycle) pairs** any script here inserts an Appraisal on — including the ones that expect a 403, since a 403 regressing to a 200 leaves a row |
| `$CAF_FIXTURE_EPF_MARKER` | `"PROBE"`, the substring every probe writes into `feedback` (`ZZPROBE` satisfies it) |

🔴 **Add a pair to that list in the same commit that adds the assertion.** A
fixture missing from it is a fixture that survives the reset.

The verification changed with it: the reset now confirms **the fixture pairs are
clear**, not that the site holds zero appraisals. Counting every row is what
produced the old *"3 appraisal(s) survived the reset"* — about three rows this
suite never owned, which then could not be deleted at all (quirks #63: a DELETE
is blocked by **any** referrer, cancelled ones included) and took the whole run
down with a null index.

Two smaller repairs shipped with it:

- `run_all.ps1` counted results matching `^T-`, silently dropping every id that
  does not start with `T-` — `probe_2_10bc`'s `D74` among them. It now matches on
  the **result column**.
- `test_2_5_to_2_8` left **`ZZ Probe OrgRoot`** on the site until the *next* run
  cleaned it, so between runs the site sat on **3 org roots** — a D53 violation
  that `deploy_appraisal_module` blocks on. It now removes its probe employees at
  the end and asserts the count is back to 2 (**T-H8**).

## 🔴 The org-tree fixture is gone — `Test-CafOrgFixture`

Every question this suite asks is *"who may appraise whom"*, and the answer comes
from three `reports_to` links built by hand on 2026-08-05
(`test_fixture_credentials.md` §1): **C Rukaiya → A Kamrul → B Salsabila**, with
**D Pramod** under C.

On **2026-09-01** `caf.tests.workflow_gaps.data_align.fill_apply` replaced the
whole tree with CAF's **real** org chart from `sites/employeewithreport_to.csv` —
81 employees, written with `frappe.db.set_value`, so **no Version row records it**
(OD-26) and nothing announced it. All four now report **directly to
HR-EMP-00008**, who carries **61 direct reports**; Kamrul and Rukaiya have none.

So `T-A1` gets a **correct** 403, `$APR` is null, and nineteen assertions then
report on a URL built from nothing. `Test-CafOrgFixture` checks the three links
first and says so in one line:

- **`test_2_1_to_2_4`** stops (`T-ORG` FAIL). All 20 of its assertions need the tree.
- **`test_2_5_to_2_8`** reports and carries on — 2.8's `reports_to` rules, `T-H7`
  and the EPF probes do not need it and are worth running.

⚠️ **Restoring the three links by hand will be undone the next time
`fill_apply` runs** — which is exactly how this happened. Awaiting MG (T-37).

The four `probe_2_10*` scripts do not depend on the tree and are unaffected.

## What is red, and why

| assertion | cause |
|---|---|
| `T-ORG` ×2 | the org tree above — **the only real finding** |
| `T-F1` `T-F2` `T-F6` `T-G3` `T-J8f`, half of `T-J15` | downstream of it: every appraisal created as `SupA` 403s |

✅ **`T-I2` is no longer among them.** Red since 2026-08-22 and rightly left that
way — until MG confirmed it on 2026-09-10, and his own manual pass
(`MG_LLM_ui_touch up.md`, Pass C5) turned out to hold the answer: a **supervisor**
cancelled a Completed appraisal, and the document afterwards still displayed
*"Completed"* while its `docstatus` had gone to 2. The `Cancelled` state added
that same day is the fix. It now asserts the shape **by meaning** — a `Cancel`
edge that runs `Completed → Cancelled`, belongs to HR Manager, and lands on
`doc_status = 2` — because counting to 4 would pass against four wrong states.

⭐ **`T-I2b`** records the trap underneath it: `allow_self_approval = 0` compares
against **`doc.owner`**, and clicking *Amend* makes the HR Manager the owner. So
the amender can never approve their own amendment — a second HR Manager must.
That is MG's *"workflow is stucked"*, and it is OD-87b working as designed.

Fixed on 2026-09-10, each with the reason written beside it:

- **`T-J15`** asserted the supervisor's Finger Log read returns **403**. OD-63
  option d gave the Employee role a read **scoped to their own rows** on
  2026-08-15, so 200 is correct. It now asks for **EMP_B's** logs explicitly and
  requires **0 rows back** — a stronger claim than the 403 ever made.
- **`T-J24` / `T-J24b`** — `Attendance Request` and `Employee Checkin` joined the
  Custom DocPerm fixture under **OD-84 / T-24**, built and verified 2026-09-02.
  Both lists (`$named` **and** `$touched`) now name them, with the reason.

## Gotchas

- **Test a report through `frappe.desk.query_report.run`**, never by importing its
  module and calling `execute()`. The module call **bypasses the permission gate
  entirely** and passes against a broken model (quirks #58) — the same trap as
  running the test as Administrator.
- **Widening a leak-detector needs a written reason.** `probe_2_10e`'s `$named` and
  `$touched` lists exist to catch a permission change escaping its intended scope.
  When a doctype legitimately joins them, name it *and say why in the file* — both
  current additions (Appraisal via OD-81b, Shift Assignment via R3) do.
- **A failing assertion here is not automatically stale — and both endings have
  happened.** `T-J25` once reported 4 users holding `Employee Self Service` where
  D42/T22 says zero; that was **live drift**, and the fix was the site
  (`retire_ess_role`), not the test — it passes at 0 today. `T-J15` and `T-J24`
  were the other ending: shipped decisions (OD-63, OD-84) the assertions had not
  caught up with. **Establish which before touching either**, and if you cannot,
  do what T-I2 did — leave it red and say why in `GO_LIVE_TODO.md`.
- Every script is **re-runnable and order-independent** by design. If one is not,
  that is the bug.
