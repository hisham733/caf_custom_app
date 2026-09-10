# CAF Appraisal chunk 2 - test plan 2.5 to 2.8, plus the five carried over from
# chunk 1 (T-I3, T-J8c, T-J8d, T-J8f, T-J15).
# 🔴 $CURRENT must be the month ACTUALLY IN PROGRESS - that is the whole basis of
# the BR6 tests, and it rots. Written when "today" was 2026-08-05 and left at
# 2026-08 until 2026-09-10, by which point the month had ended and T-F2 was
# asserting that a legal submit is refused. **Re-check it when a BR6 test fails.**

$ErrorActionPreference = "Continue"
# Credentials are NOT stored in this repo - see credentials.example.ps1.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$credFile = Join-Path $here "credentials.ps1"
if (-not (Test-Path $credFile)) {
  Write-Host "credentials.ps1 not found. Copy credentials.example.ps1 to credentials.ps1 and fill it in." -ForegroundColor Yellow
  exit 1
}
. $credFile
. (Join-Path $here "_cleanup.ps1")
$U = $CAF_SITE_URL
$T = $CAF_TOKENS
# T-37, 2026-09-10: the REAL org tree, from credentials.ps1.
$EMP_B = $CAF_EMP.B   # HR-EMP-00171 Siti Noratikah - leaf under A
$EMP_D = $CAF_EMP.D   # HR-EMP-00009 Seow Zi Ying - OUTSIDE A's branch
$EMP_A = $CAF_EMP.A   # HR-EMP-00036 Nurulfarehah
# ⚠️ DATE ROT FIXED. The header still said "Today is 2026-08-05", and $CURRENT
# was 2026-08 - a month that ended six weeks ago, which silently destroyed the
# point of every BR6 test: T-F2 asserts a submit is REFUSED because the month has
# not finished. $CURRENT must always be the month actually in progress.
$PAST = "2026-07"; $CURRENT = "2026-09"

function CafHeader($role) {
  # 🔴 A MISSING KEY IS THE MOST DANGEROUS FAILURE IN THIS SUITE. $T[$role] on an
  # absent key returns $null, so "token " goes out, Frappe treats the caller as
  # GUEST, and every request comes back 403 - which makes every test that EXPECTS
  # a 403 pass having proved nothing. It bit T-J10 once, and again on 2026-09-10
  # when the T-37 re-point renamed SupA2 -> SupA. Fail loudly instead.
  if (-not $T[$role]) {
    throw "credentials.ps1 has no token for role '$role'. Every request would run as Guest, and the 403-expecting tests would pass for the wrong reason."
  }
  return @{ Authorization = "token $($T[$role])" }
}
function Req($role, $method, $path, $body) {
  $p = @{ Uri = "$U$path"; Method = $method; Headers = (CafHeader $role); UseBasicParsing = $true; TimeoutSec = 90 }
  if ($body) { $p.Body = $body; $p.ContentType = "application/json" }
  try { $r = Invoke-WebRequest @p; return @{ code = [int]$r.StatusCode; json = ($r.Content | ConvertFrom-Json) } }
  catch {
    $c = 0; if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }
    $m = $null; if ($_.ErrorDetails.Message) { try { $m = ($_.ErrorDetails.Message | ConvertFrom-Json).exception } catch {} }
    return @{ code = $c; json = $null; err = $m }
  }
}
function Res($id, $ok, $detail) { "{0,-7} {1,-6} {2}" -f $id, $(if ($ok) {"PASS"} else {"FAIL"}), $detail }
function Ins($role, $doc) { return Req $role POST "/api/method/frappe.client.insert" (@{ doc = $doc } | ConvertTo-Json -Depth 6) }
function WfAction($role, $name, $action) {
  return Req $role POST "/api/method/frappe.model.workflow.apply_workflow" `
    (@{ doc = @{ doctype = "Appraisal"; name = $name }; action = $action } | ConvertTo-Json -Depth 6)
}
function SetToggle($val) {
  Req HRMgr PUT "/api/resource/HR%20Settings/HR%20Settings" "{""caf_enable_score_calculation"":$val}" | Out-Null
}

# --- self-cleanup so the suite is RE-RUNNABLE -------------------------------
# This script creates a 2026-08 draft, ZZ Probe employees and probe EPFs. Left
# behind, the next run hits its own leftovers: T-F1 fails with a duplicate, and
# T-F2 then 404s on a null document name - neither of which is a product fault.
"=== cleanup from any previous run ==="
Reset-CafTestData -Request { param($r,$m,$p,$b) Req $r $m $p $b } -IncludeProbeEmployees
""

# --- the org tree ------------------------------------------------------------
# Reported, then CARRIED ON - unlike test_2_1_to_2_4, which stops. Only the
# assertions that create an appraisal AS SupA depend on the tree (T-F1/2/3,
# T-G3, T-J15); 2.8's reports_to-mandatory and org-root checks, T-H7 and the EPF
# probes do not, and they are worth running. The named FAIL keeps the run red.
$orgOk = Test-CafOrgFixture -Request { param($r,$m,$p,$b) Req $r $m $p $b }
if (-not $orgOk) {
  Res "T-ORG" $false "org-tree fixture absent (see above) - every SupA-created appraisal below will 403 for that reason, not the product's"
  ""
}

"=== 2.6  BR6 - the month-ended rule gates SUBMIT, not create (D31) ==="

# T-F1 - drafting for the current, unfinished month is always allowed
$draft = Ins SupA @{ doctype="Appraisal"; employee=$EMP_B; appraisal_cycle=$CURRENT; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
$CUR_APR = $draft.json.message.name
Res "T-F1" ($draft.code -eq 200) "save a draft for the current month ($CURRENT): code=$($draft.code) name=$CUR_APR $($draft.err)"

# T-F3 - auto-fill refuses to compute a month that has not finished: reporting a
# partial month as if it were final is worse than reporting nothing
$d = (Req HRMgr GET "/api/resource/Appraisal/$CUR_APR").json.data
$cells = @(@($d.appraisal_kra) | Where-Object { $_.caf_date_cell })
Res "T-F3" ($cells.Count -eq 0) "auto-fill on an unfinished month: $($cells.Count) cells populated (must be 0); auto_fill_computed_on=$($d.auto_fill_computed_on)"

# T-F2 - submitting it must be refused
$sub = WfAction SupA $CUR_APR "Submit for Review"
$after = (Req HRMgr GET "/api/resource/Appraisal/$CUR_APR").json.data
Res "T-F2" ($sub.code -ne 200 -and $after.workflow_state -eq "Draft") `
  "submit before the month ends: code=$($sub.code) state=$($after.workflow_state) : $($sub.err)"

# T-F6 - a Not Started cycle does NOT block creation; only Completed does
$notStarted = (Req HRMgr GET "/api/resource/Appraisal%20Cycle/2026-11").json.data.status
$f6 = Ins SupA @{ doctype="Appraisal"; employee=$EMP_B; appraisal_cycle="2026-11"; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
Res "T-F6" ($f6.code -eq 200) "create for a '$notStarted' cycle (2026-11): code=$($f6.code) - documents that cycle status does NOT enforce BR6 $($f6.err)"
if ($f6.code -eq 200) { Req HRMgr DELETE "/api/resource/Appraisal/$($f6.json.message.name)" | Out-Null }

""
"=== 2.5  Score toggle (D2/BR5) ==="

# T-E1 - toggle OFF: an appraisal with no scores saves and submits cleanly
# NOTE: uses EMP-D + 2026-05, NOT EMP-B + $PAST. test_2_1_to_2_4 already gives
# EMP-B an appraisal for $PAST, so reusing that pair hits the duplicate guard,
# returns no document name, and the next two assertions then build a URL from a
# null and fail with HTTP 405 - which looks nothing like the real cause.
SetToggle 0
$e1 = Ins HRMgr @{ doctype="Appraisal"; employee=$EMP_D; appraisal_cycle="2026-05"; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
Res "T-E1" ($e1.code -eq 200) "toggle OFF, empty score columns: code=$($e1.code) $($e1.err)"
$E1_APR = $e1.json.message.name

# T-E2 - toggle ON with weightage != 100 must hit the stock guard
SetToggle 1
$rows = @((Req HRMgr GET "/api/resource/Appraisal/$E1_APR").json.data.appraisal_kra)
$bad = @{ appraisal_kra = @() }
foreach ($r in $rows) { $bad.appraisal_kra += @{ name=$r.name; kra=$r.kra; per_weightage=10 } }
$e2 = Req HRMgr PUT "/api/resource/Appraisal/$E1_APR" ($bad | ConvertTo-Json -Depth 6)
Res "T-E2" ($e2.code -ne 200 -and "$($e2.err)" -match "100") "toggle ON, weightage 60 total: code=$($e2.code) : $($e2.err)"

# T-E3 - toggle ON with a valid 100 total and scores present
$good = @{ appraisal_kra = @() }
foreach ($r in $rows) { $good.appraisal_kra += @{ name=$r.name; kra=$r.kra; per_weightage=$r.per_weightage; goal_completion=100 } }
$e3 = Req HRMgr PUT "/api/resource/Appraisal/$E1_APR" ($good | ConvertTo-Json -Depth 6)
$scored = (Req HRMgr GET "/api/resource/Appraisal/$E1_APR").json.data
Res "T-E3" ($e3.code -eq 200) "toggle ON, weightage 100 + completion: code=$($e3.code) total_score=$($scored.total_score) final_score=$($scored.final_score) $($e3.err)"
SetToggle 0
Req HRMgr DELETE "/api/resource/Appraisal/$E1_APR" | Out-Null

""
"=== 2.7  Edge cases ==="

# T-G3 - duplicate for the same employee + cycle
$g3 = Ins SupA @{ doctype="Appraisal"; employee=$EMP_B; appraisal_cycle=$CURRENT; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
Res "T-G3" ($g3.code -eq 409 -or "$($g3.err)" -match "Duplicate") "duplicate employee+cycle: code=$($g3.code) : $($g3.err)"

# T-G1 - an employee with no Finger Log rows in the period: blank cells, no crash
$g1 = Ins HRMgr @{ doctype="Appraisal"; employee="HR-EMP-00003"; appraisal_cycle=$PAST; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
if ($g1.code -eq 200) {
  $g1doc = (Req HRMgr GET "/api/resource/Appraisal/$($g1.json.message.name)").json.data
  $g1cells = @(@($g1doc.appraisal_kra) | Where-Object { $_.caf_date_cell })
  Res "T-G1" ($true) "employee with no Finger Log data: code=$($g1.code), populated cells=$($g1cells.Count), no crash"
  Req HRMgr DELETE "/api/resource/Appraisal/$($g1.json.message.name)" | Out-Null
} else {
  Res "T-G1" ($false) "could not create: code=$($g1.code) $($g1.err)"
}

""
"=== 2.8  reports_to mandatory + org-root exemption (D15/D51/D53) ==="

# T-H1 - a new employee with no reports_to and the checkbox unticked
$h1 = Ins HRMgr @{ doctype="Employee"; first_name="ZZ Probe NoSupervisor"; gender="Male"; date_of_birth="1990-01-01"; date_of_joining="2026-01-01"; company="CAF"; status="Active" }
Res "T-H1" ($h1.code -ne 200 -and "$($h1.err)" -match "Reports To|Supervisor") "new employee, empty reports_to, box unticked: code=$($h1.code) : $($h1.err)"

# T-H2 - the same employee WITH the org-root box ticked
$h2 = Ins HRMgr @{ doctype="Employee"; first_name="ZZ Probe OrgRoot"; gender="Male"; date_of_birth="1990-01-01"; date_of_joining="2026-01-01"; company="CAF"; status="Active"; caf_reports_to_nobody=1 }
$H2_EMP = $h2.json.message.name
Res "T-H2" ($h2.code -eq 200) "org root (box ticked), empty reports_to: code=$($h2.code) name=$H2_EMP $($h2.err)"

# T-H2b - unticking it while reports_to is still empty must throw
if ($H2_EMP) {
  $h2b = Req HRMgr PUT "/api/resource/Employee/$H2_EMP" '{"caf_reports_to_nobody":0}'
  $still = (Req HRMgr GET "/api/resource/Employee/$H2_EMP").json.data.caf_reports_to_nobody
  Res "T-H2b" ($h2b.code -ne 200 -and $still -eq 1) "untick the org-root box: code=$($h2b.code) stored flag=$still : $($h2b.err)"
}

# T-H7 - Get Employees on a cycle must exclude both org roots (D52)
$h7 = Req HRMgr POST "/api/method/caf.caf.overrides.appraisal.set_cycle_employees" (@{ appraisal_cycle="2026-07" } | ConvertTo-Json)
Res "T-H7" ($h7.code -eq 200 -and $h7.json.message.org_roots_excluded -ge 2) `
  "cycle appraisees=$($h7.json.message.appraisees) org_roots_excluded=$($h7.json.message.org_roots_excluded) (must exclude at least the 2 Directors) $($h7.err)"

# T-H6 - two disconnected trees: a supervisor under root 1 never sees root 2's branch
# 🔴 THE LEAK LIST WAS REBUILT 2026-09-10 (T-37) and the old one was actively
# WRONG: it named HR-EMP-00036 as part of "Director B's tree", and HR-EMP-00036
# is now EMP_A herself - so the assertion would have reported a leak the moment
# the suite worked. The disjoint branch in the real chart is Too Poh Chin's
# (HR-EMP-00003, lft 2-39); C's own branch is HR-EMP-00008's (lft 46-425). They
# do not overlap, so anyone under 00003 must never appear in C's list.
$lC = Req SupC GET "/api/resource/Appraisal?limit_page_length=0&fields=%5B%22employee%22%5D"
$seen = @(@($lC.json.data) | ForEach-Object { $_.employee } | Sort-Object -Unique)
$disjointBranch = @("HR-EMP-00005","HR-EMP-00007","HR-EMP-00009","HR-EMP-00011","HR-EMP-00013","HR-EMP-00065")
$leak = @($seen | Where-Object { $disjointBranch -contains $_ })
Res "T-H6" ($leak.Count -eq 0) "C sees [$($seen -join ', ')]; leaks from the disjoint branch under HR-EMP-00003: $($leak.Count) [$($leak -join ', ')]"

""
"=== carried over from chunk 1 ==="

# T-I3 - the headline proof of D55: no role gates this, the tree does
# ⚠️ 2026-12, not 2026-09: $CURRENT is now 2026-09, and reusing it here would hit
# T-F1's own draft and return a DUPLICATE error instead of the 403 this tests for.
$i3 = Ins EmpB @{ doctype="Appraisal"; employee=$EMP_B; appraisal_cycle="2026-12"; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
Res "T-I3" ($i3.code -eq 403) "Employee-role user with NO direct reports creates an Appraisal: code=$($i3.code) : $($i3.err)"
if ($i3.code -eq 200) { Req HRMgr DELETE "/api/resource/Appraisal/$($i3.json.message.name)" | Out-Null }

# T-J15 - auto-fill still computes after the Finger Log tightening (D40). The
# supervisor has NO direct read on Finger Log, yet the cells populate, because
# CAF's helpers run server-side.
#
# Builds its OWN appraisal rather than reusing one from test_2_1_to_2_4: every
# script resets the site first, so depending on another script's fixtures makes
# the result depend on run ORDER. It looked like a product failure the first
# time - "0 auto-filled cells" - when the appraisal had simply been cleared.
# ⚠️ EXPECTATION CORRECTED 2026-09-10. This asserted `code -eq 403` - a flat
# denial - which stopped being true on 2026-08-15, when OD-63 option d gave the
# Employee role a read on Finger Log SCOPED TO THEIR OWN ROWS
# (hooks.py -> caf.caf.finger_log_scope.get_permission_query_conditions). A
# supervisor now gets 200 and sees their own logs, so the old assertion failed
# against correct, shipped behaviour.
#
# The POINT of the test is unchanged and is now asserted directly: the supervisor
# cannot read the APPRAISEE's logs, yet the appraisee's cells still populate,
# because CAF's helpers run server-side. Ask for EMP_B's rows explicitly and
# require none to come back - a stronger claim than the 403 ever made.
$flq = [uri]::EscapeDataString("[[""employee"",""="",""$EMP_B""]]")
$fl  = Req SupA GET "/api/resource/Finger%20Log?limit_page_length=0&filters=$flq"
$flRows = @($fl.json.data).Count
$j15 = Ins SupA @{ doctype="Appraisal"; employee=$EMP_B; appraisal_cycle=$PAST; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
$j15name = $j15.json.message.name
$j15doc = (Req HRMgr GET "/api/resource/Appraisal/$j15name").json.data
$j15cells = @(@($j15doc.appraisal_kra) | Where-Object { $_.caf_date_cell })
Res "T-J15" ($flRows -eq 0 -and $j15cells.Count -gt 0) `
  "supervisor asks for EMP_B's Finger Logs directly: code=$($fl.code) rows=$flRows (must be 0 - OD-63 scopes him to his own) yet auto-filled cells=$($j15cells.Count) (must be > 0)"

# take it through to Completed, so T-J8f below has a Completed appraisal of its own
WfAction SupA $j15name "Submit for Review" | Out-Null
WfAction HRMgr $j15name "Approve" | Out-Null
$j15state = (Req HRMgr GET "/api/resource/Appraisal/$j15name").json.data.workflow_state
"        $j15name is now $j15state (needed by T-J8f)"

# T-J8c - an ordinary employee files STANDING feedback (no appraisal link).
# Blocked in chunk 1 by stock validate_appraisal(); the D60 override should fix it.
$epf = Ins SupA @{ doctype="Employee Performance Feedback"; employee=$EMP_B; company="CAF"
                   reviewer=$EMP_A; added_on="2026-08-05 10:00:00"
                   feedback="<p>ZZPROBE standing feedback</p>" }
$EPF1 = $epf.json.message.name
Res "T-J8c" ($epf.code -eq 200) "standing EPF with NO appraisal link: code=$($epf.code) name=$EPF1 : $($epf.err)"

# T-J8d - it scores 0 and cannot move any appraisal's average (D65)
if ($EPF1) {
  $subEpf = Req SupA PUT "/api/resource/Employee%20Performance%20Feedback/$EPF1" '{"docstatus":1}'
  $epfDoc = (Req HRMgr GET "/api/resource/Employee%20Performance%20Feedback/$EPF1").json.data
  Res "T-J8d" ($epfDoc.total_score -eq 0) "standing EPF submit=$($subEpf.code) total_score=$($epfDoc.total_score) (must be 0) ratings=$(@($epfDoc.feedback_ratings).Count)"
}

# T-J8f - feedback against an appraisal HR has already Completed (D64)
$j8f = Ins HRMgr @{ doctype="Employee Performance Feedback"; employee=$EMP_B; company="CAF"
                    reviewer="HR-EMP-00003"; added_on="2026-08-05 10:05:00"
                    feedback="<p>ZZPROBE against completed</p>"; appraisal=$j15name }
Res "T-J8f" ($j8f.code -ne 200 -and "$($j8f.err)" -match "completed|Completed") `
  "EPF linked to a Completed appraisal: code=$($j8f.code) : $($j8f.err)"

""
# --- put the org roots back to two -------------------------------------------
# T-H2 creates "ZZ Probe OrgRoot", a THIRD org root. Removing it only at the
# START of the next run left the site sitting on a D53 violation the whole time
# in between - and `deploy_appraisal_module` blocks on `len(roots) != 2`, so the
# suite was quietly failing the readiness gate it exists to protect.
$probes = (Req Admin GET "/api/resource/Employee?filters=%5B%5B%22first_name%22%2C%22like%22%2C%22ZZ%20Probe%25%22%5D%5D&limit_page_length=0").json.data
foreach ($p in @($probes)) { Req Admin DELETE "/api/resource/Employee/$($p.name)" | Out-Null }
$rootsNow = (Req Admin GET "/api/method/frappe.client.get_count?doctype=Employee&filters=%5B%5B%22status%22%2C%22%3D%22%2C%22Active%22%5D%2C%5B%22caf_reports_to_nobody%22%2C%22%3D%22%2C1%5D%5D").json.message
Res "T-H8" ($rootsNow -eq 2) "probe employees removed=$(@($probes).Count); active org roots left on the site=$rootsNow (must be 2 - D53)"

""
"CLEANUP HINTS: appraisals HR-APR-2026-*, employees ZZ Probe*, EPFs with ZZPROBE"
