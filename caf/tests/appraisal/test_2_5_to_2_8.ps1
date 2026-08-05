# CAF Appraisal chunk 2 - test plan 2.5 to 2.8, plus the five carried over from
# chunk 1 (T-I3, T-J8c, T-J8d, T-J8f, T-J15).
# Today is 2026-08-05, so cycle 2026-08 is the CURRENT, unfinished month - that
# is what makes the BR6 tests meaningful.

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
$EMP_B = "HR-EMP-00185"; $EMP_D = "HR-EMP-00022"; $EMP_A = "HR-EMP-00024"
$PAST = "2026-06"; $CURRENT = "2026-08"

function CafHeader($role) { return @{ Authorization = "token $($T[$role])" } }
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
# NOTE: uses EMP-D + 2026-05, NOT EMP-B + 2026-06. The 2.1 script already gives
# EMP-B an appraisal for 2026-06, so reusing that pair hits the duplicate guard,
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
$lC = Req SupC GET "/api/resource/Appraisal?limit_page_length=0&fields=%5B%22employee%22%5D"
$seen = @(@($lC.json.data) | ForEach-Object { $_.employee } | Sort-Object -Unique)
$rootBBranch = @("HR-EMP-00036","HR-EMP-00042","HR-EMP-00047","HR-EMP-00051","HR-EMP-00030","HR-EMP-00028")
$leak = @($seen | Where-Object { $rootBBranch -contains $_ })
Res "T-H6" ($leak.Count -eq 0) "supervisor in Director A's tree sees [$($seen -join ', ')]; leaks from Director B's tree: $($leak.Count)"

""
"=== carried over from chunk 1 ==="

# T-I3 - the headline proof of D55: no role gates this, the tree does
$i3 = Ins EmpB @{ doctype="Appraisal"; employee=$EMP_B; appraisal_cycle="2026-09"; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
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
$fl = Req SupA GET "/api/resource/Finger%20Log?limit_page_length=1"
$j15 = Ins SupA @{ doctype="Appraisal"; employee=$EMP_B; appraisal_cycle=$PAST; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
$j15name = $j15.json.message.name
$j15doc = (Req HRMgr GET "/api/resource/Appraisal/$j15name").json.data
$j15cells = @(@($j15doc.appraisal_kra) | Where-Object { $_.caf_date_cell })
Res "T-J15" ($fl.code -eq 403 -and $j15cells.Count -gt 0) `
  "supervisor's direct Finger Log read=$($fl.code) (must be 403) yet auto-filled cells=$($j15cells.Count) (must be > 0)"

# take it through to Completed, so T-J8f below has a Completed appraisal of its own
WfAction SupA $j15name "Submit for Review" | Out-Null
WfAction HRMgr $j15name "Approve" | Out-Null
$j15state = (Req HRMgr GET "/api/resource/Appraisal/$j15name").json.data.workflow_state
"        $j15name is now $j15state (needed by T-J8f)"

# T-J8c - an ordinary employee files STANDING feedback (no appraisal link).
# Blocked in chunk 1 by stock validate_appraisal(); the D60 override should fix it.
$epf = Ins SupA @{ doctype="Employee Performance Feedback"; employee=$EMP_B; company="CAF"
                   reviewer="HR-EMP-00024"; added_on="2026-08-05 10:00:00"
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
"CLEANUP HINTS: appraisals HR-APR-2026-*, employees ZZ Probe*, EPFs with ZZPROBE"
