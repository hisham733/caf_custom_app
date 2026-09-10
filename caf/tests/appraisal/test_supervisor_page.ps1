# CAF Supervisor Bulk Appraisal page - the role suite for /app/supervisor-appraisal
# =================================================================================
# T-38, built 2026-09-10. Until today this page had **zero** test coverage, while
# exposing four whitelisted endpoints reachable by URL:
#
#     get_direct_reports_appraisals(appraisal_cycle)
#     get_appraisal_doc(appraisal_name)
#     save_appraisal_kra(appraisal_name, kra_rows)
#     submit_for_review(appraisal_name)
#
# 🔴 THE REASON THIS MATTERS. All four do `frappe.get_doc(...)`, and
# `frappe.get_doc()` performs **no permission check at all**. Only ONE of them -
# `get_appraisal_doc` - carries the explicit `doc.check_permission("read")` that
# was added in v1.1 after a real leak. `save_appraisal_kra` and
# `submit_for_review` have no such line, and nothing has ever checked whether
# something else stops them.
#
# ⚠️ Every probe runs as a REAL role over HTTP. Administrator is used only to set
# up and tear down, never as a permission subject.
#
# THE FIXTURE - the REAL org tree, not the retired hand-built one:
#     C  HR-EMP-00008 Ow Yong Nin Geet   production1@   (SupC)
#     └── A HR-EMP-00036 Nurulfarehah    quality@       (SupA)  9 direct reports
#         └── B HR-EMP-00171 Siti Noratikah              (EmpB)  Employee role ONLY
#             + HR-EMP-00181 Nurul Aisyah                (EmpBb) a second leaf
#
# CYCLE: **2026-08**, and it must be a month that has ALREADY ENDED - BR6 refuses
# `submit_for_review` on a cycle still running, so SP7/SP8 cannot be exercised in
# a future one. (First written against 2026-10 and SP7 duly failed with
# "Appraisal cycle 2026-10 ends on 2026-10-31" - the product was right.)
#
# ⚠️ Cleanup is scoped to **A's direct reports in that cycle**, never to the whole
# cycle: test_2_5_to_2_8 owns (HR-EMP-00185, 2026-08) and must not be collateral.
# get_direct_reports_appraisals CREATES a draft for every direct report it finds -
# nine per call - so this suite cleans at both ends.

$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$credFile = Join-Path $here "credentials.ps1"
if (-not (Test-Path $credFile)) {
  Write-Host "credentials.ps1 not found. Copy credentials.example.ps1 and fill it in." -ForegroundColor Yellow
  exit 1
}
. $credFile
$U = $CAF_SITE_URL
$T = $CAF_TOKENS

$CYCLE   = "2026-08"
$EMP_A   = "HR-EMP-00036"   # the supervisor under test
$EMP_B   = "HR-EMP-00171"   # a leaf under A
$EMP_B2  = "HR-EMP-00181"   # a second leaf under A - B's colleague

function Req($role, $method, $path, $body) {
  # 🔴 A MISSING KEY IS THE MOST DANGEROUS FAILURE IN THIS SUITE. $T[$role] on an
  # absent key returns $null, so "token " goes out, Frappe treats the caller as
  # GUEST, and everything comes back 403 - making every test that EXPECTS a 403
  # pass having proved nothing. It happened here on 2026-09-10: the T-37 re-point
  # renamed SupA2 -> SupA, this file still said SupA2, and SP2 "passed" while the
  # server was answering "Login to access".
  if (-not $T[$role]) {
    throw "credentials.ps1 has no token for role '$role'. Every request would run as Guest, and the 403-expecting tests would pass for the wrong reason."
  }
  $p = @{ Uri = "$U$path"; Method = $method; Headers = @{ Authorization = "token $($T[$role])" }
          UseBasicParsing = $true; TimeoutSec = 90 }
  if ($body) { $p.Body = $body; $p.ContentType = "application/json" }
  try { $r = Invoke-WebRequest @p; return @{ code = [int]$r.StatusCode; json = ($r.Content | ConvertFrom-Json) } }
  catch {
    $c = 0; if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }
    $m = $null; if ($_.ErrorDetails.Message) { try { $m = ($_.ErrorDetails.Message | ConvertFrom-Json).exception } catch {} }
    return @{ code = $c; json = $null; err = $m }
  }
}
function Res($id, $ok, $detail) { "{0,-7} {1,-6} {2}" -f $id, $(if ($ok) {"PASS"} else {"FAIL"}), $detail }
# ⚠️ The parameter is NOT called $args. `$args` is a PowerShell AUTOMATIC
# variable (the unbound-argument array), so naming a parameter that silently
# leaves it empty and every call arrives with no arguments at all. It cost a full
# run: Frappe answered "missing 1 required positional argument: 'appraisal_cycle'"
# and the endpoint looked broken when the caller was.
function Page($role, $method, $payload) {
  return Req $role POST "/api/method/caf.caf.page.supervisor_appraisal.supervisor_appraisal.$method" ($payload | ConvertTo-Json -Depth 6)
}

# @($null).Count is 1 in PowerShell, not 0 - so a null result reads as "one row"
# and an emptiness assertion passes when it should fail.
function CountRows($v) { return @($v | Where-Object { $_ -ne $null }).Count }

function Clear-Cycle {
  # 🔴 Scoped to A's OWN direct reports in $CYCLE, never the whole cycle.
  # test_2_5_to_2_8 owns (HR-EMP-00185, 2026-08); deleting by cycle alone would
  # take its fixture with it - the exact mistake T-21 was raised to fix.
  $kids = (Req Admin GET ("/api/resource/Employee?limit_page_length=0&filters=" +
           [uri]::EscapeDataString("[[""reports_to"",""="",""$EMP_A""]]"))).json.data
  $ids = @($kids | ForEach-Object { $_.name })
  if (-not $ids.Count) { return 0 }
  $f = [uri]::EscapeDataString("[[""appraisal_cycle"",""="",""$CYCLE""],[""employee"",""in"",[" +
        (($ids | ForEach-Object { """$_""" }) -join ",") + "]]]")
  $rows = (Req Admin GET "/api/resource/Appraisal?limit_page_length=0&filters=$f&fields=%5B%22name%22%2C%22docstatus%22%5D").json.data
  foreach ($a in @($rows)) {
    if ([int]$a.docstatus -eq 1) { Req Admin PUT "/api/resource/Appraisal/$($a.name)" '{"docstatus":2}' | Out-Null }
    Req Admin DELETE "/api/resource/Appraisal/$($a.name)" | Out-Null
  }
  return @($rows).Count
}

"=== cleanup: A's direct reports in cycle $CYCLE ==="
"  removed $(Clear-Cycle) appraisal(s) from a previous run"
""

"=== SP1  the supervisor opens the page (THE CAROLINA REPRODUCTION) ==="
# MG's manual pass, production1@: "Next button reach below emp, error msg board
# ... You are not allowed to access this Appraisal record because it is linked to
# Employee 'HR-EMP-00001' in field Reported By ... issue - Carolina A/P Vijian is
# report-to production1@". An employee who DOES report to the supervisor produced
# an access error. This is that call, made as a supervisor over HTTP.
$sp1 = Page SupA "get_direct_reports_appraisals" @{ appraisal_cycle = $CYCLE }
$rows = @($sp1.json.message.doc_list | Where-Object { $_ -ne $null })
Res "SP1" ($sp1.code -eq 200 -and $rows.Count -gt 0) `
  "supervisor lists her direct reports' appraisals: code=$($sp1.code) rows=$($rows.Count) total=$($sp1.json.message.total) : $($sp1.err)"
if ($rows.Count) { "        first: $($rows[0].employee) $($rows[0].employee_name) [$($rows[0].workflow_state)]" }

# SP1b - the page must return HER reports and nobody else's. A supervisor page
# that quietly widens is worse than one that errors.
$emps = @($rows | ForEach-Object { $_.employee } | Sort-Object -Unique)
$expected = (Req Admin GET ("/api/resource/Employee?limit_page_length=0&filters=" +
             [uri]::EscapeDataString("[[""reports_to"",""="",""$EMP_A""],[""status"",""="",""Active""]]"))).json.data
$expectedIds = @($expected | ForEach-Object { $_.name } | Sort-Object -Unique)
$extra = @($emps | Where-Object { $expectedIds -notcontains $_ })
Res "SP1b" ($extra.Count -eq 0 -and $emps.Count -gt 0) `
  "returned $($emps.Count) employee(s); A actually has $($expectedIds.Count) active direct reports; NOT hers: $($extra.Count) [$($extra -join ', ')]"

"=== SP2  a leaf employee has no direct reports ==="
# Must refuse cleanly and say why - never a crash, and never somebody else's list.
$sp2 = Page EmpB "get_direct_reports_appraisals" @{ appraisal_cycle = $CYCLE }
$sp2rows = CountRows $sp2.json.message.doc_list
Res "SP2" ($sp2.code -ne 200 -or $sp2rows -eq 0) `
  "leaf employee opens the supervisor page: code=$($sp2.code) rows=$sp2rows (must be refused or empty) : $($sp2.err)"

""
"=== SP3-SP6  the three endpoints that take an appraisal NAME ==="
# Pick a target that belongs to A's team, then knock on each endpoint as a LEAF
# employee who has no business touching it.
$target = if ($rows.Count) { $rows[0].name } else { $null }
$targetEmp = if ($rows.Count) { $rows[0].employee } else { "" }

if (-not $target) {
  Res "SP3" $false "no appraisal available - SP1 must pass first; SP3-SP6 not run"
} else {
  # SP3 - the owner-supervisor can read it. The positive control: if this fails,
  # the negatives below prove nothing (everything would be refused).
  $sp3 = Page SupA "get_appraisal_doc" @{ appraisal_name = $target }
  Res "SP3" ($sp3.code -eq 200) "supervisor reads her own report's appraisal $target : code=$($sp3.code) rows=$(@($sp3.json.message.kra_rows).Count) editable=$($sp3.json.message.is_editable) : $($sp3.err)"

  # SP4 - the v1.1 fix, as a REGRESSION GUARD. `doc.check_permission("read")`
  # was added on 2026-08-06 after this exact call returned 200 where the raw
  # Frappe API correctly returned 403. Nothing has re-checked it since.
  $sp4 = Page EmpB "get_appraisal_doc" @{ appraisal_name = $target }
  Res "SP4" ($sp4.code -ne 200) `
    "leaf employee reads a COLLEAGUE's appraisal through the page: code=$($sp4.code) (must NOT be 200 - this is the v1.1 check_permission line) : $($sp4.err)"

  # 🔴 SP5 - save_appraisal_kra has NO check_permission call. Whether anything
  # else stops a stranger writing into an appraisal has never been established.
  $kra = @()
  foreach ($r in @($sp3.json.message.kra_rows)) {
    $kra += @{ name = $r.name; caf_description = "SP5 PROBE - must never be stored" }
  }
  $sp5 = Page EmpB "save_appraisal_kra" @{ appraisal_name = $target; kra_rows = ($kra | ConvertTo-Json -Depth 5 -Compress) }
  $after = Page SupA "get_appraisal_doc" @{ appraisal_name = $target }
  $leaked = @(@($after.json.message.kra_rows) | Where-Object { "$($_.caf_description)" -like "*SP5 PROBE*" }).Count
  Res "SP5" ($sp5.code -ne 200 -and $leaked -eq 0) `
    "leaf employee WRITES into a colleague's appraisal: code=$($sp5.code) (must NOT be 200); rows carrying the probe text afterwards=$leaked (must be 0) : $($sp5.err)"

  # 🔴 SP6 - submit_for_review has no check_permission either, and it moves the
  # document's workflow state. A stranger submitting somebody's appraisal for HR
  # review is a state change nobody asked for.
  $sp6 = Page EmpB "submit_for_review" @{ appraisal_name = $target }
  $state = (Page SupA "get_appraisal_doc" @{ appraisal_name = $target }).json.message.header.workflow_state
  Res "SP6" ($sp6.code -ne 200 -and $state -eq "Draft") `
    "leaf employee SUBMITS a colleague's appraisal: code=$($sp6.code) (must NOT be 200); state afterwards='$state' (must stay Draft) : $($sp6.err)"

  # SP7 - the supervisor's own submit works, and a second one is refused with a
  # sentence rather than a stack trace.
  $sp7 = Page SupA "submit_for_review" @{ appraisal_name = $target }
  $sp7b = Page SupA "submit_for_review" @{ appraisal_name = $target }
  Res "SP7" ($sp7.code -eq 200 -and $sp7b.code -ne 200) `
    "supervisor submits her own: code=$($sp7.code) state=$($sp7.json.message.workflow_state); submitting twice: code=$($sp7b.code) (must be refused) : $($sp7.err)"

  # SP8 - once it has left Draft the page must refuse edits, or a supervisor
  # could rewrite an appraisal HR is already reviewing.
  $sp8 = Page SupA "save_appraisal_kra" @{ appraisal_name = $target; kra_rows = ($kra | ConvertTo-Json -Depth 5 -Compress) }
  Res "SP8" ($sp8.code -ne 200) `
    "edit after Submit for Review: code=$($sp8.code) (must be refused - 'Locked for review') : $($sp8.err)"
}

""
"=== SP9  HR Manager reaches the page endpoints at all ==="
# BR3: HR Manager may appraise anyone. The page should not be the one surface
# that locks her out.
if ($target) {
  $sp9 = Page HRMgr "get_appraisal_doc" @{ appraisal_name = $target }
  Res "SP9" ($sp9.code -eq 200) "HR Manager reads any appraisal through the page: code=$($sp9.code) : $($sp9.err)"
}

""
"=== SP10  🔴 MG's ACTUAL Carolina case - a supervisor with a self-scoping User Permission ==="
# SP1 passes because `quality@` carries NO Employee User Permission. `production1@`
# DOES - `allow = Employee, for_value = HR-EMP-00008 (himself),
# apply_to_all_doctypes = 1` - and he is the supervisor MG was driving when the
# page failed:
#
#   "You are not allowed to access this Appraisal record because it is linked to
#    Employee 'HR-EMP-00001' in field Reported By ... issue - Carolina A/P Vijian
#    is report-to production1@"
#
# ⚠️ CORRECTION, same day. I expected this to be RED - that a self-scoping User
# Permission would block the whole page. **It does not, measured: 61 rows, 200.**
# The theory was wrong and is recorded here so nobody re-proposes it.
#
# What actually happens: User Permissions bite at the LIST/report layer and in
# `check_permission`, not in this endpoint - which uses `frappe.db.exists`,
# `frappe.db.get_value` and `frappe.get_doc`, none of which consult them. And the
# drafts this call creates carry `reported_by = HR-EMP-00008`, i.e. himself, so
# they stay inside his permitted set.
#
# 🔴 MG's failing document was `HR-APR-2026-00091`, a PRE-EXISTING appraisal whose
# `reported_by` was **HR-EMP-00001** - an Employee his permission does not allow.
# So the trigger is narrower than "the page is broken": it is
# `get_appraisal_doc` on an appraisal whose `reported_by` names an Employee
# outside the supervisor's User Permission. That case still needs its own probe -
# GO_LIVE_TODO T-38b - and it needs a fixture appraisal built with a foreign
# `reported_by`, which this run did not have.
#
# ✅ Keep this assertion anyway: it is the positive control proving the page
# works for a supervisor who has one of the site's 92 self-scoping permissions.
$up = (Req Admin GET ("/api/resource/User%20Permission?limit_page_length=0&filters=" +
       [uri]::EscapeDataString("[[""user"",""="",""production1@caffood.com""],[""allow"",""="",""Employee""]]"))).json.data
$upCount = CountRows $up
$sp10 = Page SupC "get_direct_reports_appraisals" @{ appraisal_cycle = $CYCLE }
$sp10rows = CountRows $sp10.json.message.doc_list
Res "SP10" ($sp10.code -eq 200 -and $sp10rows -gt 0) `
  "production1@ (61 direct reports, $upCount self-scoping Employee User Permission) opens the page: code=$($sp10.code) rows=$sp10rows - a supervisor MUST see their own reports : $($sp10.err)"

""
"=== SP11  T-38b — the Carolina case: an appraisal with a FOREIGN reported_by ==="
# 🔴 THIS IS THE ONE SP10 COULD NOT REPRODUCE. SP10 passes because the drafts it
# creates all carry `reported_by = <the supervisor himself>`, which sits inside
# his own Employee User Permission. MG's failing document did not:
#
#   "You are not allowed to access this Appraisal record because it is linked to
#    Employee 'HR-EMP-00001' in field Reported By ... issue - Carolina A/P Vijian
#    is report-to production1@"
#
# `production1@` carries `allow = Employee, for_value = HR-EMP-00008 (himself),
# apply_to_all_doctypes = 1`. A document holding a Link to ANY other Employee is
# then outside his permitted set - and `reported_by` is such a link.
#
# ⚠️ The fixture works because `set_reported_by()` only fills a BLANK
# (`if not self.reported_by`), and `read_only = 1` is form decoration that
# `doc.save()` does not enforce (OD-61/OD-62, measured). So Administrator can
# plant a foreign value at insert.
#
# 🔴 THE ASSERTION IS THE DESIRED BEHAVIOUR, NOT THE CURRENT ONE: a supervisor
# must be able to open the appraisal of somebody who reports to them. Do not
# "fix" it by weakening this line.
#
# ⚠️ AND IT IS NOT A PAGE BUG - measured 2026-09-10, both routes, same document:
#
#     /api/resource/Appraisal/<name>   (the ORDINARY form's route)   403
#     get_appraisal_doc                (this page)                   403
#     ...and with reported_by = himself, BOTH return                 200
#
# So the page is only where MG was standing when he hit it; the ordinary
# appraisal form refuses it identically. The assertion lives here because this is
# where the fixture is cheap, but the fault is in the APPRAISAL DOCTYPE's
# permissions - specifically `production1@`'s User Permission restricting him to
# documents linked to his OWN employee record. 94 such permissions exist, 92 are
# self-scoping, and exactly ONE of those belongs to somebody with direct reports:
# him, with 61. See GO_LIVE_TODO T-38b, decision ⑯.
# ⚠️ REUSE one of the drafts SP10 just created rather than inserting a new one -
# every employee under production1@ already has an appraisal for $CYCLE, so a
# fresh insert hits the duplicate guard (measured: 409 DuplicateEntryError).
$sp10rowsList = @($sp10.json.message.doc_list | Where-Object { $_ -ne $null })
$fname = if ($sp10rowsList.Count) { $sp10rowsList[0].name } else { $null }
if (-not $fname) {
  Res "SP11" $false "no appraisal from SP10 to re-point - SP10 must pass first"
} else {
  # plant a FOREIGN reported_by. `read_only = 1` is form decoration that
  # `doc.save()` does not enforce (OD-61/OD-62, measured), so a PUT stores it.
  $put = Req Admin PUT "/api/resource/Appraisal/$fname" '{"reported_by":"HR-EMP-00001"}'
  $stored = (Req Admin GET "/api/resource/Appraisal/$fname").json.data.reported_by
  $read = Page SupC "get_appraisal_doc" @{ appraisal_name = $fname }
  Res "SP11" ($stored -eq "HR-EMP-00001" -and $read.code -eq 200) `
    "production1@ opens the appraisal of his OWN report whose reported_by='$stored' (a FOREIGN Employee; PUT code=$($put.code)): code=$($read.code) - must be 200. A 403 here IS MG's Carolina case, and the cause is his self-scoping Employee User Permission, not this page : $($read.err)"
}

""
"=== cleanup ==="
"  removed $(Clear-Cycle) appraisal(s)"
# SP10 may have created drafts for production1@'s 61 reports - clear those too
$kidsC = (Req Admin GET ("/api/resource/Employee?limit_page_length=0&filters=" +
          [uri]::EscapeDataString("[[""reports_to"",""="",""HR-EMP-00008""]]"))).json.data
$idsC = @($kidsC | ForEach-Object { $_.name })
if ($idsC.Count) {
  $fC = [uri]::EscapeDataString("[[""appraisal_cycle"",""="",""$CYCLE""],[""employee"",""in"",[" +
         (($idsC | ForEach-Object { """$_""" }) -join ",") + "]]]")
  $rowsC = (Req Admin GET "/api/resource/Appraisal?limit_page_length=0&filters=$fC&fields=%5B%22name%22%2C%22docstatus%22%5D").json.data
  foreach ($a in @($rowsC)) {
    if ([int]$a.docstatus -eq 1) { Req Admin PUT "/api/resource/Appraisal/$($a.name)" '{"docstatus":2}' | Out-Null }
    Req Admin DELETE "/api/resource/Appraisal/$($a.name)" | Out-Null
  }
  "  removed $(@($rowsC).Count) appraisal(s) created under HR-EMP-00008 by SP10"
}
