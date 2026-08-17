# S3 — verdict shapes: W1 / W5 / W6 / W7 / W9 at the Finger Log + Attendance level.
# NEW file; nothing existing touched. No importer calls.

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP13 = "HR-EMP-00013"   # 8:30am Schedule (no OT) — W1/W5/W9
$EMP16 = "HR-EMP-00016"   # 8am Schedule (OT eligible) — W6/W7
$CYCLE = "2026-06"
$LTYPE = "Leave Without Pay"
$MYDATES = @("2026-06-15", "2026-06-16", "2026-06-18", "2026-05-24", "2026-05-27")

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    # D-12: cancel leaves FIRST (their Attendance becomes docstatus=2 via stock
    # db_set), then attendance is deletable, then the cancelled leaves.
    Cancel-MyDocs "Leave Application" "from_date" $MYDATES
    Remove-MyDocs "Attendance" "attendance_date" $MYDATES
    Remove-MyDocs "Finger Log" "work_date" $MYDATES
    Remove-MyDocs "OT Approval" "work_date" $MYDATES
    Remove-MyDocs "Leave Application" "from_date" $MYDATES
    Remove-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
}

function New-Log([string]$Employee, [string]$EmployeeName, [string]$Date, [string]$In, [string]$Out, [double]$Overtime) {
    $zero = ($In -eq "00:00:00")
    $doc = @{
        doctype = "Finger Log"; employee = $Employee; employee_name = $EmployeeName; work_date = $Date
        time_in = $In; break = $(if ($zero) { "00:00:00" } else { "12:30:00" }); resume = $(if ($zero) { "00:00:00" } else { "13:30:00" }); out = $Out; overtime = $Overtime
    }
    return Insert-Doc "HRM" $doc
}

function New-OT([string]$Employee, [string]$EmployeeName, [string]$Date, [string]$Type, [double]$Hours) {
    $emp = Get-Doc "ADMIN" "Employee" $Employee
    $r = Insert-Doc "HRM" @{
        doctype = "OT Approval"; work_date = $Date; type = $Type
        ot_department = $emp.department; reason = "WF-GAP S3/S4 fixture"
        emp_list = @(@{
            work_date = $Date; emp_id = $Employee; emp_name = $EmployeeName
            start_work = "08:00:00"; ot_end = "18:00:00"; ot_duration = $Hours
        })
    }
    if ($r.code -ne 200) { return $null }
    $nm = if ($r.data.message -is [string]) { $r.data.message } else { $r.data.message.name }
    $s = Submit-Doc "HRM" "OT Approval" $nm
    if ($s.code -ne 200) { Write-Host "   approval submit FAILED: $($s.raw)"; return $null }
    return $nm
}

function Log-Doc([string]$Employee, [string]$Date) {
    $rows = Get-List "ADMIN" "Finger Log" @(
        @("employee", "=", $Employee), @("work_date", "=", $Date), @("docstatus", "<", 2)
    ) @("name")
    if ($rows.Count -eq 1) { return Get-Doc "ADMIN" "Finger Log" $rows[0].name }
    return $null
}

function Approve-Leave([string]$Name) {
    WF-Action "SUP" "Leave Application" $Name "Submit for Approval" | Out-Null
    WF-Action "SUP" "Leave Application" $Name "Approve" | Out-Null
    WF-Action "HRM" "Leave Application" $Name "Approve" | Out-Null
    WF-Action "HRM" "Leave Application" $Name "Approve" | Out-Null
}

# ------------------------------------------------------------------
Write-Host "=== S3 — verdict shapes ==="
Clean-All
$e13 = Get-Doc "ADMIN" "Employee" $EMP13
$e16 = Get-Doc "ADMIN" "Employee" $EMP16

# W1 — normal workday
$l = New-Log $EMP13 $e13.employee_name "2026-06-15" "08:30:00" "17:30:00" 0
$lname = $l.data.message.name
$s = Submit-Doc "HRM" "Finger Log" $lname
$d = Log-Doc $EMP13 "2026-06-15"
$att = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", "2026-06-15"), @("docstatus", "<", 2) ) @("name", "status", "leave_type")
Check "W1-PRESENT" ($s.code -eq 200 -and $d.docstatus -eq 1 -and $att.Count -eq 1 -and $att[0].status -eq "Present" -and $d.day_type -eq "Workday") "Present, day_type=$($d.day_type), final_ot=$($d.final_ot)"

# W5 — punchless rostered day -> Absent, leave_type EMPTY
$l5 = New-Log $EMP13 $e13.employee_name "2026-06-16" "00:00:00" "00:00:00" 0
$l5n = $l5.data.message.name
$s5 = Submit-Doc "HRM" "Finger Log" $l5n
$d5 = Log-Doc $EMP13 "2026-06-16"
$att5 = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", "2026-06-16"), @("docstatus", "<", 2) ) @("name", "status", "leave_type")
Check "W5-ABSENT" ($s5.code -eq 200 -and $att5.Count -eq 1 -and $att5[0].status -eq "Absent" -and [string]::IsNullOrEmpty($att5[0].leave_type)) "Absent, leave_type EMPTY"

# W6 — Restday (Sunday) + punches + special approval -> every hour OT
$ot6 = New-OT $EMP16 $e16.employee_name "2026-05-24" "special_approve" 8
$l6 = New-Log $EMP16 $e16.employee_name "2026-05-24" "09:00:00" "13:00:00" 4
$l6n = $l6.data.message.name
$s6 = Submit-Doc "HRM" "Finger Log" $l6n
$d6 = Log-Doc $EMP16 "2026-05-24"
Check "W6-RESTDAY" ($null -ne $ot6 -and $s6.code -eq 200 -and $d6.day_type -eq "Restday" -and $d6.ot_in_hour -gt 0 -and $d6.final_ot -gt 0) "day_type=$($d6.day_type), ot_in_hour=$($d6.ot_in_hour), final_ot=$($d6.final_ot) — every hour OT"

# W7 — Holiday + punches + approval -> Holiday OT, NOT collapsed to Restday
$ot7 = New-OT $EMP16 $e16.employee_name "2026-05-27" "special_approve" 8
$l7 = New-Log $EMP16 $e16.employee_name "2026-05-27" "09:00:00" "13:00:00" 4
$l7n = $l7.data.message.name
$s7 = Submit-Doc "HRM" "Finger Log" $l7n
$d7 = Log-Doc $EMP16 "2026-05-27"
Check "W7-HOLIDAY" ($null -ne $ot7 -and $s7.code -eq 200 -and $d7.day_type -eq "Holiday" -and $d7.ot_in_hour -gt 0) "day_type=$($d7.day_type), ot_in_hour=$($d7.ot_in_hour) — distinct from W6's Restday"

# W9 — half-day leave -> Attendance Half Day, counted 0.5 in the appraisal cell
$lv = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = "2026-06-18"; to_date = "2026-06-18"; leave_type = $LTYPE; leave_approver = "too@caffood.com"; half_day = 1; description = "WF-GAP S3 W9" }
$lvName = $lv.data.message.name
Approve-Leave $lvName
$att9 = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", "2026-06-18"), @("docstatus", "<", 2) ) @("name", "status", "leave_type")
Check "W9-HALFDAY" ($att9.Count -eq 1 -and $att9[0].status -eq "Half Day") "Attendance Half Day"

$app = Insert-Doc "HRM" @{ doctype = "Appraisal"; employee = $EMP13; appraisal_cycle = $CYCLE; appraisal_template = "CAF Monthly Appraisal" }
$appName = $app.data.message.name
$rf = Invoke-Call "HRM" "POST" "/api/method/run_doc_method" @{ dt = "Appraisal"; dn = $appName; method = "refresh_auto_fill_action" }
$ad = Get-Doc "ADMIN" "Appraisal" $appName
$cell = ($ad.appraisal_kra | Where-Object { $_.kra -eq "Attendance" }).caf_date_cell
Check "W9-COUNT" ($rf.code -eq 200 -and $cell -match "18½") "appraisal cell='$cell' — half day counted as 0.5 (Absent day 16 also expected)"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$leftLogs = Count-MyDocs "Finger Log" "work_date" $MYDATES
$leftAtt = Count-MyDocs "Attendance" "attendance_date" $MYDATES
$leftOt = Count-MyDocs "OT Approval" "work_date" $MYDATES
$leftLv = Count-MyDocs "Leave Application" "from_date" $MYDATES
Check "CLEAN" ($leftLogs -eq 0 -and $leftAtt -eq 0 -and $leftOt -eq 0 -and $leftLv -eq 0) "session-owned leftovers: logs=$leftLogs att=$leftAtt ot=$leftOt leave=$leftLv"

Summary
