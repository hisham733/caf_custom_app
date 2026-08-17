# S9 — Attendance direct amend/cancel as a role (truth-test). NEW file.

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP13 = "HR-EMP-00013"
$LTYPE = "Leave Without Pay"
$D1 = "2026-06-16"
$CYCLE = "2026-06"

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    Remove-MyDocs "Attendance" "attendance_date" @($D1)
    Remove-MyDocs "Finger Log" "work_date" @($D1)
    Remove-MyDocs "Leave Application" "from_date" @($D1)
    Remove-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
}

# ------------------------------------------------------------------
Write-Host "=== S9 - Attendance amend/cancel truth ==="
Clean-All

# leave approved -> Attendance On Leave for D1
$lv = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D1; to_date = $D1; leave_type = $LTYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S9" }
$LVN = $lv.data.message.name
WF-Action "SUP" "Leave Application" $LVN "Submit for Approval" | Out-Null
WF-Action "SUP" "Leave Application" $LVN "Approve" | Out-Null
WF-Action "HRM" "Leave Application" $LVN "Approve" | Out-Null
WF-Action "HRM" "Leave Application" $LVN "Approve" | Out-Null
$att = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", $D1), @("docstatus", "<", 2) ) @("name", "status", "leave_type")
$ATTN = $att[0].name
Check "SETUP-ATT" ($att.Count -eq 1 -and $att[0].status -eq "On Leave") "attendance On Leave created: $ATTN"

# draft appraisal to observe the count
$app = Insert-Doc "HRM" @{ doctype = "Appraisal"; employee = $EMP13; appraisal_cycle = $CYCLE; appraisal_template = "CAF Monthly Appraisal" }
$APPN = $app.data.message.name
$r1 = Invoke-Call "HRM" "POST" "/api/method/run_doc_method" @{ dt = "Appraisal"; dn = $APPN; method = "refresh_auto_fill_action" }
$ad1 = Get-Doc "ADMIN" "Appraisal" $APPN
$cell1 = ($ad1.appraisal_kra | Where-Object { $_.kra -eq "Attendance" }).caf_date_cell
Check "S9-BEFORE" ($cell1 -match "\b16\b") "appraisal counts the leave day: cell='$cell1'"

# A1 - TRUTH: HR Manager edits the SUBMITTED attendance's status
$a1 = Invoke-Call "HRM" "PUT" "/api/resource/Attendance/$ATTN" @{ status = "Present" }
Check "A1-EDIT-TRUTH" ($a1.code -ne 200 -and $a1.raw -match "Not allowed to change") "TRUTH: status edit after submit refused ($($a1.code)) - stock UpdateAfterSubmitError guard (good)"
$att2 = Get-Doc "ADMIN" "Attendance" $ATTN
Check "A1-UNCHANGED" ($att2.status -eq "On Leave") "refused edit changed nothing: status=$($att2.status)"
$r2 = Invoke-Call "HRM" "POST" "/api/method/run_doc_method" @{ dt = "Appraisal"; dn = $APPN; method = "refresh_auto_fill_action" }
$ad2 = Get-Doc "ADMIN" "Appraisal" $APPN
$cell2 = ($ad2.appraisal_kra | Where-Object { $_.kra -eq "Attendance" }).caf_date_cell
Check "A1-COUNT" ($cell2 -match "\b16\b") "the day stays counted: cell='$cell2'"

# A2 (2026-08-15, D-12) - the guard: direct cancel of a leave-owned row is refused
$a2 = Cancel-Doc "HRM" "Attendance" $ATTN
Check "A2-CANCEL-GUARD" ($a2.code -ne 200 -and $a2.raw -match $LVN) "direct cancel of a leave-owned row refused ($($a2.code)), names the leave: $($a2.raw.Substring(0,[Math]::Min(120,[string]$a2.raw.Length)))"
$att3 = Get-Doc "ADMIN" "Attendance" $ATTN
Check "A2-UNCHANGED" ($null -ne $att3 -and $att3.docstatus -eq 1 -and $att3.status -eq "On Leave") "refused cancel changed nothing: ds=$($att3.docstatus) status=$($att3.status)"
$r3 = Invoke-Call "HRM" "POST" "/api/method/run_doc_method" @{ dt = "Appraisal"; dn = $APPN; method = "refresh_auto_fill_action" }
$ad3 = Get-Doc "ADMIN" "Appraisal" $APPN
$cell3 = ($ad3.appraisal_kra | Where-Object { $_.kra -eq "Attendance" }).caf_date_cell
Check "A2-COUNT-KEPT" ($cell3 -match "\b16\b") "the day STAYS counted while the leave stands: cell='$cell3'"

# A2b - the sanctioned route: cancel the LEAVE (restores the day from its own record)
$cL = WF-Action "HRM" "Leave Application" $LVN "Cancel"
Check "A2B-LEAVE-CANCEL" ($cL.code -eq 200) "cancel the leave instead: $($cL.code)"
$r4 = Invoke-Call "HRM" "POST" "/api/method/run_doc_method" @{ dt = "Appraisal"; dn = $APPN; method = "refresh_auto_fill_action" }
$ad4 = Get-Doc "ADMIN" "Appraisal" $APPN
$cell4 = ($ad4.appraisal_kra | Where-Object { $_.kra -eq "Attendance" }).caf_date_cell
Check "A2B-COUNT-DROP" ($cell4 -notmatch "\b16\b") "sanctioned route drops the day: cell='$cell4'"

# A3 - Employee cannot touch it
$a3 = Invoke-Call "EMP" "PUT" "/api/resource/Attendance/$ATTN" @{ status = "Absent" }
Check "A3-EMP-REFUSED" ($a3.code -ne 200) "Employee cannot edit attendance ($($a3.code))"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$left = Count-MyDocs "Leave Application" "from_date" @($D1)
$leftA = Count-MyDocs "Attendance" "attendance_date" @($D1)
$leftC = Count-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
Check "CLEAN" ($left -eq 0 -and $leftA -eq 0 -and $leftC -eq 0) "session-owned leftovers: leave=$left att=$leftA app=$leftC"

Summary
