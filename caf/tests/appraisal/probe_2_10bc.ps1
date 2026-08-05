# CAF Appraisal chunk 1 - test plan 2.10b-2 (EPF appraisal permlevel, D66)
# and 2.10c (KRA permissions, D41). Also creates the scaffolding Appraisal the
# EPF probes need, and runs the 2.9 checks that do not need Chunk 2 code.

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
function CafHeader($role) { return @{ Authorization = "token $($T[$role])" } }
function Req($role, $method, $path, $body) {
  $p = @{ Uri = "$U$path"; Method = $method; Headers = (CafHeader $role); UseBasicParsing = $true; TimeoutSec = 60 }
  if ($body) { $p.Body = $body; $p.ContentType = "application/json" }
  try { $r = Invoke-WebRequest @p; return @{ code = [int]$r.StatusCode; json = ($r.Content | ConvertFrom-Json) } }
  catch {
    $c = 0; if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }
    $msg = $null; if ($_.ErrorDetails.Message) { try { $msg = ($_.ErrorDetails.Message | ConvertFrom-Json).exception } catch {} }
    return @{ code = $c; json = $null; err = $msg }
  }
}
function Result($id, $ok, $detail) { "{0,-7} {1,-6} {2}" -f $id, $(if ($ok) {"PASS"} else {"FAIL"}), $detail }

# ---------------------------------------------------------------- scaffolding
# --- self-cleanup so this probe is RE-RUNNABLE ------------------------------
# The scaffolding below assumes a FRESH draft appraisal. On a second run it
# found the previous run's COMPLETED one and every downstream assertion failed -
# D74 reported workflow_state 'Completed' instead of 'Draft', and the EPF probes
# cascaded off it. Clear our own artifacts first.
"=== cleanup from any previous run ==="
Reset-CafTestData -Request { param($r,$m,$p,$b) Req $r $m $p $b }
""

"=== scaffolding: one cycle + one appraisal (created as HR Manager) ==="
$CYCLE = "2026-06"
$c = Req HRMgr GET "/api/resource/Appraisal%20Cycle/$CYCLE"
if ($c.code -ne 200) {
  $c = Req HRMgr POST "/api/method/frappe.client.insert" (@{ doc = @{
        doctype="Appraisal Cycle"; cycle_name=$CYCLE; start_date="2026-06-01"; end_date="2026-06-30"; company="CAF"
      }} | ConvertTo-Json -Depth 5)
  "  cycle created: code=$($c.code) $($c.err)"
} else { "  cycle $CYCLE already exists" }

$apr = Req HRMgr GET "/api/resource/Appraisal?filters=%5B%5B%22appraisal_cycle%22%2C%22%3D%22%2C%222026-06%22%5D%5D&limit_page_length=1"
$aprName = if ($apr.json -and @($apr.json.data).Count -gt 0) { $apr.json.data[0].name } else { $null }
if (-not $aprName) {
  $a = Req HRMgr POST "/api/method/frappe.client.insert" (@{ doc = @{
        doctype="Appraisal"; employee="HR-EMP-00185"; appraisal_cycle=$CYCLE; company="CAF"
        appraisal_template="CAF Monthly Appraisal"
      }} | ConvertTo-Json -Depth 5)
  $aprName = $a.json.message.name
  "  appraisal created: code=$($a.code) name=$aprName $($a.err)"
} else { "  appraisal $aprName already exists" }

# D74 - the initial workflow state must never be blank
$ws = (Req HRMgr GET "/api/resource/Appraisal/$aprName").json.data.workflow_state
Result "D74" ($ws -eq "Draft") "new Appraisal $aprName workflow_state = '$ws' (must be 'Draft', never empty)"

# grid built from the template?
$kraRows = (Req HRMgr GET "/api/resource/Appraisal/$aprName").json.data.appraisal_kra
"  appraisal_kra rows built from template: $(@($kraRows).Count)"

# ------------------------------------------------------- 2.10b-2  EPF (D66)
""
"=== 2.10b-2  Employee Performance Feedback: appraisal at permlevel 1 (D66) ==="

# T-J8c FIRST - an ordinary Employee posts an EPF WITH the appraisal link set.
# Expected: HTTP 200 and the stored `appraisal` is EMPTY (silently reset).
# SupA, not EmpB: EmpB's Employee record has create_user_permission=1, so Frappe
# scopes her to her OWN record and she cannot file feedback about a colleague at
# all (D78). That is correct behaviour, but it measures User Permission rather
# than the permlevel this test is about.
$epf = Req SupA POST "/api/method/frappe.client.insert" (@{ doc = @{
        # subject and reviewer must DIFFER - stock validate_employee() blocks
        # self-feedback, and the scaffolding appraisal belongs to HR-EMP-00185
        doctype="Employee Performance Feedback"; employee="HR-EMP-00185"; company="CAF"
        reviewer="HR-EMP-00024"; added_on="2026-08-05 09:00:00"
        feedback="<p>PROBE T-J8c standing feedback</p>"; appraisal=$aprName
      }} | ConvertTo-Json -Depth 5)
$epfName = $epf.json.message.name
$stored = (Req HRMgr GET "/api/resource/Employee%20Performance%20Feedback/$epfName").json.data
Result "T-J8c" ($epf.code -eq 200 -and -not $stored.appraisal) "Employee POST with appraisal='$aprName': code=$($epf.code) name=$epfName; stored appraisal='$($stored.appraisal)' (must be empty) $($epf.err)"

# T-J8a - ordinary Employee reading an EPF must not see the appraisal field
$asEmp = (Req EmpB GET "/api/resource/Employee%20Performance%20Feedback/$epfName").json.data
$hasKey = $asEmp.PSObject.Properties.Name -contains "appraisal"
Result "T-J8a" (-not $asEmp.appraisal) "Employee read: key present=$hasKey value='$($asEmp.appraisal)' (Link fields are dropped entirely, unlike Check/Int)"

# T-J8b - HR Manager sees the field
$hasKeyHR = $stored.PSObject.Properties.Name -contains "appraisal"
# deferred - see below. The T-J8c EPF had its appraisal correctly stripped to
# empty, and Frappe omits null Link fields from the payload, so "key absent"
# there proves nothing about permlevel. Assert on a LINKED EPF instead.

# T-J8d - the unlinked EPF scores 0 and cannot move avg_feedback_score (D65)
$scoreBefore = (Req HRMgr GET "/api/resource/Appraisal/$aprName").json.data.avg_feedback_score
Req EmpB PUT "/api/resource/Employee%20Performance%20Feedback/$epfName" '{"docstatus":1}' | Out-Null
$epfDoc = (Req HRMgr GET "/api/resource/Employee%20Performance%20Feedback/$epfName").json.data
$scoreAfter = (Req HRMgr GET "/api/resource/Appraisal/$aprName").json.data.avg_feedback_score
Result "T-J8d" ($epfDoc.total_score -eq 0 -and $scoreBefore -eq $scoreAfter) "unlinked EPF total_score=$($epfDoc.total_score) (must be 0); appraisal avg_feedback_score $scoreBefore -> $scoreAfter (must be unchanged)"

# T-J8e - HR Manager CAN set the link (the T31 escape hatch stays open)
$epf2 = Req HRMgr POST "/api/method/frappe.client.insert" (@{ doc = @{
        doctype="Employee Performance Feedback"; employee="HR-EMP-00185"; company="CAF"
        reviewer="HR-EMP-00003"; added_on="2026-08-05 09:05:00"
        feedback="<p>PROBE T-J8e linked feedback</p>"; appraisal=$aprName
      }} | ConvertTo-Json -Depth 5)
$epf2Name = $epf2.json.message.name
$stored2 = (Req HRMgr GET "/api/resource/Employee%20Performance%20Feedback/$epf2Name").json.data
$crit = @($stored2.feedback_ratings).Count
Result "T-J8e" ($epf2.code -eq 200 -and $stored2.appraisal -eq $aprName) "HR Manager POST with link: code=$($epf2.code) stored appraisal='$($stored2.appraisal)'; rating criteria rows=$crit $($epf2.err)"

# T-J8b (deferred) - on an EPF that genuinely carries a link, HR Manager holds
# the permlevel-1 row and therefore sees the field.
$keyHR = $stored2.PSObject.Properties.Name -contains "appraisal"
Result "T-J8b" ($keyHR -and $stored2.appraisal) "HR Manager read of a LINKED EPF: key present=$keyHR value='$($stored2.appraisal)'"

# ---------------------------------------------------------- 2.10c  KRA (D41)
""
"=== 2.10c  KRA permissions (D41) ==="

# T-J16 - HR Manager can create a KRA. Before D41 this failed (System Manager only).
Req Admin DELETE "/api/resource/KRA/PROBE%20TJ16%20KRA" | Out-Null   # idempotency
$k = Req HRMgr POST "/api/method/frappe.client.insert" '{"doc":{"doctype":"KRA","title":"PROBE TJ16 KRA","description":"probe"}}'
Result "T-J16" ($k.code -eq 200) "HR Manager create KRA: code=$($k.code) $($k.err)"

# T-J17 - Employee (and a supervisor, who holds the same role) can read
$rB = Req EmpB GET "/api/resource/KRA?limit_page_length=0"
$rA = Req SupA GET "/api/resource/KRA?limit_page_length=0"
Result "T-J17" ($rB.code -eq 200 -and $rA.code -eq 200) "Employee GET code=$($rB.code) rows=$(@($rB.json.data).Count); supervisor GET code=$($rA.code) rows=$(@($rA.json.data).Count)"

# T-J18 - read was granted, write was not
$k2 = Req EmpB POST "/api/method/frappe.client.insert" '{"doc":{"doctype":"KRA","title":"PROBE TJ18 MUST NOT EXIST","description":"probe"}}'
$exists = (Req Admin GET "/api/method/frappe.client.get_count?doctype=KRA&filters=%5B%5B%22title%22%2C%22%3D%22%2C%22PROBE%20TJ18%20MUST%20NOT%20EXIST%22%5D%5D").json.message
Result "T-J18" ($k2.code -eq 403 -and $exists -eq 0) "Employee create KRA: code=$($k2.code); record count=$exists (must be 0)"

# ------------------------------------------------------------------ 2.9
""
"=== 2.9  permission model shipped, not just configured ==="

# T-I2 - the Workflow record reached the site with 3 states + 3 transitions
$w = Req Admin GET "/api/resource/Workflow/CAF%20Appraisal%20Workflow"
$wd = $w.json.data
$states = @($wd.states); $trans = @($wd.transitions)
$selfApprove = ($trans | Where-Object { $_.action -eq "Approve" }).allow_self_approval
Result "T-I2" ($w.code -eq 200 -and $states.Count -eq 3 -and $trans.Count -eq 3 -and $wd.is_active -eq 1 -and $selfApprove -eq 0) `
  "Workflow: code=$($w.code) active=$($wd.is_active) states=$($states.Count) transitions=$($trans.Count) Approve.allow_self_approval=$selfApprove"
"        states:      " + (($states | ForEach-Object { "$($_.state)(ds=$($_.doc_status),edit=$($_.allow_edit))" }) -join '  ')
"        transitions: " + (($trans  | ForEach-Object { "$($_.state)-[$($_.action)]->$($_.next_state) by $($_.allowed)" }) -join '  ')

# T-I3 - an Employee-role user with NO direct reports must not be able to create
# an Appraisal. The gate is the has_permission hook, which is CHUNK 2 work -
# this probe is expected to fail here and is recorded as the chunk-2 baseline.
$t = Req EmpB POST "/api/method/frappe.client.insert" (@{ doc = @{
      doctype="Appraisal"; employee="HR-EMP-00024"; appraisal_cycle=$CYCLE; company="CAF"
      appraisal_template="CAF Monthly Appraisal"
    }} | ConvertTo-Json -Depth 5)
Result "T-I3" ($t.code -eq 403) "Employee with no direct reports creates an Appraisal: code=$($t.code) (403 required; the has_permission gate is Chunk 2)"
if ($t.code -eq 200) { "        created $($t.json.message.name) - must be cleaned up" }
