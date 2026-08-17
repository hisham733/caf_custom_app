# S1 — the 6b leave-approval workflow walked as real roles over REST, plus
# MG's two end-to-end reflection scenarios. NEW file; nothing existing touched.
#
# Fixture (verified by S8 test_fixture_integrity):
#   EMP      mohd@caffood.com            HR-EMP-00013  (Employee)
#   SUP      too@caffood.com         HR-EMP-00003  (supervisor AND leave approver)
#   STRANGER yow.kwee@caffood.com       HR-EMP-00002  (director, pure LA, NOT mohd's approver)
#   HRM      hr.manager.test@caffood.com (HR Manager)
#   ADMIN    Administrator (setup/cleanup only)
#
# Cycle A = 2026-06 (ended), Cycle B = 2026-05 (ended) — refresh_auto_fill
# refuses unfinished months (BR6/T-F3), so both appraisals live in ENDED months.
# Leave type = "Leave Without Pay" (is_lwp, counted).
#
# Run:  pwsh -NoProfile -ExecutionPolicy Bypass -File run_leave_workflow.ps1

$ErrorActionPreference = "Stop"
$Base = "http://development.localhost:8000"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"

$EMP_HR = "HR-EMP-00013"
$HRM_HR = "HR-EMP-00003"
$EMP_NAME = "Mohd Hairy Bin Abd Latif"
$CYCLE_A = "2026-06"   # appraisal A (draft) — L1 modify scenario
$CYCLE_B = "2026-05"   # appraisal B (submitted) — L2 cancel scenario
$LTYPE   = "Leave Without Pay"
$D1 = "2026-06-15"   # L1 target (later modified to D3)
$D2 = "2026-05-25"   # L2 target (submitted appraisal B + cancel)
$D3 = "2026-06-19"   # L1 revised date
$D4 = "2026-06-22"   # L3 HRM self-approval (HRM's own employee)
$D5 = "2026-06-23"   # L4 HRM paperwork
$MYDATES = @($D1, $D2, $D3, $D4, $D5)

$script:Results = @()

function Check([string]$tid, [bool]$ok, [string]$detail) {
    $script:Results += [pscustomobject]@{ id = $tid; ok = $ok; detail = $detail }
    Write-Host ("{0} {1,-20} {2}" -f ($(if ($ok) { "PASS" } else { "FAIL" }), $tid, $detail))
}

function Invoke-Call([string]$Role, [string]$Method, [string]$Path, $Body) {
    $h = @{ Authorization = $Creds[$Role] }
    $b = $null
    if ($null -ne $Body) {
        $h["Content-Type"] = "application/json"
        $b = $Body | ConvertTo-Json -Depth 6 -Compress
    }
    try {
        $r = Invoke-WebRequest -Uri ($Base + $Path) -Method $Method -Headers $h -Body $b -UseBasicParsing -TimeoutSec 60
        $parsed = $null
        if ($r.Content) { try { $parsed = $r.Content | ConvertFrom-Json } catch { $parsed = $r.Content } }
        return [pscustomobject]@{ code = 200; data = $parsed; raw = $r.Content }
    }
    catch {
        $code = 0
        try { $code = [int]$_.Exception.Response.StatusCode } catch {}
        $err = ""
        if ($_.ErrorDetails.Message) {
            try { $err = ($_.ErrorDetails.Message | ConvertFrom-Json).exception } catch { $err = $_.ErrorDetails.Message }
            if ($err -is [string] -and $err.Length -gt 250) { $err = $err.Substring(0, 250) }
        }
        return [pscustomobject]@{ code = $code; data = $null; raw = $err }
    }
}

function Get-Doc([string]$Role, [string]$Dt, [string]$Name) {
    $r = Invoke-Call $Role "GET" "/api/resource/$Dt/$Name" $null
    if ($r.code -eq 200) { return $r.data.data } else { return $null }
}

# NOTE: filters must be passed as an array-of-arrays. Single-filter calls use the
# leading comma (e.g. ,@(@("x","=",1))) — PowerShell flattens @( @(..) ) to one
# level otherwise, which corrupts the JSON body.
function Get-List([string]$Role, [string]$Dt, $Filters, $Fields) {
    $body = @{ doctype = $Dt; filters = $Filters; fields = $Fields }
    $r = Invoke-Call $Role "POST" "/api/method/frappe.client.get_list" $body
    if ($r.code -eq 200) { return @($r.data.message) } else { return @() }
}

function WF-Action([string]$Role, [string]$Dt, [string]$Name, [string]$Action) {
    return Invoke-Call $Role "POST" "/api/method/frappe.model.workflow.apply_workflow" @{
        doc = @{ doctype = $Dt; name = $Name }; action = $Action
    }
}

function Run-Method([string]$Role, [string]$Dt, [string]$Name, [string]$Method) {
    return Invoke-Call $Role "POST" "/api/method/run_doc_method" @{
        dt = $Dt; dn = $Name; method = $Method
    }
}

function Insert-Doc([string]$Role, $Doc) {
    return Invoke-Call $Role "POST" "/api/method/frappe.client.insert" @{ doc = $Doc }
}

function Remove-Doc([string]$Role, [string]$Dt, [string]$Name) {
    $doc = Get-Doc $Role $Dt $Name
    if ($null -eq $doc) { return }
    if ($doc.docstatus -eq 1) {
        Invoke-Call $Role "PUT" "/api/resource/$Dt/$Name" @{ docstatus = 2 } | Out-Null
    }
    Invoke-Call $Role "DELETE" "/api/resource/$Dt/$Name" $null | Out-Null
}

function Clean-All {
    Write-Host "`n-- cleanup (first) --"
    foreach ($dt in @("Leave Application", "Attendance", "Finger Log", "Shift Assignment")) {
        $dateField = switch ($dt) {
            "Leave Application" { "from_date" }
            "Attendance" { "attendance_date" }
            "Finger Log" { "work_date" }
            "Shift Assignment" { "start_date" }
        }
        $rows = Get-List "ADMIN" $dt (, @(@($dateField, "in", $MYDATES))) @("name", "employee", "docstatus")
        foreach ($row in $rows) {
            if ($row.employee -notin @($EMP_HR, $HRM_HR)) { continue }
            Remove-Doc "ADMIN" $dt $row.name | Out-Null
        }
    }
    foreach ($cyc in @($CYCLE_A, $CYCLE_B)) {
        $apps = Get-List "ADMIN" "Appraisal" (, @(@("appraisal_cycle", "=", $cyc))) @("name", "employee", "docstatus")
        foreach ($a in $apps) {
            if ($a.employee -notin @($EMP_HR, $HRM_HR)) { continue }
            Remove-Doc "ADMIN" "Appraisal" $a.name | Out-Null
        }
    }
    # baseline: live attendance for EMP_HR on the D1..D3 span (06-15..06-19) must be empty
    $baseline = @(Get-List "ADMIN" "Attendance" @(
        @("employee", "=", $EMP_HR),
        @("attendance_date", "between", @($D1, $D3)),
        @("docstatus", "<", 2)
    ) @("name"))
    Check "CLEAN-BASE" ($baseline.Count -eq 0) "no live attendance for $EMP_HR on $D1..$D3 ($($baseline.Count) found)"
}

function New-Leave([string]$Role, [string]$Employee, [string]$From, [string]$To) {
    $r = Insert-Doc $Role @{
        doctype = "Leave Application"
        employee = $Employee
        from_date = $From
        to_date = $To
        leave_type = $LTYPE
        leave_approver = "too@caffood.com"
        description = "WF-GAP S1 test"
    }
    if ($r.code -ne 200) { return $null }
    if ($r.data.message -is [string]) { return $r.data.message }
    return $r.data.message.name
}

function State-Of([string]$Name) {
    $d = Get-Doc "ADMIN" "Leave Application" $Name
    return "$($d.workflow_state) | ds=$($d.docstatus) | status=$($d.status)"
}

function Attendance-Cell([string]$AppraisalName) {
    $d = Get-Doc "ADMIN" "Appraisal" $AppraisalName
    if ($null -eq $d) { return $null }
    foreach ($row in @($d.appraisal_kra)) {
        if ($row.kra -match "Attendance") { return $row.caf_date_cell }
    }
    return $null
}

# ------------------------------------------------------------------ SETUP
Write-Host "=== S1 — 6b leave workflow as roles, REST ==="
Clean-All

# FIX — no public holiday on fixture dates
$hols = Get-List "ADMIN" "Holiday" @(
    @("holiday_date", "in", $MYDATES),
    @("parent", "=", "CAF Public Holidays 2026")
) @("holiday_date")
Check "FIX-HOLIDAY" ($hols.Count -eq 0) "no CAF public holiday on fixture dates (got $($hols.Count))"

# FIX — the employee resolves a shift
$emp = Get-Doc "ADMIN" "Employee" $EMP_HR
Check "FIX-SHIFT" ($null -ne $emp.default_shift) "default_shift of $EMP_HR = $($emp.default_shift)"

# FIX — leave type is counted
$hs = Get-Doc "ADMIN" "HR Settings" "HR Settings"
Check "FIX-COUNTED" ($hs.caf_attendance_leave_codes -match [regex]::Escape($LTYPE)) "codes: $($hs.caf_attendance_leave_codes)"

# FIX — both cycles exist
$cA = Get-Doc "ADMIN" "Appraisal Cycle" $CYCLE_A
$cB = Get-Doc "ADMIN" "Appraisal Cycle" $CYCLE_B
Check "FIX-CYCLES" ($null -ne $cA -and $null -ne $cB) "cycles $CYCLE_A / $CYCLE_B exist"

# Draft all-zero Finger Log for D1 (as HRM - simulates the 4am import row, left draft)
$log1 = Insert-Doc "HRM" @{
    doctype = "Finger Log"; employee = $EMP_HR; employee_name = $EMP_NAME; work_date = $D1
    time_in = "00:00:00"; break = "00:00:00"; resume = "00:00:00"; out = "00:00:00"; overtime = 0
}
Check "SETUP-LOG1" ($log1.code -eq 200) "draft all-zero Finger Log for $D1 (err: $($log1.raw))"

# Appraisal A (DRAFT, cycle 2026-06) for the L1 modify scenario
$a1 = Insert-Doc "HRM" @{ doctype = "Appraisal"; employee = $EMP_HR; appraisal_cycle = $CYCLE_A; appraisal_template = "CAF Monthly Appraisal" }
$APP_A = if ($a1.code -eq 200) { if ($a1.data.message -is [string]) { $a1.data.message } else { $a1.data.message.name } } else { $null }
Check "SETUP-APP-A" ($null -ne $APP_A) "draft appraisal A: $APP_A (err: $($a1.raw))"
$kraA = @((Get-Doc "ADMIN" "Appraisal" $APP_A).appraisal_kra)
Check "SETUP-KRA-A" ($kraA.Count -ge 1) "grid auto-populated on insert ($($kraA.Count) rows)"
$cellA = Attendance-Cell $APP_A
Check "S1-A-BEFORE" ($cellA -notmatch "19") "appraisal A cell BEFORE leave: '$cellA' (must not contain 19)"

# Appraisal B (cycle 2026-05) — the SUPERVISOR creates it (normal flow), then
# submits it; HRM approves. (HRM cannot create+approve their own: the appraisal
# workflow's Approve has allow_self_approval=0, verified in tabWorkflow Transition.)
$b1 = Insert-Doc "SUP" @{ doctype = "Appraisal"; employee = $EMP_HR; appraisal_cycle = $CYCLE_B; appraisal_template = "CAF Monthly Appraisal" }
$APP_B = if ($b1.code -eq 200) { if ($b1.data.message -is [string]) { $b1.data.message } else { $b1.data.message.name } } else { $null }
Check "SETUP-APP-B" ($null -ne $APP_B) "appraisal B (cycle $CYCLE_B): $APP_B (err: $($b1.raw))"
$kraB = @((Get-Doc "ADMIN" "Appraisal" $APP_B).appraisal_kra)
Check "SETUP-KRA-B" ($kraB.Count -ge 1) "grid auto-populated on insert ($($kraB.Count) rows)"
$wf1 = WF-Action "SUP" "Appraisal" $APP_B "Submit for Review"
Check "SETUP-B-SUBMIT" ($wf1.code -eq 200) "SUP submits B (Employee role) — $($wf1.code): $($wf1.raw)"
$wf2 = WF-Action "HRM" "Appraisal" $APP_B "Approve"
$bDoc = Get-Doc "ADMIN" "Appraisal" $APP_B
Check "SETUP-B-DONE" ($wf2.code -eq 200 -and $bDoc.docstatus -eq 1) "B submitted: ds=$($bDoc.docstatus) state=$($bDoc.workflow_state)"

# ------------------------------------------------------------------ L1: modify chain
Write-Host "`n--- L1: file -> reject x3 -> revise -> modify dates -> approve (appraisal A reflects) ---"
$L1 = New-Leave "EMP" $EMP_HR $D1 $D1
Check "W1-CREATE" ($null -ne $L1) "EMP files L1: $L1"
$l1d = Get-Doc "ADMIN" "Leave Application" $L1
Check "W1-DRAFT" ($l1d.workflow_state -eq "Draft" -and $l1d.docstatus -eq 0) "state after insert: $(State-Of $L1)"

$w2 = Invoke-Call "EMP" "PUT" "/api/resource/Leave Application/$L1" @{ docstatus = 1 }
Check "W2-EMP-NOSUBMIT" ($w2.code -ne 200) "EMP direct submit refused ($($w2.code))"

$w3 = WF-Action "EMP" "Leave Application" $L1 "Submit for Approval"
Check "W3-EMP-NOTRANS" ($w3.code -ne 200) "EMP cannot take the transition ($($w3.code)): $($w3.raw)"

$w4 = Invoke-Call "STRANGER" "GET" "/api/resource/Leave Application/$L1" $null
Check "W4-STRANGER-READ" ($w4.code -ne 200) "STRANGER cannot read L1 ($($w4.code))"

$w5 = WF-Action "STRANGER" "Leave Application" $L1 "Submit for Approval"
Check "W5-STRANGER-TRANS" ($w5.code -ne 200) "STRANGER (pure LA, wrong employee) refused ($($w5.code)): $($w5.raw)"

$wf = WF-Action "SUP" "Leave Application" $L1 "Submit for Approval"
Check "W4B-SUP-SUBMIT" ($wf.code -eq 200) "SUP takes Submit for Approval -> $(State-Of $L1)"

$wf = WF-Action "SUP" "Leave Application" $L1 "Reject"
Check "W10-SUP-REJECT" ($wf.code -eq 200) "SUP rejects -> $(State-Of $L1)"
$l1d = Get-Doc "ADMIN" "Leave Application" $L1
Check "W10-STATUS" ($l1d.status -eq "Rejected" -and $l1d.docstatus -eq 0) "status=Rejected, ds=0 (no amend needed)"

$wf = WF-Action "SUP" "Leave Application" $L1 "Revise"
Check "W10B-REVISE" ($wf.code -eq 200 -and (Get-Doc "ADMIN" "Leave Application" $L1).workflow_state -eq "Draft") "Revise -> same doc back to Draft: $(State-Of $L1)"

$wf = WF-Action "SUP" "Leave Application" $L1 "Submit for Approval" | Out-Null
$wf = WF-Action "SUP" "Leave Application" $L1 "Approve"
Check "W6-SUP-APPROVE" ($wf.code -eq 200) "correct approver approves -> $(State-Of $L1)"

$wf = WF-Action "HRM" "Leave Application" $L1 "Reject"
Check "W11-HRM-REJECT" ($wf.code -eq 200) "HRM rejects -> $(State-Of $L1)"
$wf = WF-Action "HRM" "Leave Application" $L1 "Revise" | Out-Null
$wf = WF-Action "SUP" "Leave Application" $L1 "Submit for Approval" | Out-Null
$wf = WF-Action "SUP" "Leave Application" $L1 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L1 "Approve"
Check "W8-HRM-APPROVE" ($wf.code -eq 200) "HRM approves -> $(State-Of $L1)"
$wf = WF-Action "HRM" "Leave Application" $L1 "Reject"
Check "W11B-FINAL-REJECT" ($wf.code -eq 200) "HRM rejects at final -> $(State-Of $L1)"
$wf = WF-Action "HRM" "Leave Application" $L1 "Revise" | Out-Null

# MODIFY — EMP edits own draft to D3
$up = Invoke-Call "EMP" "PUT" "/api/resource/Leave Application/$L1" @{ from_date = $D3; to_date = $D3 }
Check "W-MODIFY" ($up.code -eq 200) "EMP modifies own draft: D1 -> D3"

$wf = WF-Action "SUP" "Leave Application" $L1 "Submit for Approval" | Out-Null
$wf = WF-Action "SUP" "Leave Application" $L1 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L1 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L1 "Approve"
Check "W9-APPROVED" ($wf.code -eq 200) "final approve -> $(State-Of $L1)"
$l1d = Get-Doc "ADMIN" "Leave Application" $L1
Check "W9-DS1" ($l1d.docstatus -eq 1 -and $l1d.status -eq "Approved") "Approved: ds=1, status=Approved"

# Scenario 1 asserts — attendance, ledger, appraisal A
$att = Get-List "ADMIN" "Attendance" @(
    @("employee", "=", $EMP_HR), @("attendance_date", "=", $D3), @("docstatus", "<", 2)
) @("name", "status", "leave_type")
Check "S1-ATT-D3" ($att.Count -eq 1 -and $att[0].status -eq "On Leave" -and $att[0].leave_type -eq $LTYPE) "Attendance ${D3}: $($att | ForEach-Object { "$($_.status)/$($_.leave_type)" })"
$attOld = Get-List "ADMIN" "Attendance" @(
    @("employee", "=", $EMP_HR), @("attendance_date", "=", $D1), @("docstatus", "<", 2)
) @("name")
Check "S1-ATT-D1-NONE" ($attOld.Count -eq 0) "no live Attendance on the OLD date D1"
$log1name = if ($log1.code -eq 200) { $log1.data.message.name } else { "" }
$log1d = Get-Doc "ADMIN" "Finger Log" $log1name
Check "S1-FL-DRAFT" ($null -ne $log1d -and $log1d.docstatus -eq 0) "Finger Log for D1 untouched (draft): ds=$($log1d.docstatus)"
$led1 = Get-List "ADMIN" "Leave Ledger Entry" @(
    @("transaction_name", "=", $L1), @("docstatus", "<", 2)
) @("name", "leaves")
Check "S1-LEDGER" ($led1.Count -gt 0 -and [math]::Abs(($led1 | Measure-Object -Property leaves -Sum).Sum) -eq 1.0) "ledger moved for L1: $($led1 | ForEach-Object { $_.leaves })"
$r1 = Run-Method "HRM" "Appraisal" $APP_A "refresh_auto_fill_action"
$cellA2 = Attendance-Cell $APP_A
Check "S1-APPR-A" ($cellA2 -match "\b19\b" -and $cellA2 -notmatch "\b15\b") "appraisal A reflects the MODIFIED date: cell='$cellA2' (want 19, not 15)"

# ------------------------------------------------------------------ L2: submitted appraisal + HRM cancel
Write-Host "`n--- L2: approve over a SUBMITTED appraisal, then HR Manager cancels ---"
$commentsBefore = @(Get-List "ADMIN" "Comment" @(
    @("reference_doctype", "=", "Appraisal"), @("reference_name", "=", $APP_B)
) @("name")).Count
$L2 = New-Leave "EMP" $EMP_HR $D2 $D2
Check "L2-CREATE" ($null -ne $L2) "EMP files L2 ($D2): $L2"
$wf = WF-Action "SUP" "Leave Application" $L2 "Submit for Approval" | Out-Null
$wf = WF-Action "SUP" "Leave Application" $L2 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L2 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L2 "Approve"
Check "L2-APPROVED" ($wf.code -eq 200) "L2 approved via workflow -> $(State-Of $L2)"
$att2 = Get-List "ADMIN" "Attendance" @(
    @("employee", "=", $EMP_HR), @("attendance_date", "=", $D2), @("docstatus", "<", 2)
) @("name", "status", "leave_type")
Check "S2-ATT" ($att2.Count -eq 1 -and $att2[0].status -eq "On Leave") "Attendance ${D2}: $($att2 | ForEach-Object { "$($_.status)/$($_.leave_type)" })"
$cellB = Attendance-Cell $APP_B
Check "S2-APPR-B-REFLECT" ($cellB -match "\b25\b") "SUBMITTED appraisal B auto-refreshed (OD-44): cell='$cellB'"
$commentsAfter = @(Get-List "ADMIN" "Comment" @(
    @("reference_doctype", "=", "Appraisal"), @("reference_name", "=", $APP_B)
) @("name")).Count
Check "S2-COMMENT" ($commentsAfter -gt $commentsBefore) "comment trail on B grew: $commentsBefore -> $commentsAfter"

# cancel guards — only HRM may cancel
$c1 = WF-Action "EMP" "Leave Application" $L2 "Cancel"
$c2 = WF-Action "SUP" "Leave Application" $L2 "Cancel"
Check "S2-CANCEL-GUARD-EMP" ($c1.code -ne 200) "EMP cannot Cancel ($($c1.code)): $($c1.raw)"
Check "S2-CANCEL-GUARD-SUP" ($c2.code -ne 200) "Leave Approver cannot Cancel ($($c2.code)): $($c2.raw)"

$cc = WF-Action "HRM" "Leave Application" $L2 "Cancel"
Check "S2-CANCEL-HRM" ($cc.code -eq 200) "HRM cancels -> $(State-Of $L2)"
$att2b = Get-List "ADMIN" "Attendance" @(
    @("employee", "=", $EMP_HR), @("attendance_date", "=", $D2), @("docstatus", "<", 2)
) @("name")
Check "S2-ATT-GONE" ($att2b.Count -eq 0) "live Attendance $D2 removed after cancel ($($att2b.Count) left)"
$cellB2 = Attendance-Cell $APP_B
Check "S2-APPR-B-DROP" ($cellB2 -notmatch "\b25\b") "appraisal B drops the day after cancel: cell='$cellB2'"
$led2 = Get-List "ADMIN" "Leave Ledger Entry" @(
    @("transaction_name", "=", $L2), @("docstatus", "<", 2)
) @("name", "leaves", "is_cancelled")
$ledLive = @($led2 | Where-Object { -not $_.is_cancelled })
Check "S2-LEDGER-REVERSED" ($ledLive.Count -eq 0) "ledger for L2 reversed after cancel (live: $($ledLive.Count))"

# ------------------------------------------------------------------ L3: HRM self-approval (truth probe)
Write-Host "`n--- L3: HR Manager files + approves OWN leave (self-approval probe) ---"
$L3 = New-Leave "HRM" $HRM_HR $D4 $D4
Check "W13-CREATE" ($null -ne $L3) "HRM files own leave: $L3"
$wf = WF-Action "HRM" "Leave Application" $L3 "Submit for Approval" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L3 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L3 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L3 "Approve"
$l3d = Get-Doc "ADMIN" "Leave Application" $L3
Check "W13-TRUTH" ($wf.code -eq 200 -and $l3d.docstatus -eq 1) "TRUTH: HRM walked own leave to Approved alone -> $(State-Of $L3)  (REPORT to MG)"

# ------------------------------------------------------------------ L4: HRM does the paperwork (mirrored edges)
Write-Host "`n--- L4: HR Manager files + walks the whole chain for the employee ---"
$L4 = New-Leave "HRM" $EMP_HR $D5 $D5
Check "W7-CREATE" ($null -ne $L4) "HRM files for employee: $L4"
$wf = WF-Action "HRM" "Leave Application" $L4 "Submit for Approval" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L4 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L4 "Approve" | Out-Null
$wf = WF-Action "HRM" "Leave Application" $L4 "Approve"
Check "W7-PAPERWORK" ($wf.code -eq 200) "HRM walked the whole chain alone -> $(State-Of $L4)"

# ------------------------------------------------------------------ CLEANUP
Write-Host "`n--- cleanup (last) ---"
foreach ($n in @($L1, $L2, $L3, $L4)) { if ($n) { Remove-Doc "ADMIN" "Leave Application" $n | Out-Null } }
foreach ($n in @($APP_A, $APP_B)) { if ($n) { Remove-Doc "ADMIN" "Appraisal" $n | Out-Null } }
if ($log1.code -eq 200) { Remove-Doc "ADMIN" "Finger Log" $log1.data.message.name | Out-Null }
# attendance rows left cancelled by the leave removals must go too
$attLeft = Get-List "ADMIN" "Attendance" (, @(@("attendance_date", "in", $MYDATES))) @("name", "employee")
foreach ($a in $attLeft) {
    if ($a.employee -notin @($EMP_HR, $HRM_HR)) { continue }
    Remove-Doc "ADMIN" "Attendance" $a.name | Out-Null
}
$left = @(Get-List "ADMIN" "Leave Application" @(
    @("from_date", "in", $MYDATES)
) @("name", "employee") | Where-Object { $_.employee -in @($EMP_HR, $HRM_HR) }).Count
Check "CLEAN-LEAVES" ($left -eq 0) "no leftover leave applications ($left)"
$leftAtt = @(Get-List "ADMIN" "Attendance" @(
    @("attendance_date", "in", $MYDATES)
) @("name", "employee") | Where-Object { $_.employee -in @($EMP_HR, $HRM_HR) }).Count
Check "CLEAN-ATT" ($leftAtt -eq 0) "no leftover attendance rows ($leftAtt)"

Write-Host "`n=== S1 SUMMARY ==="
$pass = @($script:Results | Where-Object { $_.ok }).Count
$fail = @($script:Results | Where-Object { -not $_.ok }).Count
$script:Results | Where-Object { -not $_.ok } | ForEach-Object { Write-Host ("FAIL {0}: {1}" -f $_.id, $_.detail) }
Write-Host "`n$pass/$($script:Results.Count) passed"
