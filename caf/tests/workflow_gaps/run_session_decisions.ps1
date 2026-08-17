# S10 — the fix-session decisions regression suite (D-10, 2026-08-15).
# ONE suite, one test row per decision in FIX_DECISION_LOG.md:
#   D-1/D-2/AC-1 scoped read · D-4 flags visible · D-6 employee Link
#   D-7 calendar content + pink · D-8 EPF complaint rule · D-9 FL cancel cascade
#   D-12 Attendance guard · D-13 OT cascade + dashboards · D-15 FL refresh
# Closed-window appraisal refresh (D-13) is covered by the companion
# session_decisions_verify.py (bench execute - needs a backdated Version row).
# Run: pwsh -NoProfile -ExecutionPolicy Bypass -File run_session_decisions.ps1

$ErrorActionPreference = "Stop"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"
. "\\wsl.localhost\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\workflow_gaps\common.ps1"

$EMP13 = "HR-EMP-00013"
$EMP_NAME = "Mohd Hairy Bin Abd Latif"
$OTHER = "HR-EMP-00016"        # someone else's rows - a colleague
$LTYPE = "Leave Without Pay"
$CYCLE = "2026-06"
$D_ABS = "2026-06-23"          # SD7 pink-Absent day (Tuesday, Workday)
$D_LV  = "2026-06-24"          # SD2/SD10/SD15 leave day -> DRAFT + On Leave
$D_OT  = "2026-06-25"          # SD9 OT cascade day
$D_FL  = "2026-06-26"          # SD12/SD13 FL cancel + D-15 refresh day
$D_JUNK = "2026-06-30"         # SD6 junk-insert day (nothing else touches it)
$OT_SHIFT = "8am Schedule"     # mohd's default (8:30am) has caf_allow_ot=0; SA overrides for D_OT
$MYDATES = @($D_ABS, $D_LV, $D_OT, $D_FL, $D_JUNK)

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    # D-12 phased teardown: cancel leaves -> attendance -> everything else.
    Cancel-MyDocs "Leave Application" "from_date" $MYDATES
    Remove-MyDocs "Attendance" "attendance_date" $MYDATES
    Remove-MyDocs "Finger Log" "work_date" $MYDATES
    Remove-MyDocs "OT Approval" "work_date" $MYDATES
    Remove-MyDocs "Shift Assignment" "start_date" $MYDATES
    Remove-MyDocs "Leave Application" "from_date" $MYDATES
    Remove-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
}

function Approve-Leave([string]$Name) {
    WF-Action "SUP" "Leave Application" $Name "Submit for Approval" | Out-Null
    WF-Action "SUP" "Leave Application" $Name "Approve" | Out-Null
    WF-Action "HRM" "Leave Application" $Name "Approve" | Out-Null
    WF-Action "HRM" "Leave Application" $Name "Approve" | Out-Null
}

function New-Submitted-Log([string]$Date, [string]$In, [string]$Out, [double]$Overtime) {
    $zero = ($In -eq "00:00:00")
    $r = Insert-Doc "HRM" @{
        doctype = "Finger Log"; employee = $EMP13; employee_name = $EMP_NAME; work_date = $Date
        time_in = $In; break = $(if ($zero) { "00:00:00" } else { "12:30:00" })
        resume = $(if ($zero) { "00:00:00" } else { "13:30:00" }); out = $Out; overtime = $Overtime
    }
    if ($r.code -ne 200) { return $null }
    $nm = $r.data.message.name
    $s = Submit-Doc "HRM" "Finger Log" $nm
    if ($s.code -ne 200) { return $null }
    return $nm
}

function New-Submitted-Appraisal {
    $c = Insert-Doc "SUP" @{ doctype = "Appraisal"; employee = $EMP13; appraisal_cycle = $CYCLE; appraisal_template = "CAF Monthly Appraisal" }
    if ($c.code -ne 200) { return $null }
    $nm = $c.data.message.name
    WF-Action "SUP" "Appraisal" $nm "Submit for Review" | Out-Null
    WF-Action "HRM" "Appraisal" $nm "Approve" | Out-Null
    return $nm
}

function Appraisal-Cell([string]$App, [string]$Kra) {
    $d = Get-Doc "ADMIN" "Appraisal" $App
    if ($null -eq $d) { return $null }
    $row = @($d.appraisal_kra | Where-Object { $_.kra -eq $Kra } | Select-Object -First 1)
    if ($row.Count -eq 0) { return $null }
    return [string]$row[0].caf_date_cell
}

# ------------------------------------------------------------------
Write-Host "=== S10 - fix-session decisions regression ==="
Clean-All

# ---- SD1 (D-1/AC-1): EMP list returns ONLY own rows ----
$empList = Invoke-Call "EMP" "GET" "/api/resource/Finger%20Log?limit_page_length=50&fields=%5B%22name%22%2C%22employee%22%5D" $null
$foreign = @($empList.data.data | Where-Object { $_.employee -ne $EMP13 })
Check "SD1-EMP-LIST-SCOPE" ($empList.code -eq 200 -and @($empList.data.data).Count -gt 0 -and $foreign.Count -eq 0) "EMP list: $(@($empList.data.data).Count) rows, $($foreign.Count) foreign (AC-1)"

# ---- SD3 (AC-1): a colleague's row by name is refused ----
$hrmRows = (Invoke-Call "HRM" "GET" "/api/resource/Finger%20Log?limit_page_length=20&fields=%5B%22name%22%2C%22employee%22%5D" $null).data.data
$colleagueRow = @($hrmRows | Where-Object { $_.employee -ne $EMP13 } | Select-Object -First 1)
if ($colleagueRow) {
    $g = Invoke-Call "EMP" "GET" "/api/resource/Finger%20Log/$([uri]::EscapeDataString($colleagueRow.name))" $null
    Check "SD3-COLLEAGUE-403" ($g.code -eq 403) "EMP GET colleague's row '$($colleagueRow.name)': $($g.code) (must be 403)"
} else { Check "SD3-COLLEAGUE-403" $false "no colleague row found" }

# ---- SD4 (D-1): HRM sees everyone ----
$hrmList = (Invoke-Call "HRM" "GET" "/api/resource/Finger%20Log?limit_page_length=50&fields=%5B%22name%22%2C%22employee%22%5D" $null).data.data
$hrmEmps = @($hrmList | Select-Object -ExpandProperty employee -Unique).Count
Check "SD4-HRM-ALL" ($hrmEmps -gt 1) "HRM list spans $hrmEmps distinct employees"

# ---- SD5 (D-2): the desk report gate - HR only ----
$gateEmp = Invoke-Call "EMP" "POST" "/api/method/frappe.desk.query_report.run" @{ report_name = "My Attendance"; filters = @{ from_date = $D_ABS; to_date = $D_ABS } }
$gateHrm = Invoke-Call "HRM" "POST" "/api/method/frappe.desk.query_report.run" @{ report_name = "My Attendance"; filters = @{ from_date = $D_ABS; to_date = $D_ABS } }
Check "SD5-REPORT-GATE" ($gateEmp.code -ne 200 -and $gateHrm.code -eq 200) "report as EMP: $($gateEmp.code) (refused), as HRM: $($gateHrm.code)"

# ---- SD6 (D-6): the employee Link refuses junk loudly (on an untouched date) ----
$junk = Insert-Doc "HRM" @{ doctype = "Finger Log"; employee = "NOT-AN-EMPLOYEE-XX"; employee_name = "X"; work_date = $D_JUNK; time_in = "00:00:00"; break = "00:00:00"; resume = "00:00:00"; out = "00:00:00"; overtime = 0 }
Check "SD6-LINK-JUNK-REFUSED" ($junk.code -ne 200 -and $junk.raw -match "does not exist|Could not find Employee") "junk employee refused ($($junk.code)) with a loud message (D-6)"

# ---- SD7 (D-7): pink box for Absent + SUBMITTED label ----
$lgAbs = New-Submitted-Log $D_ABS "00:00:00" "00:00:00" 0
$calAbs = Invoke-Call "EMP" "POST" "/api/method/caf.caf.finger_log_scope.get_employee_events" @{ doctype = "Finger Log"; start = $D_ABS; end = $D_ABS }
$evAbs = @($calAbs.data.message | Where-Object { $_.name -eq $lgAbs } | Select-Object -First 1)
Check "SD7-CAL-PINK" ($null -ne $lgAbs -and $calAbs.code -eq 200 -and $null -ne $evAbs -and $evAbs.color -eq "#f8d7da" -and $evAbs.title -match "SUBMITTED" -and $evAbs.title -match "Absent") "Absent day renders pink + SUBMITTED + Absent: color=$($evAbs.color) title='$($evAbs.title)'"

# ---- SD2 (D-5/D-7): leave day renders DRAFT + On Leave ----
# The importer leaves an all-zero DRAFT on a leave day (assert_no_clash refuses
# it); the calendar's status join explains it. Create that draft first.
$draftLv = Insert-Doc "HRM" @{ doctype = "Finger Log"; employee = $EMP13; employee_name = $EMP_NAME; work_date = $D_LV; time_in = "00:00:00"; break = "00:00:00"; resume = "00:00:00"; out = "00:00:00"; overtime = 0 }
$lv1 = Insert-Doc "EMP" @{ doctype = "Leave Application"; employee = $EMP13; from_date = $D_LV; to_date = $D_LV; leave_type = $LTYPE; leave_approver = "too@caffood.com"; description = "WF-GAP S10 SD2" }
$LV1N = $lv1.data.message.name
Approve-Leave $LV1N
$calLv = Invoke-Call "EMP" "POST" "/api/method/caf.caf.finger_log_scope.get_employee_events" @{ doctype = "Finger Log"; start = $D_LV; end = $D_LV }
$evLv = @($calLv.data.message | Where-Object { $_.start -eq $D_LV } | Select-Object -First 1)
Check "SD2-CAL-LEAVE" ($calLv.code -eq 200 -and $null -ne $evLv -and $evLv.title -match "DRAFT" -and $evLv.title -match "On Leave") "leave day renders DRAFT + On Leave (status join, no MC leak): '$($evLv.title)'"

# ---- SD10 (D-12): direct cancel of the leave-owned Attendance refused ----
$attLv = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", $D_LV), @("docstatus", "<", 2) ) @("name", "status")
$attLvN = $attLv[0].name
$cLv = Cancel-Doc "HRM" "Attendance" $attLvN
Check "SD10-ATT-GUARD" ($cLv.code -ne 200 -and $cLv.raw -match $LV1N) "leave-owned attendance cancel refused ($($cLv.code)) naming the leave (D-12)"

# ---- SD11 (D-12): non-leave attendance cancel stays open ----
$attAbs = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", $D_ABS), @("docstatus", "<", 2) ) @("name", "status")
$cAbs = Cancel-Doc "HRM" "Attendance" $attAbs[0].name
Check "SD11-NONLEAVE-CANCEL-OK" ($cAbs.code -eq 200) "plain-day attendance cancel still allowed: $($cAbs.code) (D-12 scope)"

# ---- one appraisal for the whole session (one per employee+cycle) ----
$APP = New-Submitted-Appraisal
Check "SD-APP-SETUP" ($null -ne $APP) "session appraisal: $APP"
Invoke-Call "HRM" "POST" "/api/method/run_doc_method" @{ dt = "Appraisal"; dn = $APP; method = "refresh_auto_fill_action" } | Out-Null

# ---- SD9 (D-13): OT cascade - zero + flag + dashboard + open-window refresh ----
# mohd's default shift forbids OT; a Shift Assignment gives D_OT an OT shift.
$saOt = Insert-Doc "HRM" @{ doctype = "Shift Assignment"; employee = $EMP13; employee_name = $EMP_NAME; shift_type = $OT_SHIFT; start_date = $D_OT; end_date = $D_OT }
$saOtN = $saOt.data.message.name
Submit-Doc "HRM" "Shift Assignment" $saOtN | Out-Null
$ot9 = Insert-Doc "HRM" @{
    doctype = "OT Approval"; work_date = $D_OT; type = "normal"
    ot_department = (Get-Doc "ADMIN" "Employee" $EMP13).department; reason = "WF-GAP S10 SD9"
    emp_list = @(@{ work_date = $D_OT; emp_id = $EMP13; emp_name = $EMP_NAME
                    start_work = "08:00:00"; ot_end = "18:30:00"; ot_duration = 2.0 })
}
$ot9n = $ot9.data.message.name
Submit-Doc "HRM" "OT Approval" $ot9n | Out-Null
$lgOt = New-Submitted-Log $D_OT "08:00:00" "18:30:00" 2
$otCellBefore = Appraisal-Cell $APP "OT Hours"
$cOt = Cancel-Doc "HRM" "OT Approval" $ot9n
$lgOtDoc = Get-Doc "ADMIN" "Finger Log" $lgOt
$otCellAfter = Appraisal-Cell $APP "OT Hours"
Check "SD9-CASCADE-ZERO" ($cOt.code -eq 200 -and $lgOtDoc.docstatus -eq 1 -and $lgOtDoc.final_ot -eq 0 -and [string]$lgOtDoc.ot_approval_id -eq "" -and $lgOtDoc.caf_hr_review -eq 1) "cascade zeroed+flagged the log (ds=$($lgOtDoc.docstatus) ot=$($lgOtDoc.final_ot) flag=$($lgOtDoc.caf_hr_review))"
$empSeesFlag = (Invoke-Call "EMP" "GET" "/api/resource/Finger%20Log/$([uri]::EscapeDataString($lgOt))" $null).data.data
Check "SD9-D4-FLAGS-VISIBLE" ($null -ne $empSeesFlag -and $empSeesFlag.caf_hr_review -eq 1 -and ([string]$empSeesFlag.caf_hr_review_note) -match "OT Approval") "employee sees his own HR flags (D-4): flag=$($empSeesFlag.caf_hr_review) note='$($empSeesFlag.caf_hr_review_note)'"
$flags = Invoke-Call "HRM" "POST" "/api/method/caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.get_hr_review_flags" @{ limit = 50 }
$flagNames = @($flags.data.message.rows | ForEach-Object { $_.name })
Check "SD9-DASH-FLAG-PANEL" ($flags.code -eq 200 -and $lgOt -in $flagNames) "HR dashboard review panel lists the flagged log '$lgOt' (MG's dashboard requirement)"
Check "SD9-WINDOW-REFRESH" ($otCellBefore -ne $otCellAfter) "open-window appraisal OT cell refreshed by the cascade: '$otCellBefore' -> '$otCellAfter'"

# ---- SD13 (D-15): FL submit refreshes a submitted appraisal (no manual call) ----
# The attendance cell lists the NOT-present days (leave + Absent, FBR37), so the
# fixture log is an all-zero Absent day - a Present day would not move the cell.
$flCellBefore = Appraisal-Cell $APP "Attendance"
$lgFl = New-Submitted-Log $D_FL "00:00:00" "00:00:00" 0
$flCellAfter = Appraisal-Cell $APP "Attendance"
Check "SD13-D15-AUTO-REFRESH" ($null -ne $lgFl -and $flCellBefore -ne $flCellAfter -and ([string]$flCellAfter) -match "26") "FL submit auto-refreshed the appraisal cell: '$flCellBefore' -> '$flCellAfter' (D-15)"

# ---- SD12 (D-9): HR cancels a submitted FL -> linked attendance cascade ----
$attFl = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", $D_FL), @("docstatus", "<", 2) ) @("name", "docstatus")
$cFl = Cancel-Doc "HRM" "Finger Log" $lgFl
$attFlAfter = Get-List "ADMIN" "Attendance" @( @("employee", "=", $EMP13), @("attendance_date", "=", $D_FL), @("docstatus", "<", 2) ) @("name", "docstatus")
Check "SD12-FL-CANCEL-CASCADE" ($cFl.code -eq 200 -and $attFl.Count -eq 1 -and $attFlAfter.Count -eq 0) "FL cancel cascaded to Attendance ($($attFl.Count) live -> $($attFlAfter.Count)) (D-9)"

# ---- SD14 (D-8): complaint-letter EPF - leaf employee files about a colleague ----
$epf = Insert-Doc "EMP" @{ doctype = "Employee Performance Feedback"; employee = $OTHER; reviewer = $EMP13; feedback = "WF-GAP S10 SD14 complaint" }
Check "SD14-EPF-COMPLAINT-RULE" ($epf.code -eq 200) "leaf employee files EPF about a colleague: $($epf.code) (D-8 business rule)"

# ---- SD15 (D-2): the HR report still serves HR after the leave ----
$repHrm = Invoke-Call "HRM" "POST" "/api/method/frappe.desk.query_report.run" @{ report_name = "My Attendance"; filters = @{ from_date = $D_LV; to_date = $D_LV; employee = $EMP13 } }
$rowLv = @($repHrm.data.message.result | Where-Object { $_.work_date -eq $D_LV } | Select-Object -First 1)
Check "SD15-REPORT-HR-ROWS" ($repHrm.code -eq 200 -and $null -ne $rowLv -and $rowLv.status -eq "On Leave") "HR report shows the leave row: status=$($rowLv.status) (D-2/D-5)"

# ---- dashboard: 7.2 changed-after-submission panel (MG's requirement) ----
$panel = Invoke-Call "HRM" "POST" "/api/method/caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.get_refreshed_after_submit" @{ limit = 25 }
$panelNames = @($panel.data.message.rows | ForEach-Object { $_.name })
Check "SD16-DASH-CHANGED-PANEL" ($panel.code -eq 200 -and $APP -in $panelNames) "7.2 'changed after submission' lists the refreshed appraisal '$APP' (got $($panelNames -join ','))"

# ------------------------------------------------------------------
Write-Host "`n-- cleanup (last) --"
Clean-All
$leftL = Count-MyDocs "Leave Application" "from_date" $MYDATES
$leftA = Count-MyDocs "Attendance" "attendance_date" $MYDATES
$leftF = Count-MyDocs "Finger Log" "work_date" $MYDATES
$leftO = Count-MyDocs "OT Approval" "work_date" $MYDATES
$leftS = Count-MyDocs "Shift Assignment" "start_date" $MYDATES
$leftC = Count-MyDocs "Appraisal" "appraisal_cycle" @($CYCLE)
Get-List "ADMIN" "Employee Performance Feedback" @(
    @("reviewer", "=", $EMP13), @("creation", ">=", "2026-08-14")
) @("name") | ForEach-Object { Remove-Doc "ADMIN" "Employee Performance Feedback" $_.name }
Check "CLEAN" ($leftL -eq 0 -and $leftA -eq 0 -and $leftF -eq 0 -and $leftO -eq 0 -and $leftS -eq 0 -and $leftC -eq 0) "session-owned leftovers: leave=$leftL att=$leftA logs=$leftF ot=$leftO sa=$leftS app=$leftC"

Summary
