# S4 — OT Approval branches: special_approve over/under, normal control, and the
# approval lifecycle AFTER the log submitted (cancel / replace). NEW file.

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP16 = "HR-EMP-00016"   # 8am Schedule (OT eligible, gate 30 round 30)
$D1 = "2026-05-25"   # O1 special over
$D2 = "2026-05-26"   # O2 special under
$D3 = "2026-06-01"   # O3 normal control + O4 cascade + O5 replace + O6 emp_list guard
$D4 = "2026-05-27"   # O7 rollback (aborted special_approve)
$MYDATES = @($D1, $D2, $D3, $D4)

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
# ⚠️ child-table get_list WITHOUT a parent arg 403s for EVERYONE (db_query.py
# check_parent_permission, quirk filed 2026-08-17) - so walk the parent docs.
$liveParents = Get-List "ADMIN" "OT Approval" @(
    @("work_date", "in", $MYDATES), @("docstatus", "=", 1)
) @("name")
$liveForEmp = 0
foreach ($p in $liveParents) {
    $pd = Get-Doc "ADMIN" "OT Approval" $p.name
    foreach ($row in @($pd.emp_list)) {
        if ($row.emp_id -eq $EMP16 -and $row.docstatus -eq 1) { $liveForEmp++ }
    }
}
Check "FIX-NO-LIVE-OT" ($liveForEmp -eq 0) "no live pre-existing approval for $EMP16 on fixture dates ($liveForEmp found)"

# O1 - special_approve grants MORE than clocked (~2h) -> final_ot = granted, has_overwrite = 1
$ot1 = New-OT $EMP16 $e16.employee_name $D1 "special_approve" 10 "08:00:00" "18:00:00"
$lg1 = New-Log $EMP16 $e16.employee_name $D1 "08:00:00" "18:30:00"
# ⚠️ PowerShell is CASE-INSENSITIVE: $d1 would clobber $D1 (the date) and
# silently corrupt the NEXT insert's work_date. The locals are $fl1/$fl2/$fl3.
$fl1 = Log-Doc $D1
Check "O1-SPECIAL-OVER" ($null -ne $ot1 -and $null -ne $lg1 -and $fl1.docstatus -eq 1 -and $fl1.final_ot -eq 10 -and $fl1.has_overwrite -eq 1) "clocked~$($fl1.ot_in_hour)h, final_ot=$($fl1.final_ot), has_overwrite=$($fl1.has_overwrite)"

# O2 - special_approve grants LESS than clocked -> override wins either way
$ot2 = New-OT $EMP16 $e16.employee_name $D2 "special_approve" 1 "08:00:00" "18:00:00"
$lg2 = New-Log $EMP16 $e16.employee_name $D2 "08:00:00" "18:30:00"
$fl2 = Log-Doc $D2
Check "O2-SPECIAL-UNDER" ($null -ne $ot2 -and $null -ne $lg2 -and $fl2.final_ot -eq 1 -and $fl2.has_overwrite -eq 1) "clocked~$($fl2.ot_in_hour)h, final_ot=$($fl2.final_ot)"

# O3 - NORMAL approval, duration check must pass: (ot_end - start) - work_hours = 2.0
$ot3 = New-OT $EMP16 $e16.employee_name $D3 "normal" 2.0 "08:00:00" "18:30:00"
$lg3 = New-Log $EMP16 $e16.employee_name $D3 "08:00:00" "18:30:00"
$fl3 = Log-Doc $D3
Check "O3-NORMAL" ($null -ne $ot3 -and $null -ne $lg3 -and $fl3.final_ot -eq 2.0 -and $fl3.has_overwrite -eq 0) "final_ot=$($fl3.final_ot), has_overwrite=$($fl3.has_overwrite)"

# O4 (2026-08-15, D-13) - the cascade: cancelling the approval after the log
# submitted now WORKS. The linked log is zeroed and flagged for HR - the
# "machine flags, HR decides" shape.
$c4 = Cancel-Doc "HRM" "OT Approval" $ot3
$d3b = Get-Doc "ADMIN" "Finger Log" $lg3
Check "O4-CANCEL-CASCADE" ($c4.code -eq 200 -and $d3b.docstatus -eq 1 -and $d3b.final_ot -eq 0 -and [string]$d3b.ot_approval_id -eq "" -and $d3b.caf_hr_review -eq 1) "cascade: cancel=$($c4.code); log stays submitted ds=$($d3b.docstatus), final_ot=$($d3b.final_ot), ot_approval_id='$($d3b.ot_approval_id)', caf_hr_review=$($d3b.caf_hr_review)"

# O5 (2026-08-15, D-13) - the cascade freed the date: a replacement approval
# CAN now be filed (the old child rows are docstatus=2).
$ot5 = New-OT $EMP16 $e16.employee_name $D3 "normal" 1.0 "08:00:00" "17:30:00"
Check "O5-REPLACE-NOW-ALLOWED" ($null -ne $ot5) "replacement approval after cascade: filed $ot5"

# O6 - hygiene 2 (D-13): the submitted approval's child rows refuse edits
if ($null -ne $ot5) {
    $o6doc = Get-Doc "ADMIN" "OT Approval" $ot5
    $o6rows = @($o6doc.emp_list)
    $o6rows[0].ot_duration = 1.5
    $o6 = Invoke-Call "HRM" "PUT" "/api/resource/OT%20Approval/$ot5" @{ emp_list = $o6rows }
    Check "O6-EMPLIST-GUARD" ($o6.code -ne 200 -and $o6.raw -match "employee rows cannot be changed") "submitted approval's emp_list edit refused ($($o6.code)): $($o6.raw.Substring(0,[Math]::Min(110,[string]$o6.raw.Length)))"
} else {
    Check "O6-EMPLIST-GUARD" $false "no replacement approval to probe (O5 failed)"
}

# O7 - hygiene 1 (D-13, commit removed): an ABORTED special_approve must leave
# the previous approval's rows untouched (no partial commit).
$ot7 = New-OT $EMP16 $e16.employee_name $D4 "special_approve" 10 "08:00:00" "18:00:00"
$bad = Insert-Doc "HRM" @{
    doctype = "OT Approval"; work_date = $D4; type = "special_approve"
    ot_department = "NOPE-NOT-A-DEPT"; reason = "WF-GAP S4 O7"
    emp_list = @(@{ work_date = $D4; emp_id = $EMP16; emp_name = $e16.employee_name
                    start_work = "08:00:00"; ot_end = "18:00:00"; ot_duration = 10 })
}
$ot7doc = Get-Doc "ADMIN" "OT Approval" $ot7
$childDs = if ($null -ne $ot7doc -and @($ot7doc.emp_list).Count -ge 1) { $ot7doc.emp_list[0].docstatus } else { "none" }
Check "O7-ROLLBACK" ($null -ne $ot7 -and $bad.code -ne 200 -and $childDs -eq 1) "aborted special_approve rolled back: ot7=$ot7 bad-insert=$($bad.code) child-ds=$childDs"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$left = Count-MyDocs "OT Approval" "work_date" $MYDATES
$leftL = Count-MyDocs "Finger Log" "work_date" $MYDATES
$leftA = Count-MyDocs "Attendance" "attendance_date" $MYDATES
Check "CLEAN" ($left -eq 0 -and $leftL -eq 0 -and $leftA -eq 0) "session-owned leftovers: ot=$left logs=$leftL att=$leftA"

Summary
