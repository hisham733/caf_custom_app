# CAF Appraisal chunk 2 - test plan 2.1 to 2.4
# Supervisor flow, HR flow, rejection loop, subtree visibility.
# Every request uses its own per-role token. Administrator is never used as a
# permission subject - it bypasses every check.

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
$T = $CAF_TOKENS   # includes Admin, used only for cleanup
$EMP_A = "HR-EMP-00024"; $EMP_B = "HR-EMP-00185"; $EMP_C = "HR-EMP-00016"; $EMP_D = "HR-EMP-00022"
$CYCLE = "2026-06"

function CafHeader($role) { return @{ Authorization = "token $($T[$role])" } }
function Req($role, $method, $path, $body) {
  $p = @{ Uri = "$U$path"; Method = $method; Headers = (CafHeader $role); UseBasicParsing = $true; TimeoutSec = 60 }
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

# --- self-cleanup so the suite is RE-RUNNABLE and ORDER-INDEPENDENT ---------
# Without this the second run of run_all.ps1 collapses: T-A1 hits a duplicate
# from the previous run, returns no document name, and every later assertion
# then builds a URL from a null (405/404). None of that is a product fault.
"=== cleanup from any previous run ==="
Reset-CafTestData -Request { param($r,$m,$p,$b) Req $r $m $p $b }
""

"=== 2.1  Supervisor workflow (happy path) ==="

# T-A1
$a = Ins SupA @{ doctype="Appraisal"; employee=$EMP_B; appraisal_cycle=$CYCLE; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
$APR = $a.json.message.name
$doc = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
Res "T-A1" ($a.code -eq 200 -and $doc.workflow_state -eq "Draft" -and $doc.docstatus -eq 0 -and $doc.reported_by -eq $EMP_A) `
  "code=$($a.code) name=$APR workflow_state=$($doc.workflow_state) docstatus=$($doc.docstatus) reported_by=$($doc.reported_by) (expect $EMP_A) $($a.err)"

# T-A2b - grid built from the template by stock logic, server-side
$rows = @($doc.appraisal_kra)
$weighted = @($rows | Where-Object { $_.per_weightage -gt 0 })
Res "T-A2b" ($rows.Count -eq 6 -and $weighted.Count -eq 6) "appraisal_kra rows=$($rows.Count) with weightage=$($weighted.Count) : $((($rows | ForEach-Object { $_.kra }) -join ', '))"

# T-A2 - the auto-filled cells, asserted as STRINGS in D68 format
$byKra = @{}; foreach ($r in $rows) { $byKra[$r.kra] = $r }
$att = $byKra["Attendance"].caf_date_cell
$pun = $byKra["Punctuality"].caf_date_cell
$ot  = $byKra["OT Hours"].caf_date_cell
$rem = $byKra["Attendance"].caf_remarks
# expected from raw SQL over the seeded set: 0.5UPL on the 16th, UPL on the 27th;
# never late in June; approved OT 9.00 (clocked 7.00 - proves final_ot is used)
Res "T-A2" ($att -eq "16½, 27" -and $pun -eq "" -and $ot -eq "9 h") `
  "Attendance='$att' (expect '16½, 27')  Punctuality='$pun' (expect '')  OT='$ot' (expect '9 h')  Remarks='$rem'"
"        auto_fill_computed_on = $($doc.auto_fill_computed_on)"

# T-A3 - supervisor fills the text columns
$upd = @{ appraisal_kra = @() }
foreach ($r in $rows) {
  $upd.appraisal_kra += @{ name=$r.name; kra=$r.kra; per_weightage=$r.per_weightage
                           caf_date_cell=$r.caf_date_cell
                           caf_description="desc $($r.kra)"; caf_root_cause="cause"
                           caf_corrective_action="action"; caf_remarks=$r.caf_remarks }
}
$w = Req SupA PUT "/api/resource/Appraisal/$APR" ($upd | ConvertTo-Json -Depth 6)
$after = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
$filled = @(@($after.appraisal_kra) | Where-Object { $_.caf_description }).Count
Res "T-A3" ($w.code -eq 200 -and $filled -eq 6) "code=$($w.code) rows with text=$filled/6 $($w.err)"

# T-A3b - re-applying the template must be REFUSED and the typed text survive
$reapply = Req SupA POST "/api/method/run_doc_method" (@{ dt="Appraisal"; dn=$APR; method="set_kras_and_rating_criteria" } | ConvertTo-Json)
$post = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
$stillFilled = @(@($post.appraisal_kra) | Where-Object { $_.caf_description }).Count
Res "T-A3b" ($reapply.code -ne 200 -and $stillFilled -eq 6) `
  "re-apply code=$($reapply.code) (must not be 200); rows with text after=$stillFilled/6 : $($reapply.err)"

# T-A6 / T-A7 - the supervisor rule, both directions
$d = Ins SupA @{ doctype="Appraisal"; employee=$EMP_D; appraisal_cycle=$CYCLE; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
Res "T-A6" ($d.code -eq 403) "A creates for D (sibling branch): code=$($d.code) $($d.err)"
$c = Ins SupA @{ doctype="Appraisal"; employee=$EMP_C; appraisal_cycle=$CYCLE; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
Res "T-A7" ($c.code -eq 403) "A creates for C (his own SUPERIOR): code=$($c.code) $($c.err)"

# T-A4 - Submit for Review. June has ended, so BR6 lets this through.
$sub = WfAction SupA $APR "Submit for Review"
$doc = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
Res "T-A4" ($sub.code -eq 200 -and $doc.workflow_state -eq "Pending HR Review" -and $doc.docstatus -eq 0) `
  "code=$($sub.code) state=$($doc.workflow_state) docstatus=$($doc.docstatus) (must stay 0 - D54) $($sub.err)"

# T-A5 - the workflow lock, not a docstatus lock
$edit = Req SupA PUT "/api/resource/Appraisal/$APR" '{"remarks":"supervisor edit after submit"}'
$check = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
Res "T-A5" ($edit.code -ne 200 -or $check.remarks -ne "supervisor edit after submit") `
  "supervisor edit while Pending HR Review: code=$($edit.code) stored remarks='$($check.remarks)' $($edit.err)"

# T-A8 - supervisor approves his own document
$self = WfAction SupA $APR "Approve"
Res "T-A8" ($self.code -ne 200) "A clicks Approve on his own: code=$($self.code) $($self.err)"

""
"=== 2.2  HR Manager workflow ==="
$list = Req HRMgr GET "/api/resource/Appraisal?limit_page_length=0"
Res "T-B1" ($list.code -eq 200) "HR Manager lists appraisals: code=$($list.code) rows=$(@($list.json.data).Count)"

$cm = Req HRMgr POST "/api/method/frappe.desk.form.utils.add_comment" `
  (@{ reference_doctype="Appraisal"; reference_name=$APR; content="HR review note"; comment_email="hr.manager.test@caffood.com"; comment_by="HR Manager Test" } | ConvertTo-Json)
Res "T-B2" ($cm.code -eq 200) "HR adds a comment: code=$($cm.code) $($cm.err)"

# T-B4 - HR Manager may appraise anyone (BR3 override). EMP-D reports to C.
$hrApr = Ins HRMgr @{ doctype="Appraisal"; employee=$EMP_D; appraisal_cycle=$CYCLE; company="CAF"; appraisal_template="CAF Monthly Appraisal" }
Res "T-B4" ($hrApr.code -eq 200) "HR creates for D (no reports_to relation): code=$($hrApr.code) name=$($hrApr.json.message.name) $($hrApr.err)"

""
"=== 2.3  Rejection / re-work loop (same document throughout) ==="
$rej = WfAction HRMgr $APR "Reject"
$doc = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
Res "T-C4" ($rej.code -eq 200 -and $doc.workflow_state -eq "Draft" -and $doc.docstatus -eq 0 -and $doc.name -eq $APR) `
  "Reject: code=$($rej.code) state=$($doc.workflow_state) docstatus=$($doc.docstatus) name=$($doc.name) $($rej.err)"

$edit2 = Req SupA PUT "/api/resource/Appraisal/$APR" '{"remarks":"fixed after rejection"}'
$doc = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
Res "T-C5" ($edit2.code -eq 200 -and $doc.remarks -eq "fixed after rejection") "supervisor edits the returned draft: code=$($edit2.code) remarks='$($doc.remarks)' $($edit2.err)"

$sub2 = WfAction SupA $APR "Submit for Review"
$app  = WfAction HRMgr $APR "Approve"
$doc  = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
Res "T-C6" ($app.code -eq 200 -and $doc.workflow_state -eq "Completed" -and $doc.docstatus -eq 1) `
  "resubmit+Approve: code=$($app.code) state=$($doc.workflow_state) docstatus=$($doc.docstatus) $($app.err)"

$lock = Req HRMgr PUT "/api/resource/Appraisal/$APR" '{"remarks":"edit after completion"}'
$doc2 = (Req HRMgr GET "/api/resource/Appraisal/$APR").json.data
Res "T-C7" ($lock.code -ne 200 -or $doc2.remarks -ne "edit after completion") "edit a Completed appraisal: code=$($lock.code) remarks='$($doc2.remarks)'"

Res "T-C8" ($doc.name -eq $APR) "document name unchanged from creation to Completed: $APR"

$empApprove = WfAction EmpB $APR "Approve"
Res "T-C9" ($empApprove.code -ne 200) "employee with no HR role clicks Approve: code=$($empApprove.code)"

""
"=== 2.4  Subtree visibility (D18) ==="
$lA = Req SupA GET "/api/resource/Appraisal?limit_page_length=0&fields=%5B%22name%22%2C%22employee%22%5D"
$empsA = @(@($lA.json.data) | ForEach-Object { $_.employee } | Sort-Object -Unique)
Res "T-D1" ($lA.code -eq 200 -and $empsA -contains $EMP_B -and $empsA -notcontains $EMP_C -and $empsA -notcontains $EMP_D) `
  "A sees: [$($empsA -join ', ')] - must contain $EMP_B, never $EMP_C or $EMP_D"

$lC = Req SupC GET "/api/resource/Appraisal?limit_page_length=0&fields=%5B%22name%22%2C%22employee%22%5D"
$empsC = @(@($lC.json.data) | ForEach-Object { $_.employee } | Sort-Object -Unique)
Res "T-D2" ($lC.code -eq 200 -and $empsC -contains $EMP_B -and $empsC -contains $EMP_D) `
  "C sees the whole subtree: [$($empsC -join ', ')] - must include grandchild $EMP_B and $EMP_D"

$direct = Req SupA GET "/api/resource/Appraisal/$($hrApr.json.message.name)"
Res "T-D3" ($direct.code -eq 403) "A fetches D's appraisal BY NAME (bypassing the list): code=$($direct.code) - proves the check is per-document"

$lB = Req EmpB GET "/api/resource/Appraisal?limit_page_length=0&fields=%5B%22name%22%2C%22employee%22%5D"
Res "T-D6" ($lB.code -eq 200) "leaf employee lists appraisals: code=$($lB.code) rows=$(@($lB.json.data).Count) - must be a clean empty result, no SQL error"

$lHR = Req HRMgr GET "/api/resource/Appraisal?limit_page_length=0"
Res "T-D5" ($lHR.code -eq 200) "HR Manager unfiltered: rows=$(@($lHR.json.data).Count)"

""
"APPRAISAL_UNDER_TEST=$APR"
"HR_CREATED=$($hrApr.json.message.name)"
