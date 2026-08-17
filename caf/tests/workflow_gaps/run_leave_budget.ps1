# S2 — leave budget: one application over the balance. NEW file.

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP13 = "HR-EMP-00013"
$TYPE = "Sick Leave"        # paid, needs balance, not in the counted codes
$D1 = "2026-06-01"           # B1: 15-day span start
$D2 = "2026-06-16"           # B2: 10-day span start
$D3 = "2026-06-02"           # B3: second big span start
$FROMDATES = @($D1, $D2, $D3)

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    Remove-MyDocs "Leave Application" "from_date" $FROMDATES
    Remove-MyDocs "Attendance" "attendance_date" @("2026-06-01","2026-06-15","2026-06-16","2026-06-25","2026-06-02","2026-06-12")
    Remove-MyDocs "Leave Allocation" "from_date" @("2026-06-01")
}

# ------------------------------------------------------------------
Write-Host "=== S2 - leave budget ==="
Clean-All

# allocation: 10 days Privilege for June 2026
$alloc = Insert-Doc "HRM" @{
    doctype = "Leave Allocation"; employee = $EMP13; leave_type = $TYPE
    from_date = "2026-06-01"; to_date = "2026-06-30"; new_leaves_allocated = 10
}
$allocName = if ($alloc.code -eq 200) { $alloc.data.message.name } else { $null }
$as = Submit-Doc "HRM" "Leave Allocation" $allocName
Check "SETUP-ALLOC" ($null -ne $allocName -and $as.code -eq 200) "allocation 10 days Privilege: $allocName"

# B1 - 15 days vs 10 balance
$b1 = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D1; to_date = "2026-06-15"; leave_type = $TYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S2 B1" }
Check "B1-OVER-BUDGET" ($b1.code -ne 200) "15-day application refused ($($b1.code)): $($b1.raw)"

# B2 - control: within budget accepted
$b2 = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D2; to_date = "2026-06-25"; leave_type = $TYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S2 B2" }
Check "B2-CONTROL" ($b2.code -eq 200) "10-day application accepted (control) — a refused B1 alone proves nothing"

# B3 - second large application: remaining balance blocks it
$b3 = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D3; to_date = "2026-06-12"; leave_type = $TYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S2 B3" }
Check "B3-EXHAUSTED" ($b3.code -ne 200) "second large application refused ($($b3.code)): $($b3.raw)"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$left = Count-MyDocs "Leave Application" "from_date" $FROMDATES
$leftA = Count-MyDocs "Leave Allocation" "from_date" @("2026-06-01")
Check "CLEAN" ($left -eq 0 -and $leftA -eq 0) "session-owned leftovers: leave=$left alloc=$leftA"

Summary
