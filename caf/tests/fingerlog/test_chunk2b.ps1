# CAF Finger Log / OT overhaul - Chunk 2b scenarios
# =================================================
# Covers the rows of CAF_fingerlog_test_plan.md marked "testable from 2b":
#   W3  workday past the OT gate, no OT Approval        -> cannot submit (FBR11)
#   W4  OT exceeds the approved duration                -> refused
#   W8  shift with caf_allow_ot = 0, works late         -> ot_in_hour 0, no error
#   E1  employee with no shift at all                   -> refuses loudly
#   E2  public holiday landing on a shift's rest day    -> Restday wins
#   E3  one Saturday, two employees, both directions    -> OD-52
# plus the Chunk 2 checkpoint itself:
#   C1  a rest Saturday resolves Restday and every hour is OT (FBR4)
#   C2  two employees, same date, different day_type
#
# W2 appears as a positive control only - without it, W4 passes on a Finger Log
# that could not have submitted for an unrelated reason.
#
# RE-RUNNABLE: every artifact is removed FIRST, not last. The appraisal suite
# once failed on the previous run's leftover draft rather than on anything real.

$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Finger Log is restricted to HR Manager + System Manager (D40), and none of
# these scenarios turn on permissions - they are server-logic and document
# lifecycle. The suite reuses the appraisal credentials rather than duplicating
# tokens into a second file.
$credFile = Join-Path $here "credentials.ps1"
if (-not (Test-Path $credFile)) { $credFile = Join-Path $here "..\appraisal\credentials.ps1" }
if (-not (Test-Path $credFile)) {
  Write-Host "credentials.ps1 not found - see ..\appraisal\credentials.example.ps1" -ForegroundColor Yellow
  exit 1
}
. $credFile
$U = $CAF_SITE_URL
$ROLE = "HRMgr"

function CafHeader($role) { return @{ Authorization = "token $($CAF_TOKENS[$role])" } }
function Req($method, $path, $body) { return ReqAs $ROLE $method $path $body }
function ReqAs($role, $method, $path, $body) {
  $p = @{ Uri = "$U$path"; Method = $method; Headers = (CafHeader $role); UseBasicParsing = $true; TimeoutSec = 60 }
  if ($body) { $p.Body = $body; $p.ContentType = "application/json" }
  try {
    $r = Invoke-WebRequest @p
    return @{ code = [int]$r.StatusCode; json = ($r.Content | ConvertFrom-Json); err = "" }
  } catch {
    # PowerShell 7 exposes the response BODY on ErrorDetails; the raw stream has
    # usually already been consumed by then. Reading the stream instead yields an
    # empty string, which silently turns every "did it say why?" assertion into a
    # false negative - it did say why, we just never looked.
    $c = 0
    $msg = $_.ErrorDetails.Message
    if (-not $msg) { $msg = $_.Exception.Message }
    if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }
    return @{ code = $c; json = $null; err = $msg }
  }
}
function Esc($s) { return [uri]::EscapeDataString($s) }
function Result($id, $ok, $detail) {
  $tag = if ($ok) { "PASS" } else { "FAIL" }
  $col = if ($ok) { "Green" } else { "Red" }
  Write-Host ("{0,-5} {1,-5} {2}" -f $id, $tag, $detail) -ForegroundColor $col
}

# ---------------------------------------------------------------- fixtures
$EMP_OT     = "HR-EMP-00016"   # 8am Schedule     - caf_allow_ot 1, gate 30, round 30
$EMP_NOOT   = "HR-EMP-00011"   # 8:30am Schedule  - caf_allow_ot 0
$EMP_NOSHIFT= "HR-EMP-00002"   # no default_shift, no assignment - the E1 case
$EMP_MONFRI = "HR-EMP-00127"   # 8am no OT no Sat - Saturday is a rest day
$EMP_SWAP   = "HR-EMP-00003"   # seeded rest-Saturday assignments
$EMP_RESTOT = "HR-EMP-00042"   # Special 8-5 -> rests onto `special`, which keeps OT

# ⚠️ These dates must be free of PRE-EXISTING OT Approvals. Dev carries 7,006 of
# them, latest work_date 2026-08-06, and an earlier draft of this suite used
# June 2026 - where HR-EMP-00016 already had approvals on all three dates. W3
# then "passed" for entirely the wrong reason: it refused because 2.0 h exceeded
# a pre-existing 1.5 h approval, not because no approval existed. September is
# past the end of the seeded data, and CheckDateIsClean asserts it rather than
# trusting it.
$D_WED = "2026-09-09"   # plain Workday, no public holiday that week
$D_THU = "2026-09-10"
$D_FRI = "2026-09-11"
$D_PH_SAT = "2026-03-21"   # HARI RAYA PUASA, and it falls on a Saturday

$ALL_EMP = @($EMP_OT, $EMP_NOOT, $EMP_NOSHIFT, $EMP_MONFRI, $EMP_SWAP, $EMP_RESTOT)

# ⚠️ The swap date is DERIVED, never hardcoded. seed_rest_saturdays seeds a
# rolling SEED_MONTHS window, so any literal date here rots the moment the
# window moves - which it did: an earlier revision pinned 2026-01-03 and E3
# started failing when the window narrowed to 3 months.
function FirstAssignment($emp) {
  $f = Esc ('[["employee","=","' + $emp + '"],["docstatus","=",1]]')
  $r = (Req GET "/api/resource/Shift%20Assignment?filters=$f&fields=%5B%22start_date%22%2C%22shift_type%22%5D&order_by=start_date&limit_page_length=1").json.data
  # Remember it so Cleanup can scope itself to the dates this suite touched.
  if ($r) { $script:DERIVED_DATES += $r[0].start_date }
  return $r
}
$script:DERIVED_DATES = @()

# ---------------------------------------------------------------- cleanup FIRST
# ⚠️ Cleanup runs as Admin, and ONLY cleanup does. HR Manager holds `cancel` but
# NOT `delete` on Finger Log - which is right, HR should not be able to destroy
# attendance evidence - so a DELETE sent as HR Manager is a silent no-op. An
# earlier version of this suite did exactly that and left 36 logs behind across
# four runs while every scenario still reported PASS. Deleting is not the thing
# under test; the scenarios themselves all run as $ROLE.
function Purge($doctype, $filters) {
  $enc = [uri]::EscapeDataString($doctype)
  $f = Esc $filters
  $rows = (ReqAs Admin GET "/api/resource/$enc`?filters=$f&fields=%5B%22name%22%2C%22docstatus%22%5D&limit_page_length=0").json.data
  $left = 0
  foreach ($r in $rows) {
    if ($r.docstatus -eq 1) { ReqAs Admin PUT "/api/resource/$enc/$(Esc $r.name)" '{"docstatus":2}' | Out-Null }
    $d = ReqAs Admin DELETE "/api/resource/$enc/$(Esc $r.name)"
    if ($d.code -ne 202 -and $d.code -ne 200) { $left++ }
  }
  return $left
}

function Cleanup {
  # ⚠️ Server-side. REST cannot set `ignore_links`, and stock refuses to cancel
  # or delete a Finger Log while Attendance links back to it (spec §6.3), so an
  # HTTP-only cleanup leaves a SUBMITTED log behind and the next run's insert
  # fails as a 405 built from a null name. See purge.py.
  $out = wsl docker exec -w /workspace/development/frappe-bench frappe `
         bench --site development.localhost execute caf.tests.fingerlog.purge.run 2>&1
  $line = $out | Select-String -Pattern "^purged" | Select-Object -First 1
  if ($line) { Write-Host "      $line" -ForegroundColor DarkGray }
  if ($line -match "(\d+) stuck" -and [int]$Matches[1] -gt 0) { return [int]$Matches[1] }
  return 0
}

function CleanupRest {
  $left = 0
  # ⚠️ Scoped to the suite's OWN employees AND its OWN dates. An earlier version
  # purged every Finger Log for the fixture employees whatever the date - which
  # was harmless while the table was empty, and became DESTRUCTIVE the moment
  # Chunk 3's importer put real rows in it: one run ate ~50 imported July logs.
  # A test suite must never be able to delete data it did not create.
  $dates = @($ALL_DATES + $script:DERIVED_DATES | Where-Object { $_ }) | Sort-Object -Unique
  $f = '[["employee","in",["' + ($ALL_EMP -join '","') + '"]],' +
       '["work_date","in",["' + ($dates -join '","') + '"]]]'

  # ⚠️ Chunk 3 made Attendance link back to Finger Log, and that link BLOCKS the
  # Finger Log's deletion even once the Attendance is cancelled. Each log's
  # children are cleared IMMEDIATELY BEFORE that log is removed - a single
  # pre-pass is not enough, because cancelling a log can itself touch Attendance,
  # so rows fetched up front go stale and one submitted log survives every run.
  $logs = (ReqAs Admin GET "/api/resource/Finger%20Log?filters=$(Esc $f)&fields=%5B%22name%22%2C%22docstatus%22%5D&limit_page_length=0").json.data
  foreach ($fl in $logs) {
    $af = Esc ('[["caf_finger_log","=","' + $fl.name + '"]]')
    foreach ($a in (ReqAs Admin GET "/api/resource/Attendance?filters=$af&fields=%5B%22name%22%2C%22docstatus%22%5D&limit_page_length=0").json.data) {
      if ($a.docstatus -eq 1) { ReqAs Admin PUT "/api/resource/Attendance/$(Esc $a.name)" '{"docstatus":2}' | Out-Null }
      ReqAs Admin DELETE "/api/resource/Attendance/$(Esc $a.name)" | Out-Null
    }
    if ($fl.docstatus -eq 1) { ReqAs Admin PUT "/api/resource/Finger%20Log/$(Esc $fl.name)" '{"docstatus":2}' | Out-Null }
    # cancelling may have created or cancelled Attendance - clear again
    foreach ($a in (ReqAs Admin GET "/api/resource/Attendance?filters=$af&fields=%5B%22name%22%5D&limit_page_length=0").json.data) {
      ReqAs Admin DELETE "/api/resource/Attendance/$(Esc $a.name)" | Out-Null
    }
    ReqAs Admin DELETE "/api/resource/Finger%20Log/$(Esc $fl.name)" | Out-Null

    # What actually matters is that nothing SUBMITTED survives: check_previous_submission
    # filters docstatus=1, so a cancelled leftover cannot poison the next run, but a
    # submitted one makes the very next insert fail with a 405 built from a null name.
    # Deleting can legitimately fail here - stock refuses to delete a doc another
    # document links to, and Attendance links back (spec 6.3) - so assert the state
    # that matters rather than the operation.
    $still = (ReqAs Admin GET "/api/resource/Finger%20Log/$(Esc $fl.name)").json.data
    if ($still -and $still.docstatus -eq 1) { $left++ }
  }
  # OT Approvals created by this suite carry the marker in `reason`
  $left += Purge "OT Approval" '[["reason","like","%CHUNK2B TEST%"]]'
  if ($left -gt 0) {
    Write-Host "      ! $left document(s) could not be removed" -ForegroundColor DarkYellow
  }
  return $left
}

function NewLog($emp, $date, $overtime, $timeIn, $timeOut) {
  $name = (Req GET "/api/resource/Employee/$(Esc $emp)?fields=%5B%22employee_name%22%5D").json.data.employee_name
  $doc = @{
    doctype = "Finger Log"; employee = $emp; employee_name = $name
    work_date = $date; time_in = $timeIn; out = $timeOut; overtime = $overtime
  }
  $body = (@{ doc = $doc } | ConvertTo-Json -Depth 5 -Compress)
  return Req POST "/api/method/frappe.client.insert" $body
}

# ot_approval.check_ot_duration() recomputes the duration from start_work/ot_end
# minus the shift's own hours and REFUSES a mismatch, so both times are real.
# $EMP_OT is on 8am Schedule, 08:00-16:30 = 8.5 h, so 18:30 gives 2.0 h of OT
# and 17:30 gives 1.0 h.
function NewApproval($emp, $date, $duration, $startWork, $otEnd, $type) {
  $dept = (Req GET "/api/resource/Employee/$(Esc $emp)?fields=%5B%22department%22%5D").json.data.department
  $doc = @{
    doctype = "OT Approval"; work_date = $date; type = $type
    ot_department = $dept; reason = "CHUNK2B TEST"
    emp_list = @(@{ emp_id = $emp; work_date = $date; ot_duration = $duration
                    start_work = $startWork; ot_end = $otEnd })
  }
  $body = (@{ doc = $doc } | ConvertTo-Json -Depth 6 -Compress)
  $r = Req POST "/api/method/frappe.client.insert" $body
  if ($r.code -ne 200) {
    Write-Host ("      ! OT Approval insert failed for {0} {1}: {2}" -f $emp, $date, ($r.err -replace '\s+', ' ').Substring(0, [Math]::Min(160, $r.err.Length))) -ForegroundColor DarkYellow
    return $r
  }
  $sub = Req PUT "/api/resource/OT%20Approval/$(Esc $r.json.message.name)" '{"docstatus":1}'
  if ($sub.code -ne 200) {
    Write-Host ("      ! OT Approval submit failed for {0} {1}" -f $emp, $date) -ForegroundColor DarkYellow
  }
  return $r
}

# A pre-existing approval on a W-date makes the OT scenarios prove the wrong
# thing. Assert the fixture rather than assuming it.
function CheckDateIsClean($emp, $date) {
  $f = Esc ('[["emp_id","=","' + $emp + '"],["work_date","=","' + $date + '"],["docstatus","=",1]]')
  $rows = (Req GET "/api/resource/OT%20Approval%20Table?filters=$f&fields=%5B%22parent%22%2C%22ot_duration%22%5D&parent=OT%20Approval&limit_page_length=0").json.data
  return @($rows).Count
}

Write-Host "=== CAF Chunk 2b - Finger Log scenarios ===" -ForegroundColor Cyan
Write-Host "cleaning up previous artifacts first..."
# Out-Null because a PowerShell function returns everything it emits, and
# Cleanup's count would otherwise print itself into the report.
Cleanup | Out-Null

$dirty = 0
foreach ($d in @($D_WED, $D_THU, $D_FRI)) { $dirty += (CheckDateIsClean $EMP_OT $d) }
Result "FIX" ($dirty -eq 0) "test dates carry $dirty pre-existing OT Approval rows for $EMP_OT (must be 0, or W2/W3/W4 prove nothing)"

# ---------------------------------------------------------------- E1
# No Shift Assignment and no default_shift. The resolver returns None and the
# import must refuse LOUDLY - guessing a shift would silently invent the rules
# the day is judged by.
$r = NewLog $EMP_NOSHIFT $D_WED 0 "08:00:00" "17:00:00"
$saidWhy = $r.err -match "no shift"
Result "E1" ($r.code -ne 200 -and $saidWhy) "no-shift employee insert: code=$($r.code); message names the reason=$saidWhy"

# ---------------------------------------------------------------- E2
# A public holiday landing on a shift's rest day. Restday must win: the employee
# was never scheduled, and Restday / Holiday OT are paid at different rates, so
# collapsing the two is a real money difference.
$rMonSat = NewLog $EMP_OT $D_PH_SAT 0 "08:00:00" "16:30:00"
$rMonFri = NewLog $EMP_MONFRI $D_PH_SAT 0 "08:00:00" "16:30:00"
$dtMonSat = $rMonSat.json.message.day_type
$dtMonFri = $rMonFri.json.message.day_type
Result "E2" ($dtMonSat -eq "Holiday" -and $dtMonFri -eq "Restday") `
  "$D_PH_SAT (public holiday, a Saturday): Mon-Sat employee=$dtMonSat, Mon-Fri employee=$dtMonFri"

# ---------------------------------------------------------------- E3 / C2
# One Saturday, two employees, opposite verdicts - OD-52. The swap employee has
# a Shift Assignment onto a no-Saturday shift; the control has none.
$swap = FirstAssignment $EMP_SWAP
if ($swap) {
  $D_SWAP = $swap[0].start_date
  $rRest = NewLog $EMP_SWAP $D_SWAP 0 "00:00:00" "00:00:00"
  $rWork = NewLog $EMP_OT $D_SWAP 0 "08:00:00" "16:30:00"
  $dtRest = $rRest.json.message.day_type
  $dtWork = $rWork.json.message.day_type
  $shRest = $rRest.json.message.shift_type
  $shWork = $rWork.json.message.shift_type
  Result "E3" ($dtRest -eq "Restday" -and $dtWork -eq "Workday") `
    "${D_SWAP}: $EMP_SWAP=$dtRest (shift $shRest) vs $EMP_OT=$dtWork (shift $shWork)"
  Result "C2" ($dtRest -ne $dtWork) "same date, different day_type for two employees - FDR6 / OD-52"
} else {
  Result "E3" $false "no Shift Assignment for $EMP_SWAP - run caf.scripts.seed_rest_saturdays.seed"
  Result "C2" $false "skipped, depends on E3's fixture"
}

# ---------------------------------------------------------------- W3
# Past the gate, no OT Approval anywhere. FBR11: OT ALWAYS needs an approval, so
# the log must refuse to submit and sit at docstatus 0.
$r = NewLog $EMP_OT $D_WED 2.00 "08:00:00" "18:30:00"
$name = $r.json.message.name
$otHours = $r.json.message.ot_in_hour
$sub = Req PUT "/api/resource/Finger%20Log/$(Esc $name)" '{"docstatus":1}'
$after = (Req GET "/api/resource/Finger%20Log/$(Esc $name)").json.data.docstatus
# The REASON matters: "no approval at all" and "approval too small" are different
# refusals, and only the first one is W3.
$saidWhy = $sub.err -match "No OT Approval records found"
Result "W3" ($otHours -eq 2.0 -and $sub.code -ne 200 -and $after -eq 0 -and $saidWhy) `
  "overtime 2.00 -> ot_in_hour=$otHours; submit code=$($sub.code); docstatus stays $after; refused for absence of an approval=$saidWhy"

# ---------------------------------------------------------------- W2 (control)
# Same shape as W3 but WITH a sufficient approval. Without this control, W4's
# refusal proves nothing - the log might be unsubmittable for another reason.
NewApproval $EMP_OT $D_FRI 2.0 "08:00:00" "18:30:00" "normal" | Out-Null
$r = NewLog $EMP_OT $D_FRI 2.00 "08:00:00" "18:30:00"
$name = $r.json.message.name
$sub = Req PUT "/api/resource/Finger%20Log/$(Esc $name)" '{"docstatus":1}'
$doc = (Req GET "/api/resource/Finger%20Log/$(Esc $name)").json.data
Result "W2" ($sub.code -eq 200 -and $doc.docstatus -eq 1 -and $doc.final_ot -eq 2.0) `
  "approved 2.0h, clocked 2.00 -> submit code=$($sub.code) docstatus=$($doc.docstatus) final_ot=$($doc.final_ot)"

# ---------------------------------------------------------------- W4
# The approval exists but is too small. Refused.
NewApproval $EMP_OT $D_THU 1.0 "08:00:00" "17:30:00" "normal" | Out-Null
$r = NewLog $EMP_OT $D_THU 2.00 "08:00:00" "18:30:00"
$name = $r.json.message.name
$sub = Req PUT "/api/resource/Finger%20Log/$(Esc $name)" '{"docstatus":1}'
$after = (Req GET "/api/resource/Finger%20Log/$(Esc $name)").json.data.docstatus
$saidWhy = $sub.err -match "greater than approved"
Result "W4" ($sub.code -ne 200 -and $after -eq 0 -and $saidWhy) `
  "approved 1.0h, clocked 2.00 -> submit code=$($sub.code); docstatus stays $after; reason given=$saidWhy"

# ---------------------------------------------------------------- W8
# caf_allow_ot = 0. He worked late; there is no OT, no approval is needed, and
# crucially NO ERROR - the old code reached this via a hardcoded shift list.
$r = NewLog $EMP_NOOT $D_WED 2.00 "08:30:00" "19:30:00"
$name = $r.json.message.name
$otHours = $r.json.message.ot_in_hour
$sub = Req PUT "/api/resource/Finger%20Log/$(Esc $name)" '{"docstatus":1}'
$doc = (Req GET "/api/resource/Finger%20Log/$(Esc $name)").json.data
Result "W8" ($otHours -eq 0 -and $sub.code -eq 200 -and $doc.docstatus -eq 1) `
  "caf_allow_ot=0, overtime 2.00 -> ot_in_hour=$otHours; submit code=$($sub.code) docstatus=$($doc.docstatus)"

# ---------------------------------------------------------------- C1
# The Chunk 2 checkpoint. A rest Saturday, and the hours worked on it are OT
# (FBR4). The rest shift must preserve OT eligibility - two of CAF's three
# no-Saturday shifts carry caf_allow_ot = 0, so a careless assignment would
# silently zero this and the test would pass for the wrong reason.
$sa = FirstAssignment $EMP_RESTOT
if ($sa) {
  $dRest = $sa[0].start_date
  $r = NewLog $EMP_RESTOT $dRest 3.00 "08:00:00" "11:00:00"
  $dt = $r.json.message.day_type
  $ot = $r.json.message.ot_in_hour
  Result "C1" ($dt -eq "Restday" -and $ot -eq 3.0) `
    "$dRest on rest shift $($sa[0].shift_type): day_type=$dt ot_in_hour=$ot (all 3 clocked hours are OT - FBR4)"
} else {
  Result "C1" $false "no Shift Assignment found for $EMP_RESTOT - run caf.scripts.seed_rest_saturdays.seed"
}

Write-Host ""
Write-Host "cleaning up..."
$stuck = Cleanup
# Assert the cleanup worked - scoped to THIS suite's rows. Asserting the whole
# table is empty was right when Finger Log had 0 rows and became wrong the moment
# the Chunk 3 importer existed; it would now fail on legitimate data.
$dates = @($ALL_DATES + $script:DERIVED_DATES | Where-Object { $_ }) | Sort-Object -Unique
$f = Esc ('[["employee","in",["' + ($ALL_EMP -join '","') + '"]],["work_date","in",["' + ($dates -join '","') + '"]]]')
$f2 = Esc ('[["employee","in",["' + ($ALL_EMP -join '","') + '"]],["work_date","in",["' + ($dates -join '","') + '"]],["docstatus","=",1]]')
$remain = @((ReqAs Admin GET "/api/resource/Finger%20Log?filters=$f2&fields=%5B%22name%22%5D&limit_page_length=0").json.data).Count
Result "CLN" ($stuck -eq 0 -and $remain -eq 0) "after cleanup: $remain SUBMITTED Finger Log(s) of this suite remain (must be 0), $stuck stuck"
Write-Host "done." -ForegroundColor Cyan
