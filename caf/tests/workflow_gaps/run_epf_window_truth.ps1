# S6 — EPF: D64 "Completed means final", standing-feedback escape hatch,
# cancel truth, and the T15 truth-test. NEW file.

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP13 = "HR-EMP-00013"
$REVIEWER = "HR-EMP-00011"
$CYCLE = "2026-06"

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    # added_on is stored as a DATETIME despite being a Date field - the "in"
    # exact-match misses it. owner + creation >= is the reliable scope.
    $epfs = Get-List "ADMIN" "Employee Performance Feedback" @(
        @("owner", "in", $SessionUsers), @("creation", ">=", "2026-08-14")
    ) @("name")
    foreach ($e in $epfs) { Remove-Doc "ADMIN" "Employee Performance Feedback" $e.name | Out-Null }
    Remove-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
}

# ------------------------------------------------------------------
Write-Host "=== S6 - EPF: D64 + standing feedback + T15 truth ==="
Clean-All

# appraisal C created and SUBMITTED FOR REVIEW (Pending HR Review) — not yet completed
$c = Insert-Doc "SUP" @{ doctype = "Appraisal"; employee = $EMP13; appraisal_cycle = $CYCLE; appraisal_template = "CAF Monthly Appraisal" }
$APP_C = $c.data.message.name
WF-Action "SUP" "Appraisal" $APP_C "Submit for Review" | Out-Null
$cd = Get-Doc "ADMIN" "Appraisal" $APP_C
Check "SETUP-APP-C" ($cd.workflow_state -eq "Pending HR Review") "appraisal C state: $($cd.workflow_state)"

# F1 - linked EPF while Pending HR Review: allowed, avg updates
$f1 = Insert-Doc "HRM" @{ doctype = "Employee Performance Feedback"; employee = $EMP13; reviewer = $REVIEWER; appraisal = $APP_C; feedback = "WF-GAP S6 fixture"; feedback_ratings = @(@{ criteria = "Teamwork"; per_weightage = 100; rating = 4.0 }) }
$F1N = if ($f1.code -eq 200) { $f1.data.message.name } else { $null }
Check "F1-INSERT" ($null -ne $F1N) "linked EPF before completion inserted: $F1N (err: $($f1.raw))"
$f1s = Submit-Doc "HRM" "Employee Performance Feedback" $F1N
$c2 = Get-Doc "ADMIN" "Appraisal" $APP_C
Check "F1-AVG" ($f1s.code -eq 200 -and $c2.avg_feedback_score -gt 0) "EPF submitted; avg_feedback_score = $($c2.avg_feedback_score)"

# now HR completes the appraisal
WF-Action "HRM" "Appraisal" $APP_C "Approve" | Out-Null
$c3 = Get-Doc "ADMIN" "Appraisal" $APP_C
Check "SETUP-COMPLETE" ($c3.workflow_state -eq "Completed" -and $c3.docstatus -eq 1) "appraisal Completed: ds=$($c3.docstatus)"

# F2 - D64 truth: a NEW linked EPF after Completed is refused, message points to standing feedback
$f2 = Insert-Doc "HRM" @{ doctype = "Employee Performance Feedback"; employee = $EMP13; reviewer = $REVIEWER; appraisal = $APP_C; feedback = "WF-GAP S6 fixture" }
Check "F2-D64" ($f2.code -ne 200 -and $f2.raw -match "already been completed") "linked EPF after Completed refused ($($f2.code)) — 'Completed means final' with escape-hatch hint"

# F2b - the escape hatch: UNLINKED standing feedback after Completed is allowed, scores nothing (D65)
$f2b = Insert-Doc "HRM" @{ doctype = "Employee Performance Feedback"; employee = $EMP13; reviewer = $REVIEWER; feedback = "WF-GAP S6 fixture" }
$F2BN = if ($f2b.code -eq 200) { $f2b.data.message.name } else { $null }
Check "F2B-STANDING" ($null -ne $F2BN) "standing (unlinked) EPF after Completed allowed: $F2BN"
$c4 = Get-Doc "ADMIN" "Appraisal" $APP_C
Check "F2B-NO-SCORE" ($c4.avg_feedback_score -eq $c3.avg_feedback_score) "standing feedback moved no score: $($c3.avg_feedback_score) -> $($c4.avg_feedback_score)"

# F3 - HRM cancels a submitted linked EPF (truth)
$f3 = Cancel-Doc "HRM" "Employee Performance Feedback" $F1N
Check "F3-CANCEL" ($f3.code -eq 200) "HRM cancels submitted EPF: $($f3.code) (truth)"

# F5 - T15 truth: ordinary Employee files STANDING feedback about a colleague
$f5 = Insert-Doc "EMP" @{ doctype = "Employee Performance Feedback"; employee = $EMP13; reviewer = $REVIEWER; feedback = "WF-GAP S6 fixture" }
$F5N = if ($f5.code -eq 200) { $f5.data.message.name } else { $null }
Check "F5-T15-TRUTH" ($null -ne $F5N) "TRUTH: ordinary Employee CAN file feedback about a colleague ($($f5.code)) - T15 restriction never built (REPORT)"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$leftE = @(Get-List "ADMIN" "Employee Performance Feedback" @(
    @("owner", "in", $SessionUsers), @("creation", ">=", "2026-08-14")
) @("name")).Count
$leftA = Count-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
Check "CLEAN" ($leftE -eq 0 -and $leftA -eq 0) "session-owned leftovers: epf=$leftE app=$leftA"

Summary

