# S11 — Ingress import + the FBR39 / Route B backdating routes, walked as REAL
# ROLES over REST. MG's test request, 2026-08-17.
#
# Why REST and not bench execute: as Administrator every permission assertion
# passes and means nothing (protocol §C1). The three things MG asked to cover are
# all role-shaped — who may import, who may approve, who may cancel — so they have
# to be exercised through the API as the actual users.
#
# Part A  the new Ingress doctypes, per role
# Part B  HR away 3 days -> one catch-up import (and today refused, FBR43)
# Part C  FBR39 Route A (in place) vs Route B (cancel -> amend -> re-submit)
#
# Fixture (shared with S1):
#   EMP      mohd@caffood.com       HR-EMP-00013  (Employee)
#   SUP      too@caffood.com        HR-EMP-00003  (mohd's supervisor + leave approver)
#   HRM      hr.manager.test@       (HR Manager)
#   ADMIN    Administrator          (setup/cleanup only)
#
# Run:  pwsh -NoProfile -ExecutionPolicy Bypass -File run_ingress_and_backdate.ps1

$ErrorActionPreference = "Stop"
$Base = "http://development.localhost:8000"
. "C:\Users\mgowy\OneDrive\Desktop\CAF MG files\MG Projects\caf_custom_app\MG_custom_app_files\apprisal_doctype_project\workflow_gaps_credentials.ps1"

$EMP_HR  = "HR-EMP-00013"
$CYCLE   = "2026-06"          # an ENDED month — BR6/D31 refuses unfinished ones
$LTYPE   = "Leave Without Pay"
$LV_A    = "2026-06-11"       # Route A target (inside window)
$LV_B    = "2026-06-12"       # Route B target (window aged shut)
$IMPORT_EMP = "HR-EMP-00006"  # HR-approved test employee (Chen), device 442

$script:Results = @()
$script:Skipped = @()
function Check([string]$tid, [bool]$ok, [string]$detail) {
    $script:Results += [pscustomobject]@{ id = $tid; ok = $ok; detail = $detail }
    Write-Host ("{0} {1,-26} {2}" -f ($(if ($ok) { "PASS" } else { "FAIL" }), $tid, $detail))
}
# 🔴 Part B needs the Ingress machine, and that machine is a DESKTOP THAT SLEEPS
# on inactivity — it dropped off three times on 2026-08-18 alone. A suite that
# goes red because somebody's PC went idle is a suite people stop reading, and the
# redness says nothing about the code. Skips are counted separately and printed
# loudly; they are never treated as passes.
function Skip([string]$tid, [string]$why) {
    $script:Skipped += [pscustomobject]@{ id = $tid; why = $why }
    Write-Host ("SKIP {0,-26} {1}" -f $tid, $why)
}

function Invoke-Call([string]$Role, [string]$Method, [string]$Path, $Body) {
    $h = @{ Authorization = $Creds[$Role] }
    $b = $null
    if ($null -ne $Body) { $h["Content-Type"] = "application/json"; $b = $Body | ConvertTo-Json -Depth 6 -Compress }
    try {
        $r = Invoke-WebRequest -Uri ($Base + $Path) -Method $Method -Headers $h -Body $b -UseBasicParsing -TimeoutSec 180
        $p = $null; if ($r.Content) { try { $p = $r.Content | ConvertFrom-Json } catch { $p = $r.Content } }
        return [pscustomobject]@{ code = 200; data = $p; raw = $r.Content }
    } catch {
        $code = 0; try { $code = [int]$_.Exception.Response.StatusCode } catch {}
        $err = ""
        if ($_.ErrorDetails.Message) {
            try { $err = ($_.ErrorDetails.Message | ConvertFrom-Json)._server_messages } catch {}
            if (-not $err) { try { $err = ($_.ErrorDetails.Message | ConvertFrom-Json).exception } catch { $err = $_.ErrorDetails.Message } }
        }
        if ($err -isnot [string]) { $err = "$err" }
        return [pscustomobject]@{ code = $code; data = $null; raw = $err }
    }
}
function WF-Action([string]$Role, [string]$Dt, [string]$Name, [string]$Action) {
    return Invoke-Call $Role "POST" "/api/method/frappe.model.workflow.apply_workflow" @{
        doc = @{ doctype = $Dt; name = $Name }; action = $Action }
}
function Run-Method([string]$Role, [string]$Dt, [string]$Name, [string]$Method) {
    return Invoke-Call $Role "POST" "/api/method/run_doc_method" @{ dt = $Dt; dn = $Name; method = $Method }
}
# A Leave Application reaches docstatus 1 only at the END of a FOUR-step workflow
# (Chunk 6b): Draft → Pending Supervisor → Pending HR Manager → Pending Final
# Approval → Approved. `status` is workflow-driven, so inserting status="Approved"
# and calling submit() is refused with "Only Leave Applications with status
# 'Approved' and 'Rejected' can be submitted" — the first version of this suite
# did exactly that and mistook the refusal for FBR39 biting.
#
# FBR39 lives in `before_submit`, so it fires on the LAST transition. Returning
# every step lets the caller see which one refused rather than guessing.
#
# ⚠️ It RESUMES from wherever the document currently sits rather than replaying
# from Draft. When FBR39 refuses, the refusal happens on the last transition, so
# the application is left parked at "Pending Final Approval" — replaying "Submit
# for Approval" against that state is an invalid transition, and the 417 that comes
# back looks exactly like FBR39 still biting. That cost a false failure on
# C10 before it was understood: after HR cancels the appraisal she does not
# re-file the leave, she simply presses Approve again.
function Leave-ToApproved([string]$Name) {
    $next = @{
        "Draft"                  = @{ role = "SUP"; action = "Submit for Approval" }
        "Pending Supervisor"     = @{ role = "SUP"; action = "Approve" }
        "Pending HR Manager"     = @{ role = "HRM"; action = "Approve" }
        "Pending Final Approval" = @{ role = "HRM"; action = "Approve" }
    }
    $last = [pscustomobject]@{ code = 200; data = $null; raw = "already approved" }
    for ($i = 0; $i -lt 6; $i++) {
        $d = (Invoke-Call ADMIN "GET" "/api/resource/Leave Application/$Name" $null).data.data
        if (-not $d) { break }
        if ($d.workflow_state -eq "Approved" -or $d.docstatus -eq 1) { return $last }
        $step = $next[$d.workflow_state]
        if (-not $step) {
            return [pscustomobject]@{ code = 0; data = $null
                raw = "stuck in unexpected state '$($d.workflow_state)'" }
        }
        $last = WF-Action $step.role "Leave Application" $Name $step.action
        if ($last.code -ne 200) { return $last }
    }
    return $last
}

function Ingress-Import([string]$Role, $From, $To, $Emps, [int]$Submit) {
    $b = @{ from_date = $From; to_date = $To; submit = $Submit; purpose = "Test" }
    if ($Emps) { $b["employees"] = $Emps }
    return Invoke-Call $Role "POST" "/api/method/caf.caf.doctype.ingress_import_batch.ingress_import_batch.run_manual_import" $b
}

Write-Host "`n=== S11 — Ingress import + backdating routes, as real roles ===`n"

# ── cleanup ─────────────────────────────────────────────────────────────────
Write-Host "-- cleanup (first) --"
foreach ($d in @($LV_A, $LV_B)) {
    foreach ($la in @((Invoke-Call ADMIN "POST" "/api/method/frappe.client.get_list" @{
            doctype = "Leave Application"; filters = @(@("employee","=",$EMP_HR),@("from_date","=",$d))
            fields = @("name","docstatus") }).data.message)) {
        if ($la) {
            if ($la.docstatus -eq 1) { Run-Method ADMIN "Leave Application" $la.name "cancel" | Out-Null }
            Invoke-Call ADMIN "POST" "/api/method/frappe.client.delete" @{ doctype = "Leave Application"; name = $la.name } | Out-Null
        }
    }
}
foreach ($ap in @((Invoke-Call ADMIN "POST" "/api/method/frappe.client.get_list" @{
        doctype = "Appraisal"; filters = @(@("employee","=",$EMP_HR),@("appraisal_cycle","=",$CYCLE))
        fields = @("name","docstatus") }).data.message)) {
    if ($ap) {
        if ($ap.docstatus -eq 1) { Run-Method ADMIN "Appraisal" $ap.name "cancel" | Out-Null }
        Invoke-Call ADMIN "POST" "/api/method/frappe.client.delete" @{ doctype = "Appraisal"; name = $ap.name } | Out-Null
    }
}
Write-Host ""

# ═══════════════════════════════ PART A — the Ingress doctypes, per role ═════
$r = Invoke-Call EMP "GET" "/api/resource/Ingress%20Import%20Batch" $null
Check "A1-EMP-NO-BATCH-LIST" ($r.code -eq 403) `
    "a plain Employee is refused the Ingress Import Batch list (HTTP $($r.code)). Import history names other people's attendance — it is not employee-readable"

$r = Invoke-Call EMP "GET" "/api/resource/Ingress%20Sync%20Settings/Ingress%20Sync%20Settings" $null
Check "A2-EMP-NO-SETTINGS" ($r.code -eq 403) `
    "a plain Employee is refused Ingress Sync Settings (HTTP $($r.code)) — it holds the machine's database password"

$r = Ingress-Import EMP "2026-06-10" "2026-06-10" @($IMPORT_EMP) 0
Check "A3-EMP-CANNOT-IMPORT" ($r.code -ne 200) `
    "a plain Employee cannot run an import (HTTP $($r.code)) — the endpoint is gated, not just the button hidden"

$r = Ingress-Import SUP "2026-06-10" "2026-06-10" @($IMPORT_EMP) 0
Check "A4-SUPERVISOR-CANNOT-IMPORT" ($r.code -ne 200) `
    "a SUPERVISOR is also refused (HTTP $($r.code)). Being senior is not the same as being HR — importing attendance for the whole company is an HR act"

$r = Invoke-Call HRM "GET" "/api/resource/Ingress%20Sync%20Settings/Ingress%20Sync%20Settings" $null
$pwMasked = $true
if ($r.code -eq 200 -and $r.data.data.db_password) { $pwMasked = ($r.data.data.db_password -notmatch '^[A-Za-z0-9]{4,}$' -or $r.data.data.db_password -match '^\*+$') }
Check "A5-HRM-READS-SETTINGS" ($r.code -eq 200 -and $pwMasked) `
    "HR Manager reads the settings (HTTP $($r.code)) and the password comes back masked as '$($r.data.data.db_password)' — readable enough to operate, not enough to leak"

# ═══════════════════════════════ PART B — HR away 3 days, one catch-up ═══════
$today     = (Get-Date).ToString("yyyy-MM-dd")
$yesterday = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
$start3    = (Get-Date).AddDays(-3).ToString("yyyy-MM-dd")

# Is the machine awake? Asked once, via the settings page's own connection test.
$probe = Invoke-Call ADMIN "GET" "/api/method/caf.caf.doctype.ingress_sync_settings.ingress_sync_settings.test_connection" $null
$LIVE = ($probe.code -eq 200 -and $probe.data.message.ok -eq $true)
if (-not $LIVE) { Write-Host "`n⚠️  Ingress machine unreachable — Part B will SKIP.`n" }

$r = Ingress-Import HRM $today $today $null 0
Check "B1-TODAY-REFUSED" ($r.code -ne 200 -and $r.raw -match "incomplete") `
    "HR Manager is refused TODAY (HTTP $($r.code)) because the punches are half written — FBR43. Refused, not silently trimmed. (Checked BEFORE the machine is touched, so it holds whether Natalie is awake or not)"

if (-not $LIVE) {
    Skip "B2-CATCHUP-3-DAYS"    "needs the Ingress machine; it is asleep or off"
    Skip "B3-CATCHUP-IDEMPOTENT" "needs the Ingress machine; it is asleep or off"
    Skip "B5-HRM-REVERTS"        "needs a real batch to revert"
    $r = Invoke-Call EMP "POST" "/api/method/caf.caf.doctype.ingress_import_batch.ingress_import_batch.revert" @{ batch_name = "INGB-NONE"; force = 1 }
    Check "B4-EMP-CANNOT-REVERT" ($r.code -ne 200) `
        "a plain Employee cannot revert an import batch (HTTP $($r.code)) — the role gate is checked before the batch is even looked up, so this holds with the machine off"
} else {

$r = Ingress-Import HRM $start3 $yesterday $null 0
$b1 = $null
if ($r.code -eq 200) { $b1 = $r.data.message.batch }
$c = $r.data.message.counts
Check "B2-CATCHUP-3-DAYS" ($r.code -eq 200 -and $c.failed -eq 0) `
    "HR back from 3 days off imports $start3..$yesterday for EVERY employee in ONE call as herself: batch $b1, created=$($c.created) held=$($c.held) already=$($c.already_present) failed=$($c.failed)"

$r2 = Ingress-Import HRM $start3 $yesterday $null 0
$b2 = $null; if ($r2.code -eq 200) { $b2 = $r2.data.message.batch }
$c2 = $r2.data.message.counts
Check "B3-CATCHUP-IDEMPOTENT" ($r2.code -eq 200 -and $c2.created -eq 0) `
    "clicking the same catch-up again created $($c2.created), already_present=$($c2.already_present) — HR unsure whether she already imported can just click again, which is what she will do"

$r = Invoke-Call EMP "POST" "/api/method/caf.caf.doctype.ingress_import_batch.ingress_import_batch.revert" @{ batch_name = $b1; force = 1 }
Check "B4-EMP-CANNOT-REVERT" ($r.code -ne 200) `
    "a plain Employee cannot revert an import batch (HTTP $($r.code)) — revert deletes Finger Logs and cancels Attendance"

$removed = 0
foreach ($bn in @($b1, $b2)) {
    if ($bn) {
        $rv = Invoke-Call HRM "POST" "/api/method/caf.caf.doctype.ingress_import_batch.ingress_import_batch.revert" @{ batch_name = $bn; force = 1 }
        if ($rv.code -eq 200) { $removed += [int]$rv.data.message.removed }
        Invoke-Call ADMIN "POST" "/api/method/frappe.client.delete" @{ doctype = "Ingress Import Batch"; name = $bn } | Out-Null
    }
}
Check "B5-HRM-REVERTS" ($removed -gt 0) `
    "HR Manager reverted her own test batches, $removed Finger Log(s) removed — a whole-company 3-day import has to be as removable as a one-row one or nobody will risk it"
}   # end of the LIVE-only block

# ═══════════════════════════════ PART C — FBR39 Route A vs Route B ══════════
# supervisor builds and sends; HR approves. That IS the submit (docstatus 0->1).
$ins = Invoke-Call SUP "POST" "/api/method/frappe.client.insert" @{
    doc = @{ doctype = "Appraisal"; employee = $EMP_HR; appraisal_cycle = $CYCLE } }
$APR = $null; if ($ins.code -eq 200) { $APR = $ins.data.message.name }
Check "C1-SUP-CREATES-APPRAISAL" ($null -ne $APR) `
    "the SUPERVISOR creates the $CYCLE appraisal as herself ($APR) — not Administrator, so validate_supervisor actually ran"

WF-Action SUP "Appraisal" $APR "Submit for Review" | Out-Null
$st = (Invoke-Call ADMIN "GET" "/api/resource/Appraisal/$APR" $null).data.data
Check "C2-STILL-DRAFT-AFTER-SUP" ($st.workflow_state -eq "Pending HR Review" -and $st.docstatus -eq 0) `
    "after the supervisor sends it: state=$($st.workflow_state) docstatus=$($st.docstatus). 🔴 FBR46 — the supervisor's action does NOT start FBR39's clock, because the document is still a draft"

WF-Action HRM "Appraisal" $APR "Approve" | Out-Null
$st = (Invoke-Call ADMIN "GET" "/api/resource/Appraisal/$APR" $null).data.data
Check "C3-HRM-APPROVAL-SUBMITS" ($st.docstatus -eq 1) `
    "HR Manager's Approve is what submits it (docstatus=$($st.docstatus)) — so FBR39's month runs from HERE, per FBR46"

# ── Route A: a backdated leave INSIDE the window ────────────────────────────
$ins = Invoke-Call EMP "POST" "/api/method/frappe.client.insert" @{
    doc = @{ doctype = "Leave Application"; employee = $EMP_HR; leave_type = $LTYPE
             from_date = $LV_A; to_date = $LV_A; status = "Approved"
             leave_approver = "too@caffood.com" } }
$LA_A = $null; if ($ins.code -eq 200) { $LA_A = $ins.data.message.name }
$sub = Leave-ToApproved $LA_A
Check "C4-ROUTE-A-ALLOWED" ($sub.code -eq 200) `
    "inside the window, the approver submits a backdated $LV_A leave and it is ACCEPTED (HTTP $($sub.code)) — the submitted appraisal is patched in place, no cancel needed. This is Route A"

# ── age the window shut, then Route B ──────────────────────────────────────
$aged = Invoke-Call ADMIN "POST" "/api/method/caf.tests.workflow_gaps.test_support.age_appraisal_submission" @{ appraisal = $APR; months = 3 }
$state = (Invoke-Call ADMIN "POST" "/api/method/caf.tests.workflow_gaps.test_support.fbr39_state" @{ appraisal = $APR }).data.message
Check "C5-WINDOW-NOW-CLOSED" ($state.closed -eq $true) `
    "the submit Version was aged to $($state.submitted_on), so FBR39 now reports closed=$($state.closed) with deadline $($state.deadline) — the October behaviour, tested in August"

$ins = Invoke-Call EMP "POST" "/api/method/frappe.client.insert" @{
    doc = @{ doctype = "Leave Application"; employee = $EMP_HR; leave_type = $LTYPE
             from_date = $LV_B; to_date = $LV_B; status = "Approved"
             leave_approver = "too@caffood.com" } }
$LA_B = $null; if ($ins.code -eq 200) { $LA_B = $ins.data.message.name }
$sub = Leave-ToApproved $LA_B
Check "C6-FBR39-REFUSES" ($sub.code -ne 200 -and $sub.raw -match "window has closed") `
    "past the window the same approver is REFUSED (HTTP $($sub.code)) — FBR39 bites, and it bites the approver, not the employee"

Check "C7-REFUSAL-NAMES-THE-WAY-OUT" ($sub.raw -match "cancels appraisal" -and $sub.raw -match "no time limit") `
    "and the refusal spells out the remedy — cancel, approve, amend, re-submit. A refusal that hides its remedy gets worked around rather than obeyed"

$r = Run-Method EMP "Appraisal" $APR "cancel"
Check "C8-EMP-CANNOT-CANCEL" ($r.code -ne 200) `
    "a plain Employee cannot cancel the appraisal to unblock their own leave (HTTP $($r.code)) — Route B is an HR act"

$r = Run-Method HRM "Appraisal" $APR "cancel"
$st = (Invoke-Call ADMIN "GET" "/api/resource/Appraisal/$APR" $null).data.data
Check "C9-HRM-CANCELS" ($st.docstatus -eq 2) `
    "HR Manager cancels the appraisal (docstatus=$($st.docstatus)) — step 1 of Route B"

$sub = Leave-ToApproved $LA_B
Check "C10-ROUTE-B-UNBLOCKS" ($sub.code -eq 200) `
    "🔴 with the appraisal cancelled the SAME refused leave now submits (HTTP $($sub.code)) — FBR47. No time limit anywhere on this route; the window only ever governed the in-place patch"

# The SUPERVISOR raises the amendment, mirroring C1 — an appraisal belongs to the
# supervisor who writes it, and validate_supervisor runs on insert.
$am = Invoke-Call SUP "POST" "/api/method/frappe.client.insert" @{
    doc = @{ doctype = "Appraisal"; employee = $EMP_HR; appraisal_cycle = $CYCLE
             amended_from = $APR; workflow_state = "Draft" } }
$APR2 = $null; if ($am.code -eq 200) { $APR2 = $am.data.message.name }
Check "C11-AMEND-NOT-DUPLICATE" ($null -ne $APR2) `
    "the amendment inserts for the same employee and cycle ($APR2) — stock validate_duplicate() carries docstatus != 2, so the cancelled one is invisible to it. This was the single thing that could have blocked Route B ($($am.raw))"

$w1 = WF-Action SUP "Appraisal" $APR2 "Submit for Review"
$w2 = WF-Action HRM "Appraisal" $APR2 "Approve"
$st2 = (Invoke-Call ADMIN "GET" "/api/resource/Appraisal/$APR2" $null).data.data
Check "C12-AMENDMENT-RESUBMITS" ($st2.docstatus -eq 1) `
    "the amendment travels the workflow again and re-submits (docstatus=$($st2.docstatus), state=$($st2.workflow_state)) — the month closes with the corrected leave counted. Route B proven end to end, as real roles [send=$($w1.code) approve=$($w2.code)]"

# ── cleanup ────────────────────────────────────────────────────────────────
Write-Host "`n-- cleanup (last) --"
foreach ($la in @($LA_A, $LA_B)) {
    if ($la) {
        Run-Method ADMIN "Leave Application" $la "cancel" | Out-Null
        Invoke-Call ADMIN "POST" "/api/method/frappe.client.delete" @{ doctype = "Leave Application"; name = $la } | Out-Null
    }
}
foreach ($ap in @($APR2, $APR)) {
    if ($ap) {
        Run-Method ADMIN "Appraisal" $ap "cancel" | Out-Null
        Invoke-Call ADMIN "POST" "/api/method/frappe.client.delete" @{ doctype = "Appraisal"; name = $ap } | Out-Null
    }
}

$pass = @($script:Results | Where-Object { $_.ok }).Count
$fail = @($script:Results | Where-Object { -not $_.ok })
$skipLine = if ($script:Skipped.Count) { " · $($script:Skipped.Count) skipped" } else { "" }
Write-Host "`n$pass/$($script:Results.Count) passed$skipLine"
if ($script:Skipped.Count) {
    Write-Host "⚠️  Skipped rows are NOT passes — re-run with the Ingress machine awake for a full gate."
}
if ($fail.Count) { Write-Host ("FAILED: " + (($fail | ForEach-Object { $_.id }) -join ", ")) ; exit 1 }
exit 0
