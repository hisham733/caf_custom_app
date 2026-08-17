# S7 — each dashboard reflects the doctype state changes it exists for.
# Server-side only (query_report.run + whitelisted page methods). NEW file.

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP13 = "HR-EMP-00013"
$LTYPE = "Leave Without Pay"
$D1 = "2026-06-16"   # My Attendance reflection (leave -> On Leave row)
$D2 = "2026-06-18"   # Who Is Off stage walk
$D3 = "2026-06-19"   # late leave over a submitted appraisal -> 7.2 panel
$CYCLE = "2026-06"
$MYDATES = @($D1, $D2, $D3)

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    Remove-MyDocs "Attendance" "attendance_date" $MYDATES
    Remove-MyDocs "Finger Log" "work_date" $MYDATES
    Remove-MyDocs "Leave Application" "from_date" $MYDATES
    Remove-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
}

function Approve-Leave([string]$Name) {
    WF-Action "SUP" "Leave Application" $Name "Submit for Approval" | Out-Null
    WF-Action "SUP" "Leave Application" $Name "Approve" | Out-Null
    WF-Action "HRM" "Leave Application" $Name "Approve" | Out-Null
    WF-Action "HRM" "Leave Application" $Name "Approve" | Out-Null
}

function Run-Report([string]$Role, [string]$Report, $Filters) {
    $r = Invoke-Call $Role "POST" "/api/method/frappe.desk.query_report.run" @{
        report_name = $Report; filters = $Filters
    }
    if ($r.code -eq 200) {
        $m = $r.data.message
        if ($null -ne $m -and $m.PSObject.Properties.Name -contains "result") { return @($m.result) }
        return @($m)
    }
    Write-Host "   report $Report as $Role -> $($r.code): $($r.raw)"
    return @()
}

# ------------------------------------------------------------------
Write-Host "=== S7 - dashboard state reflection ==="
Clean-All

# ---- D1: My Attendance reflects a leave flip (needs the imported-log row) ----
$log1 = Insert-Doc "HRM" @{
    doctype = "Finger Log"; employee = $EMP13; employee_name = "Mohd Hairy Bin Abd Latif"; work_date = $D1
    time_in = "00:00:00"; break = "00:00:00"; resume = "00:00:00"; out = "00:00:00"; overtime = 0
}
$lv1 = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D1; to_date = $D1; leave_type = $LTYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S7 D1" }
$LV1N = $lv1.data.message.name
Approve-Leave $LV1N
$rep1e = Run-Report "EMP" "My Attendance" @{ from_date = $D1; to_date = $D1 }
Check "D1-EMP-GATE" ($rep1e.Count -eq 0) "TRUTH: Employee cannot RUN the report via the desk path - Report roles are HR-Manager-only (D-2) and Employee holds report=0 on Finger Log (D-1) (REPORT)"
$ev1 = Invoke-Call "EMP" "POST" "/api/method/caf.caf.finger_log_scope.get_employee_events" @{ doctype = "Finger Log"; start = $D1; end = $D1 }
$ev1row = @($ev1.data.message) | Where-Object { $_.name -eq $log1.data.message.name } | Select-Object -First 1
Check "D1-EMP-CAL" ($ev1.code -eq 200 -and $null -ne $ev1row -and $ev1row.title -match "On Leave" -and $ev1row.title -match "DRAFT") "calendar (EMP): own row for ${D1} shows DRAFT + On Leave: '$($ev1row.title)' (D-5/D-7 join)"
Check "D1-EMP-CAL-SCOPE" (@($ev1.data.message).Count -eq 1) "calendar (EMP) returns ONLY own rows: $(@($ev1.data.message).Count) event(s) for ${D1} (AC-1)"
$rep1h = Run-Report "HRM" "My Attendance" @{ from_date = $D1; to_date = $D1; employee = $EMP13 }
$row1h = $rep1h | Where-Object { $_.work_date -eq $D1 } | Select-Object -First 1
Check "D1-MYATT-STATUS" ($null -ne $row1h -and $row1h.status -eq "On Leave") "My Attendance as HRM shows On Leave for ${D1}: status=$($row1h.status)"
Check "D1-LEAVETYPE-HR" ($null -ne $row1h -and $row1h.leave_type -eq $LTYPE) "HR Manager sees leave_type=$($row1h.leave_type)"

# ---- D2: Who Is Off stage walk with the REAL 6b workflow ----
# NB: board rows carry employee_name (no employee key); from/to filter = spans covering the date
$lv2 = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D2; to_date = $D2; leave_type = $LTYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S7 D2" }
$LV2N = $lv2.data.message.name
function Board-Row {
    $b = Run-Report "HRM" "Who Is Off" @{ from_date = $D2; to_date = $D2 }
    return $b | Where-Object { $_.employee_name -eq "Mohd Hairy Bin Abd Latif" } | Select-Object -First 1
}
$row2 = Board-Row
Check "D2-DRAFT-INCLUDED" ($null -ne $row2) "pending application appears on the board"
Check "D2-STAGE-DRAFT" ($null -ne $row2 -and $row2.stage -eq "Draft") "Stage shows the real workflow state: $($row2.stage)"
WF-Action "SUP" "Leave Application" $LV2N "Submit for Approval" | Out-Null
$row2b = Board-Row
Check "D2-STAGE-PENDING" ($null -ne $row2b -and $row2b.stage -eq "Pending Supervisor") "Stage follows the walk: $($row2b.stage)"
WF-Action "SUP" "Leave Application" $LV2N "Approve" | Out-Null
WF-Action "HRM" "Leave Application" $LV2N "Approve" | Out-Null
WF-Action "HRM" "Leave Application" $LV2N "Approve" | Out-Null
$row2c = Board-Row
Check "D2-STAGE-APPROVED" ($null -ne $row2c -and $row2c.stage -eq "Approved") "Stage = Approved after the chain: $($row2c.stage)"
WF-Action "HRM" "Leave Application" $LV2N "Cancel" | Out-Null
$row2d = Board-Row
Check "D2-CANCEL-GONE" ($null -eq $row2d) "cancelled leave leaves the board (transition, not just static exclusion)"

# ---- D3: 7.2 panel shows a completed appraisal that moved ----
$c = Insert-Doc "SUP" @{ doctype = "Appraisal"; employee = $EMP13; appraisal_cycle = $CYCLE; appraisal_template = "CAF Monthly Appraisal" }
$APP_C = $c.data.message.name
WF-Action "SUP" "Appraisal" $APP_C "Submit for Review" | Out-Null
WF-Action "HRM" "Appraisal" $APP_C "Approve" | Out-Null
$lv3 = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D3; to_date = $D3; leave_type = $LTYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S7 D3" }
$LV3N = $lv3.data.message.name
Approve-Leave $LV3N
$panel = Invoke-Call "HRM" "POST" "/api/method/caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.get_refreshed_after_submit" @{ limit = 25 }
$names = @($panel.data.message.rows | ForEach-Object { $_.name })
Check "D3-CHANGED-PANEL" ($panel.code -eq 200 -and $APP_C -in $names) "7.2 'changed after submission' lists the refreshed appraisal (got $($names -join ','))"

# ---- other panels answer ----
$flags = Invoke-Call "HRM" "POST" "/api/method/caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.get_hr_review_flags" @{ limit = 50 }
Check "D4-HRFLAGS" ($flags.code -eq 200) "get_hr_review_flags answers: $($flags.code)"
$mp = Invoke-Call "HRM" "POST" "/api/method/caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.get_monthly_progress" @{ year = 2026 }
Check "D5-MONTHLY" ($mp.code -eq 200 -and @($mp.data.message).Count -gt 0) "get_monthly_progress answers with rows ($(@($mp.data.message).Count))"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$left = Count-MyDocs "Leave Application" "from_date" $MYDATES
$leftA = Count-MyDocs "Attendance" "attendance_date" $MYDATES
$leftC = Count-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
Check "CLEAN" ($left -eq 0 -and $leftA -eq 0 -and $leftC -eq 0) "session-owned leftovers: leave=$left att=$leftA app=$leftC"

Summary
