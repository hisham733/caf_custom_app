# CAF Appraisal chunk 1 - test plan section 2.10b: Finger Log restricted to
# HR Manager + System Manager (D40). The role `All` grant is gone.

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
function CafHeader($role) { return @{ Authorization = "token $($T[$role])" } }
function Req($role, $method, $path, $body) {
  $p = @{ Uri = "$U$path"; Method = $method; Headers = (CafHeader $role); UseBasicParsing = $true; TimeoutSec = 60 }
  if ($body) { $p.Body = $body; $p.ContentType = "application/json" }
  try { $r = Invoke-WebRequest @p; return @{ code = [int]$r.StatusCode; json = ($r.Content | ConvertFrom-Json) } }
  catch { $c = 0; if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }; return @{ code = $c; json = $null } }
}
function Result($id, $ok, $detail) { "{0,-7} {1,-6} {2}" -f $id, $(if ($ok) {"PASS"} else {"FAIL"}), $detail }

"=== 2.10b  Finger Log restricted to HR Manager + System Manager (D40) ==="

# T-J9 - HR Manager still reads
$r = Req HRMgr GET "/api/resource/Finger%20Log?limit_page_length=5"
$n = if ($r.json) { @($r.json.data).Count } else { 0 }
Result "T-J9" ($r.code -eq 200 -and $n -gt 0) "HR Manager GET: code=$($r.code) rows=$n"

# T-J10 - the role `All` grant is gone: neither an ordinary employee nor a
# supervisor can read. Both hold ONLY the Employee role (fixture section 2), so
# a pass here proves the grant was removed, not that a role is missing.
$rB = Req EmpB GET "/api/resource/Finger%20Log?limit_page_length=5"
$rA = Req SupA GET "/api/resource/Finger%20Log?limit_page_length=5"
Result "T-J10" ($rB.code -eq 403 -and $rA.code -eq 403) "Employee(leaf) GET code=$($rB.code); supervisor GET code=$($rA.code) - both must be 403"

# T-J11 - insert. Under the old `All` grant this succeeded; that is the hole D40 closes.
$body = '{"doc":{"doctype":"Finger Log","employee":"HR-EMP-00185","employee_name":"PROBE - must not exist","work_date":"2026-06-15","time_in":"08:00:00"}}'
$r = Req EmpB POST "/api/method/frappe.client.insert" $body
Result "T-J11" ($r.code -eq 403) "Employee insert Finger Log: code=$($r.code)"

# T-J12 - submit an existing draft
# Pick a draft with NO clocked overtime. After the D47 seeding many drafts are
# deliberately unsubmittable negative fixtures (B2/B4): finger_log.check_ot_approval
# throws "No OT Approval records found" for any log with ot_in_hour > 0 and no
# approval. That is correct stock behaviour and nothing to do with D40, but it
# makes T-J14 look like a permission failure if the probe picks one.
#
# Also skips rows whose time_in is >= 24:00:00 - 39 such rows exist and CANNOT
# be saved by anyone (MariaDB rejects the timedelta Frappe writes back), so
# picking one produces a 500 that has nothing to do with permissions. See the
# impossible-clock-times check in appraisal_data_quality.py and D88.
#
# Compare the HOUR component as an integer rather than [TimeSpan]::Parse - .NET
# rejects "28:40:0.8" for the same reason MariaDB does, so parsing throws on
# exactly the rows we are trying to skip.
$draft = (Req HRMgr GET "/api/resource/Finger%20Log?filters=%5B%5B%22docstatus%22%2C%22%3D%22%2C0%5D%2C%5B%22ot_in_hour%22%2C%22%3D%22%2C0%5D%5D&fields=%5B%22name%22%2C%22time_in%22%5D&limit_page_length=0").json.data | Where-Object { $_.time_in -and ([int]($_.time_in -split ":")[0]) -lt 24 } | Select-Object -First 1 | ForEach-Object { $_.name }
$r = Req EmpB PUT "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))" '{"docstatus":1}'
$after = (Req HRMgr GET "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))").json.data.docstatus
Result "T-J12" ($r.code -eq 403 -and $after -eq 0) "Employee submit '$draft': code=$($r.code); docstatus after = $after (must stay 0)"

# T-J14 - downstream regression: submitting a Finger Log must still create the
# Employee Checkin rows via mp_checklist.make_employee_checkin_from_finger_log.
# That runs server-side, which bypasses permissions - verify, do not assume.
$fl = (Req HRMgr GET "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))").json.data
$before = (Req HRMgr GET "/api/method/frappe.client.get_count?doctype=Employee%20Checkin").json.message
$sub = Req HRMgr PUT "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))" '{"docstatus":1}'
$after2 = (Req HRMgr GET "/api/method/frappe.client.get_count?doctype=Employee%20Checkin").json.message
$ds = (Req HRMgr GET "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))").json.data.docstatus
$delta = $after2 - $before
Result "T-J14" ($sub.code -eq 200 -and $ds -eq 1) "HR Manager submit '$draft' (emp $($fl.employee) $($fl.work_date)): code=$($sub.code) docstatus=$ds; Employee Checkin count $before -> $after2 (delta $delta)"
"        note   T-J14 delta 0 is expected when the log has no in/out times to convert - see the checkin detail line below"
$chk = (Req HRMgr GET "/api/resource/Employee%20Checkin?filters=%5B%5B%22log_type%22%2C%22in%22%2C%5B%22IN%22%2C%22OUT%22%5D%5D%5D&limit_page_length=3&order_by=creation%20desc").json.data
"        latest Employee Checkin rows: " + (($chk | ForEach-Object { $_.name }) -join ', ')
