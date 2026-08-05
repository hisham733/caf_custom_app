# CAF Appraisal chunk 1 - test plan section 2.10a: HR Settings permlevel 1 (D43)
# Every probe uses its own per-role token. Administrator is used ONLY where the
# test explicitly asks for System Manager, and that caveat is printed.

$ErrorActionPreference = "Continue"
# Credentials are NOT stored in this repo - see credentials.example.ps1.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$credFile = Join-Path $here "credentials.ps1"
if (-not (Test-Path $credFile)) {
  Write-Host "credentials.ps1 not found. Copy credentials.example.ps1 to credentials.ps1 and fill it in." -ForegroundColor Yellow
  exit 1
}
. $credFile
$U = $CAF_SITE_URL
$T = $CAF_TOKENS
# NOTE: do not name this function H - `h` is a built-in alias for Get-History
function CafHeader($role) { return @{ Authorization = "token $($T[$role])" } }

function Req($role, $method, $path, $body) {
  $p = @{ Uri = "$U$path"; Method = $method; Headers = (CafHeader $role); UseBasicParsing = $true; TimeoutSec = 30 }
  if ($body) { $p.Body = $body; $p.ContentType = "application/json" }
  try {
    $r = Invoke-WebRequest @p
    return @{ code = [int]$r.StatusCode; json = ($r.Content | ConvertFrom-Json) }
  } catch {
    $c = 0
    if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }
    return @{ code = $c; json = $null; err = $_.Exception.Message }
  }
}

# D44/D51/D67/D69 renamed the CAF settings fields. The test plan still lists
# caf_count_half_day_upl and caf_exempt_designations - both dropped.
# caf_appraisal_section is a Section Break: it carries no data and never
# appears in an API payload, so it is not probeable here.
$CAF = @("caf_enable_score_calculation","caf_min_late_minutes",
         "caf_attendance_leave_codes","caf_cycle_frequency")

# Values HR sets before the restricted-role reads, so a leak is visible as a
# VALUE, not merely as a key. Verified behaviour (Frappe 15.116):
#   apply_fieldlevel_read_permissions (document.py:768-774) DELETES the
#   attribute, but get_valid_dict (base_document.py:394-398) coerces Check ->
#   `1 if cint(value) else 0` and Int -> cint(value). cint(None) is 0, so Check
#   and Int fields REAPPEAR in the payload as 0. Data/Small Text/Select stay
#   None and are dropped. So key-absence is the wrong assertion for Check/Int;
#   value-non-disclosure is the right one.
$PROBE_SCORE = 1
$PROBE_LATE  = 42

function Result($id, $ok, $detail) {
  $tag = if ($ok) { "PASS" } else { "FAIL" }
  "{0,-7} {1,-6} {2}" -f $id, $tag, $detail
}

function CafKeys($j) {
  if (-not $j) { return @() }
  $props = $j.data.PSObject.Properties.Name
  return @($CAF | Where-Object { $props -contains $_ })
}

"=== 2.10a  HR Settings permlevel 1 (D43) ==="

# Seed distinctive values as HR Manager so any leak shows up as a real value
Req HRMgr PUT "/api/resource/HR%20Settings/HR%20Settings" "{""caf_enable_score_calculation"":$PROBE_SCORE,""caf_min_late_minutes"":$PROBE_LATE}" | Out-Null

# T-J1 - HR Manager sees the CAF fields, with the values just written
$r = Req HRMgr GET "/api/resource/HR%20Settings/HR%20Settings"
$present = CafKeys $r.json
$d = $r.json.data
$ok = ($r.code -eq 200 -and $present.Count -eq $CAF.Count -and
       $d.caf_enable_score_calculation -eq $PROBE_SCORE -and $d.caf_min_late_minutes -eq $PROBE_LATE -and
       $d.caf_attendance_leave_codes -and $d.caf_cycle_frequency)
Result "T-J1" $ok "HR Manager: code=$($r.code) fields=$($present.Count)/$($CAF.Count) score=$($d.caf_enable_score_calculation) late=$($d.caf_min_late_minutes) codes='$($d.caf_attendance_leave_codes)' freq=$($d.caf_cycle_frequency)"

# T-J2 - System Manager. Only Administrator holds System Manager on this site,
# and Administrator BYPASSES every check (apply_fieldlevel_read_permissions
# returns early, document.py:756) - so this confirms presence, not enforcement.
$r = Req Admin GET "/api/resource/HR%20Settings/HR%20Settings"
$present = CafKeys $r.json
Result "T-J2" ($r.code -eq 200 -and $present.Count -eq $CAF.Count) "System Manager (= Administrator; bypasses checks, so presence only): code=$($r.code) fields=$($present.Count)/$($CAF.Count)"

# T-J3 / T-J4 - the restricted roles must not learn any CAF POLICY VALUE.
# Text/Select fields vanish entirely; Check/Int reappear zeroed (see note above).
function NoLeak($role, $id, $label) {
  $r = Req $role GET "/api/resource/HR%20Settings/HR%20Settings"
  $d = $r.json.data
  $leaks = @()
  if ($d.caf_enable_score_calculation -eq $PROBE_SCORE) { $leaks += "caf_enable_score_calculation=$($d.caf_enable_score_calculation)" }
  if ($d.caf_min_late_minutes -eq $PROBE_LATE)          { $leaks += "caf_min_late_minutes=$($d.caf_min_late_minutes)" }
  if ($d.caf_attendance_leave_codes)                    { $leaks += "caf_attendance_leave_codes='$($d.caf_attendance_leave_codes)'" }
  if ($d.caf_cycle_frequency)                           { $leaks += "caf_cycle_frequency=$($d.caf_cycle_frequency)" }
  $keys = @($d.PSObject.Properties.Name | Where-Object { $_ -like 'caf_*' })
  Result $id ($r.code -eq 200 -and $leaks.Count -eq 0) "$label`: code=$($r.code) value-leaks=$($leaks.Count) [$($leaks -join '; ')] | keys still present (zeroed): [$($keys -join ',')]"
}
NoLeak EmpB   "T-J3" "Employee"
NoLeak HRUser "T-J4" "HR User"

# T-J5 - HR Manager writes caf_min_late_minutes = 15 and it persists
$r = Req HRMgr PUT "/api/resource/HR%20Settings/HR%20Settings" '{"caf_min_late_minutes":15}'
$check = Req HRMgr GET "/api/resource/HR%20Settings/HR%20Settings"
$v = $check.json.data.caf_min_late_minutes
Result "T-J5" ($v -eq 15) "HR Manager PUT 15: code=$($r.code) stored=$v"

# T-J6 - Employee and HR User write 99; the STORED value must still be 15.
# (protocol_session_2026-08-05 trap 3: the write is silently reset, HTTP 200.)
$rE = Req EmpB   PUT "/api/resource/HR%20Settings/HR%20Settings" '{"caf_min_late_minutes":99}'
$rU = Req HRUser PUT "/api/resource/HR%20Settings/HR%20Settings" '{"caf_min_late_minutes":99}'
$check = Req HRMgr GET "/api/resource/HR%20Settings/HR%20Settings"
$v = $check.json.data.caf_min_late_minutes
Result "T-J6" ($v -eq 15) "Employee PUT99 code=$($rE.code), HR User PUT99 code=$($rU.code); stored value re-read as HR Manager = $v (must be 15)"

# T-J7 - the regression that justifies permlevel over revoking Employee read
$r = Req EmpB GET "/api/method/frappe.client.get_value?doctype=HR%20Settings&fieldname=emp_created_by"
$val = $r.json.message.emp_created_by
Result "T-J7" ($r.code -eq 200 -and $val) "Employee reads stock emp_created_by: code=$($r.code) value=$val"

# restore the build/test defaults
Req HRMgr PUT "/api/resource/HR%20Settings/HR%20Settings" '{"caf_min_late_minutes":0,"caf_enable_score_calculation":0}' | Out-Null
$check = Req HRMgr GET "/api/resource/HR%20Settings/HR%20Settings"
"        note   restored: caf_min_late_minutes=$($check.json.data.caf_min_late_minutes) caf_enable_score_calculation=$($check.json.data.caf_enable_score_calculation)"
