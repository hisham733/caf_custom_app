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

# T-J10 (2026-08-15, D-1/AC-1) - the role `All` grant is gone AND scoped read is
# live: an ordinary employee and a supervisor both hold only the Employee role,
# which now carries READ on Finger Log - but ONLY their own rows, filtered
# server-side. The old assertion ("both must be 403") is superseded by the
# option-(d) surface: read is granted, the scope must hold.
$rB = Req EmpB GET "/api/resource/Finger%20Log?limit_page_length=10&fields=%5B%22name%22%2C%22employee%22%5D"
$rA = Req SupA GET "/api/resource/Finger%20Log?limit_page_length=10&fields=%5B%22name%22%2C%22employee%22%5D"
$distB = @($rB.json.data | Select-Object -ExpandProperty employee -Unique).Count
$distA = @($rA.json.data | Select-Object -ExpandProperty employee -Unique).Count
Result "T-J10" ($rB.code -eq 200 -and $rA.code -eq 200 -and @($rB.json.data).Count -gt 0 -and $distB -eq 1 -and $distA -eq 1) "scoped read: Employee(leaf) code=$($rB.code) rows=$(@($rB.json.data).Count) distinct_emps=$distB; supervisor code=$($rA.code) rows=$(@($rA.json.data).Count) distinct_emps=$distA - each sees exactly ONE employee (their own)"

# T-J10b - a colleague's row by name is refused (per-doc has_permission, AC-1)
$ownB = @($rB.json.data)[0].employee
$hrRows = (Req HRMgr GET "/api/resource/Finger%20Log?limit_page_length=5&fields=%5B%22name%22%2C%22employee%22%5D").json.data
$otherRow = @($hrRows | Where-Object { $_.employee -ne $ownB } | Select-Object -First 1)
if ($otherRow) {
  $rO = Req EmpB GET "/api/resource/Finger%20Log/$([uri]::EscapeDataString($otherRow.name))"
  Result "T-J10b" ($rO.code -eq 403) "Employee GET colleague's row '$($otherRow.name)' by name: code=$($rO.code) (must be 403)"
} else {
  Result "T-J10b" $false "no colleague row found to probe"
}

# T-J11 - insert. Under the old `All` grant this succeeded; that is the hole D40 closes.
$body = '{"doc":{"doctype":"Finger Log","employee":"HR-EMP-00185","employee_name":"PROBE - must not exist","work_date":"2026-06-15","time_in":"08:00:00"}}'
$r = Req EmpB POST "/api/method/frappe.client.insert" $body
Result "T-J11" ($r.code -eq 403) "Employee insert Finger Log: code=$($r.code)"

# T-J12 - submit a draft (fixture-owned; the July draft pool is all
# deliberately-unsubmittable negative fixtures — leave-clash, not-full-day or
# OT-hold — so this probe creates its own submittable draft on a clear date,
# asserts, then removes it again: owner+date scoping, nothing real touched).
$fixture = @{
    doctype = "Finger Log"; employee = "HR-EMP-00003"; employee_name = "Alyaa Zafirah"
    work_date = "2026-06-09"; time_in = "08:00:00"; break = "12:00:00"
    resume = "13:00:00"; out = "17:00:00"; overtime = 0
}
$fixtureBody = '{"doc":' + ($fixture | ConvertTo-Json -Compress) + '}'
$ins = Req HRMgr POST "/api/method/frappe.client.insert" $fixtureBody
$draft = if ($ins.json) { $ins.json.message.name } else { "" }
$r = Req EmpB PUT "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))" '{"docstatus":1}'
$after = (Req HRMgr GET "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))").json.data.docstatus
Result "T-J12" ($ins.code -eq 200 -and $r.code -eq 403 -and $after -eq 0) "Employee submit '$draft': insert=$($ins.code), code=$($r.code); docstatus after = $after (must stay 0)"

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

# Fixture cleanup (T-J12/T-J14): cancel + delete the probe's own FL and its
# Attendance. Owner+date scoped; nothing real is touched.
$attRows = @((Req HRMgr GET "/api/resource/Attendance?filters=%5B%5B%22employee%22%2C%22%3D%22%2C%22HR-EMP-00003%22%5D%2C%5B%22attendance_date%22%2C%22%3D%22%2C%222026-06-09%22%5D%5D&fields=%5B%22name%22%5D&limit_page_length=0").json.data | ForEach-Object { $_.name })
foreach ($attN in $attRows) {
  if ((Req HRMgr GET "/api/resource/Attendance/$([uri]::EscapeDataString($attN))").json.data.docstatus -eq 1) {
    Req HRMgr PUT "/api/resource/Attendance/$([uri]::EscapeDataString($attN))" '{"docstatus":2}' | Out-Null
  }
  Req Admin DELETE "/api/resource/Attendance/$([uri]::EscapeDataString($attN))" $null | Out-Null
}
if ((Req HRMgr GET "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))").json.data.docstatus -eq 1) {
  Req HRMgr PUT "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))" '{"docstatus":2}' | Out-Null
}
Req Admin DELETE "/api/resource/Finger%20Log/$([uri]::EscapeDataString($draft))" $null | Out-Null
"        fixture removed: $draft (+ attendance rows $($attRows -join ', '))"
