# S5 — leave/log collision, both directions (no importer calls — the "4am import
# arriving" is simulated by a direct Finger Log insert).
#   B2: day already Present -> late leave filed  (case C4 — refused, he worked?)
#   V2: leave approved first -> log arrives       (must not be silently swallowed)

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP13 = "HR-EMP-00013"
$D1 = "2026-06-15"   # B2: present day
$D2 = "2026-06-16"   # V2: leave-first day
$LTYPE = "Leave Without Pay"
$MYDATES = @($D1, $D2)

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    Remove-MyDocs "Attendance" "attendance_date" $MYDATES
    Remove-MyDocs "Finger Log" "work_date" $MYDATES
    Remove-MyDocs "Leave Application" "from_date" $MYDATES
}

function Approve-Leave([string]$Name) {
    WF-Action "SUP" "Leave Application" $Name "Submit for Approval" | Out-Null
    WF-Action "SUP" "Leave Application" $Name "Approve" | Out-Null
    WF-Action "HRM" "Leave Application" $Name "Approve" | Out-Null
    WF-Action "HRM" "Leave Application" $Name "Approve" | Out-Null
}

# ------------------------------------------------------------------
Write-Host "=== S5 — leave/log collision, both directions ==="
Clean-All
$e13 = Get-Doc "ADMIN" "Employee" $EMP13

# B2 — the day is Present (submitted log), then a leave is filed for it
$log1 = Insert-Doc "HRM" @{
    doctype = "Finger Log"; employee = $EMP13; employee_name = $e13.employee_name; work_date = $D1
    time_in = "08:30:00"; break = "12:30:00"; resume = "13:30:00"; out = "17:30:00"; overtime = 0
}
$log1n = $log1.data.message.name
$s1 = Submit-Doc "HRM" "Finger Log" $log1n
Check "B2-PRESENT" ($s1.code -eq 200) "day $D1 is Present"

$lv = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D1; to_date = $D1; leave_type = $LTYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S5 B2" }
Check "B2-INSERT" ($lv.code -ne 200) "TRUTH: leave over a Present day refused at filing ($($lv.code)): $($lv.raw)"
$att1 = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", $D1), @("docstatus", "<", 2) ) @("name", "status", "leave_type")
Check "B2-TRUTH" ($att1.Count -eq 1 -and $att1[0].status -eq "Present" -and [string]::IsNullOrEmpty($att1[0].leave_type)) "attendance untouched: $($att1[0].status)/$($att1[0].leave_type) — he worked, not overwritten"

# V2 — leave approved FIRST, then the log arrives (the 4am import shape)
$lv2 = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D2; to_date = $D2; leave_type = $LTYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S5 V2" }
$lv2n = $lv2.data.message.name
Approve-Leave $lv2n
$att2 = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", $D2), @("docstatus", "<", 2) ) @("name", "status", "leave_type")
Check "V2-LEAVE-FIRST" ($att2.Count -eq 1 -and $att2[0].status -eq "On Leave") "leave approved first: attendance $($att2[0].status)"

$log2 = Insert-Doc "HRM" @{
    doctype = "Finger Log"; employee = $EMP13; employee_name = $e13.employee_name; work_date = $D2
    time_in = "08:30:00"; break = "12:30:00"; resume = "13:30:00"; out = "17:30:00"; overtime = 0
}
$log2n = $log2.data.message.name
$s2 = Submit-Doc "HRM" "Finger Log" $log2n
$att2b = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", $D2), @("docstatus", "<", 2) ) @("name", "status", "leave_type")
$log2d = Get-Doc "ADMIN" "Finger Log" $log2n
Check "V2-LOG-REFUSED" ($s2.code -ne 200) "log submit over approved leave refused ($($s2.code)): $($s2.raw)"
Check "V2-NOT-SWALLOWED" ($att2b.Count -eq 1 -and $att2b[0].status -eq "On Leave" -and $log2d.docstatus -eq 0) "attendance untouched ($($att2b[0].status)), log stays draft (ds=$($log2d.docstatus)) — never silently overwritten"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$left = Count-MyDocs "Leave Application" "from_date" $MYDATES
$leftA = Count-MyDocs "Attendance" "attendance_date" $MYDATES
$leftL = Count-MyDocs "Finger Log" "work_date" $MYDATES
Check "CLEAN" ($left -eq 0 -and $leftA -eq 0 -and $leftL -eq 0) "session-owned leftovers: leave=$left att=$leftA logs=$leftL"

Summary
