# S4 — OT Approval branches: special_approve over/under, normal control, and the
# approval lifecycle AFTER the log submitted (cancel / replace). NEW file.

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP16 = "HR-EMP-00016"   # 8am Schedule (OT eligible, gate 30 round 30)
$D1 = "2026-05-25"   # O1 special over
$D2 = "2026-05-26"   # O2 special under
$D3 = "2026-06-01"   # O3 normal control + O4 cancel + O5 replace
$MYDATES = @($D1, $D2, $D3)

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    Remove-MyDocs "Attendance" "attendance_date" $MYDATES
    Remove-MyDocs "Finger Log" "work_date" $MYDATES
    Remove-MyDocs "OT Approval" "work_date" $MYDATES
}

function New-OT([string]$Employee, [string]$EmployeeName, [string]$Date, [string]$Type, [double]$Hours, [string]$StartWork, [string]$OtEnd) {
    $emp = Get-Doc "ADMIN" "Employee" $Employee
    $r = Insert-Doc "HRM" @{
        doctype = "OT Approval"; work_date = $Date; type = $Type
        ot_department = $emp.department; reason = "WF-GAP S4 fixture"
        emp_list = @(@{
            work_date = $Date; emp_id = $Employee; emp_name = $EmployeeName
            start_work = $StartWork; ot_end = $OtEnd; ot_duration = $Hours
        })
    }
    if ($r.code -ne 200) { Write-Host "   OT insert failed: $($r.raw)"; return $null }
    $nm = if ($r.data.message -is [string]) { $r.data.message } else { $r.data.message.name }
    $s = Submit-Doc "HRM" "OT Approval" $nm
    if ($s.code -ne 200) { Write-Host "   OT submit failed: $($s.raw)"; return $null }
    return $nm
}

function New-Log([string]$Employee, [string]$EmployeeName, [string]$Date, [string]$In, [string]$Out) {
    $r = Insert-Doc "HRM" @{
        doctype = "Finger Log"; employee = $Employee; employee_name = $EmployeeName; work_date = $Date
        time_in = $In; break = "12:30:00"; resume = "13:30:00"; out = $Out; overtime = 2
    }
    if ($r.code -ne 200) { Write-Host "   log insert failed: $($r.raw)"; return $null }
    $nm = if ($r.data.message -is [string]) { $r.data.message } else { $r.data.message.name }
    $s = Submit-Doc "HRM" "Finger Log" $nm
    if ($s.code -ne 200) { Write-Host "   log submit failed: $($s.raw)"; return $null }
    return $nm
}

function Log-Doc([string]$Date) {
    $rows = Get-List "ADMIN" "Finger Log" @(
        @("employee", "=", $EMP16), @("work_date", "=", $Date), @("docstatus", "<", 2)
    ) @("name")
    if ($rows.Count -eq 1) { return Get-Doc "ADMIN" "Finger Log" $rows[0].name }
    return $null
}

# ------------------------------------------------------------------
Write-Host "=== S4 - OT Approval branches + lifecycle ==="
Clean-All
$e16 = Get-Doc "ADMIN" "Employee" $EMP16

# FIX - no LIVE pre-existing approval for the fixture employee on the fixture dates (T-CLEAN pattern)
$live = Get-List "ADMIN" "OT Approval Table" @(
    @("emp_id", "=", $EMP16), @("work_date", "in", $MYDATES), @("docstatus", "=", 1)
) @("name")
Check "FIX-NO-LIVE-OT" ($live.Count -eq 0) "no live pre-existing approval for $EMP16 on fixture dates ($($live.Count) found)"

# O1 - special_approve grants MORE than clocked (~2h) -> final_ot = granted, has_overwrite = 1
$ot1 = New-OT $EMP16 $e16.employee_name $D1 "special_approve" 10 "08:00:00" "18:00:00"
$lg1 = New-Log $EMP16 $e16.employee_name $D1 "08:00:00" "18:30:00"
$d1 = Log-Doc $D1
Check "O1-SPECIAL-OVER" ($null -ne $ot1 -and $null -ne $lg1 -and $d1.docstatus -eq 1 -and $d1.final_ot -eq 10 -and $d1.has_overwrite -eq 1) "clocked~$($d1.ot_in_hour)h, final_ot=$($d1.final_ot), has_overwrite=$($d1.has_overwrite)"

# O2 - special_approve grants LESS than clocked -> override wins either way
$ot2 = New-OT $EMP16 $e16.employee_name $D2 "special_approve" 1 "08:00:00" "18:00:00"
$lg2 = New-Log $EMP16 $e16.employee_name $D2 "08:00:00" "18:30:00"
$d2 = Log-Doc $D2
Check "O2-SPECIAL-UNDER" ($null -ne $ot2 -and $null -ne $lg2 -and $d2.final_ot -eq 1 -and $d2.has_overwrite -eq 1) "clocked~$($d2.ot_in_hour)h, final_ot=$($d2.final_ot)"

# O3 - NORMAL approval, duration check must pass: (ot_end - start) - work_hours = 2.0
$ot3 = New-OT $EMP16 $e16.employee_name $D3 "normal" 2.0 "08:00:00" "18:30:00"
$lg3 = New-Log $EMP16 $e16.employee_name $D3 "08:00:00" "18:30:00"
$d3 = Log-Doc $D3
Check "O3-NORMAL" ($null -ne $ot3 -and $null -ne $lg3 -and $d3.final_ot -eq 2.0 -and $d3.has_overwrite -eq 0) "final_ot=$($d3.final_ot), has_overwrite=$($d3.has_overwrite)"

# O4 - TRUTH: cancelling the approval AFTER the log submitted is REFUSED
# (LinkExistsError - the log's ot_approval_id freezes the approval lifecycle)
$c4 = Cancel-Doc "HRM" "OT Approval" $ot3
$d3b = Get-Doc "ADMIN" "Finger Log" $lg3
Check "O4-CANCEL-TRUTH" ($c4.code -ne 200 -and $d3b.docstatus -eq 1 -and $d3b.final_ot -eq 2.0 -and $d3b.ot_approval_id -eq $ot3) "TRUTH: cancel refused ($($c4.code)); log untouched ds=$($d3b.docstatus) final_ot=$($d3b.final_ot) (REPORT)"

# O5 - TRUTH: a replacement approval for the same date is refused too (the old one
# is still live because O4 cannot cancel it) - has_previous_submission fires
$ot5 = New-OT $EMP16 $e16.employee_name $D3 "normal" 1.0 "08:00:00" "17:30:00"
$d3c = Get-Doc "ADMIN" "Finger Log" $lg3
Check "O5-REPLACE-TRUTH" ($null -eq $ot5 -and $d3c.final_ot -eq 2.0) "TRUTH: second approval refused; log unchanged final_ot=$($d3c.final_ot) (REPORT)"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$left = Count-MyDocs "OT Approval" "work_date" $MYDATES
$leftL = Count-MyDocs "Finger Log" "work_date" $MYDATES
$leftA = Count-MyDocs "Attendance" "attendance_date" $MYDATES
Check "CLEAN" ($left -eq 0 -and $leftL -eq 0 -and $leftA -eq 0) "session-owned leftovers: ot=$left logs=$leftL att=$leftA"

Summary
