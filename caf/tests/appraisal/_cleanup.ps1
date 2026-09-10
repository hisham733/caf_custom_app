# CAF Appraisal test suite - shared reset
# ========================================
# Dot-sourced by every script that creates documents, so the suite is
# RE-RUNNABLE and ORDER-INDEPENDENT.
#
# ⚠️ Cancel first, then delete. A REST DELETE of a SUBMITTED document FAILS, so
# the first version left a Completed appraisal behind: the next run's T-A1 hit a
# duplicate, returned no document name, and every later assertion then built a
# URL from a null (405/404). Sixteen red lines, none of them a product fault.
#
# 🔴 T-21 - THE RESET OWNS A LIST, NOT THE SITE.
# The version before this one did:
#     GET /api/resource/Appraisal?limit_page_length=0          # EVERY appraisal
#     GET /api/resource/Employee Performance Feedback?...      # EVERY EPF
# and deleted the lot. That was true when written and stopped being true. Three
# CANCELLED appraisals belonging to real test users then sat on the site; they
# could not be deleted at all - a DELETE is blocked by ANY referrer row,
# cancelled ones included (quirks #63) - so every run warned "3 appraisal(s)
# survived the reset" and test_2_1_to_2_4 collapsed on a null index.
# run_all.ps1 has not completed since.
#
# It now removes only the fixtures the suite itself creates, declared below.
# Everything else on the site belongs to somebody and is left alone.


# --- the fixture manifest ----------------------------------------------------
# Every (employee, cycle) pair that any script in this folder inserts an
# Appraisal on - INCLUDING the ones that expect a 403, because a 403 that
# regresses to a 200 leaves a row behind and the next run must still start clean.
#
# Add a pair here in the same commit that adds the assertion. A fixture missing
# from this list is a fixture that survives the reset.
#
# 🔴 RE-POINTED 2026-09-10 (T-37) onto the REAL org tree. The cycle moved too:
# **2026-07**, because that is the month the new fixture employees actually have
# Finger Logs for (38 each, 2026-07-01 to 2026-08-09) and because it has ENDED,
# which BR6 requires before anything can be submitted for review.
$CAF_FIXTURE_APPRAISALS = @(
  @{ employee = "HR-EMP-00171"; cycle = "2026-07" },  # T-A1 (-> Completed) · T-J15 · probe_2_10bc scaffolding
  @{ employee = "HR-EMP-00171"; cycle = "2026-09" },  # T-F1  the CURRENT unfinished month (BR6)
  @{ employee = "HR-EMP-00171"; cycle = "2026-11" },  # T-F6  deleted inline; here as the backstop
  @{ employee = "HR-EMP-00171"; cycle = "2026-12" },  # T-I3  expects 403
  @{ employee = "HR-EMP-00009"; cycle = "2026-05" },  # T-E1  score toggle; deleted inline
  @{ employee = "HR-EMP-00009"; cycle = "2026-07" },  # T-B4 expects 200 · T-A6 expects 403
  @{ employee = "HR-EMP-00008"; cycle = "2026-07" },  # T-A7  expects 403 (A's own superior)
  @{ employee = "HR-EMP-00003"; cycle = "2026-07" },  # T-G1  employee with no Finger Logs; deleted inline
  @{ employee = "HR-EMP-00036"; cycle = "2026-07" }   # probe_2_10bc T-I3 expects 403
)

# An EPF carries no cycle, so it is matched on the marker every probe writes into
# `feedback`, AND on being about one of the employees above. Both spellings are
# live - "PROBE T-J8c/e" (probe_2_10bc) and "ZZPROBE" (test_2_5_to_2_8) - and
# since this is a substring test, "ZZPROBE" satisfies it too.
# ⚠️ Keep the marker in any new probe's feedback text, or its EPF stays forever.
$CAF_FIXTURE_EPF_MARKER = "PROBE"


# --- the org-tree precondition -----------------------------------------------
# Every assertion about who may appraise whom rests on three links. ✅ These are
# now links that exist in CAF's REAL org chart - the suite was re-pointed onto it
# on 2026-09-10 (T-37) rather than the chart being bent back to the suite:
#
#     C  Ow Yong Nin Geet  HR-EMP-00008      61 direct reports
#     └── A Nurulfarehah   HR-EMP-00036      9 direct reports, reports to C
#         └── B Siti Noratikah HR-EMP-00171  Employee role ONLY
#     D  Seow Zi Ying      HR-EMP-00009      under HR-EMP-00003 - a DISJOINT branch
#
# 🔴 WHY THE OLD FIXTURE DIED, so nobody rebuilds it. It was hand-made on
# 2026-08-05 (Rukaiya -> Kamrul -> Salsabila) and on 2026-09-01
# `caf.tests.workflow_gaps.data_align.fill_apply` replaced the whole tree with the
# real chart from sites/employeewithreport_to.csv - 81 employees written with
# `frappe.db.set_value`, so NO Version row records it (OD-26) and nothing
# announced it. Kamrul and Rukaiya ended up with zero reports, so T-A1 got a
# CORRECT 403 and sixteen later assertions failed on a null.
#
# ⚠️ `reports_to` is production-bound data (MG, 2026-09-01) and is not to be
# edited to suit a test. If these links break again, the tree moved for a real
# reason - re-point the suite again, do not restore the links.
#
# Say it once, in one line, instead of sixteen times in a language nobody can
# read. Same principle as chunk7_roster's C75-WEAK: a gate whose fixture has
# vanished must announce the fixture, not the symptom.
$CAF_ORG_FIXTURE = @(
  @{ employee = "HR-EMP-00036"; reports_to = "HR-EMP-00008"; role = "A (Nurulfarehah) reports to C (Ow Yong Nin Geet)" },
  @{ employee = "HR-EMP-00171"; reports_to = "HR-EMP-00036"; role = "B (Siti Noratikah) reports to A (Nurulfarehah)" },
  @{ employee = "HR-EMP-00009"; reports_to = "HR-EMP-00003"; role = "D (Seow Zi Ying) sits OUTSIDE A's branch" }
)


function Test-CafOrgFixture {
    param([Parameter(Mandatory = $true)] [scriptblock] $Request)

    $ids  = ($CAF_ORG_FIXTURE | ForEach-Object { """$($_.employee)""" }) -join ","
    $f    = [uri]::EscapeDataString("[[""name"",""in"",[$ids]]]")
    $cols = [uri]::EscapeDataString('["name","employee_name","reports_to"]')
    $rows = (& $Request "Admin" "GET" "/api/resource/Employee?limit_page_length=0&filters=$f&fields=$cols" $null).json.data

    $now = @{}
    foreach ($r in @($rows)) { $now[$r.name] = $r }

    $broken = @()
    foreach ($link in $CAF_ORG_FIXTURE) {
        $actual = $now[$link.employee]
        if (-not $actual) { $broken += "  $($link.employee) is not on this site at all"; continue }
        if ($actual.reports_to -ne $link.reports_to) {
            $broken += ("  {0} {1,-38} expected reports_to={2}, found {3}" -f `
                        $link.employee, $actual.employee_name, $link.reports_to,
                        $(if ($actual.reports_to) { $actual.reports_to } else { "<empty>" }))
        }
    }

    if ($broken.Count -eq 0) { return $true }

    Write-Host ""
    Write-Host "  🔴 ORG-TREE FIXTURE MISSING - the suite's premise is not on this site." -ForegroundColor Red
    $broken | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    Write-Host "  Documented in test_fixture_credentials.md §1 (built 2026-08-05)." -ForegroundColor Red
    Write-Host "  Overwritten 2026-09-01 by caf.tests.workflow_gaps.data_align.fill_apply," -ForegroundColor Red
    Write-Host "  which writes CAF's REAL org chart over all 81 employees via db.set_value" -ForegroundColor Red
    Write-Host "  (no Version row, OD-26). Restoring these links by hand WILL be undone the" -ForegroundColor Red
    Write-Host "  next time that script runs - which is how this happened. See T-21." -ForegroundColor Red
    Write-Host ""
    return $false
}


function Reset-CafTestData {
    param(
        [Parameter(Mandatory = $true)] [scriptblock] $Request,
        [switch] $IncludeProbeEmployees
    )

    $fixtureEmployees = @($CAF_FIXTURE_APPRAISALS | ForEach-Object { $_.employee } | Sort-Object -Unique)
    $summary = @{ appraisals = 0; epfs = 0; employees = 0 }
    $stuck   = @()

    function _IsFixturePair($employee, $cycle) {
        foreach ($f in $CAF_FIXTURE_APPRAISALS) {
            if ($f.employee -eq $employee -and $f.cycle -eq $cycle) { return $true }
        }
        return $false
    }

    # cancel only what is actually submitted - a PUT docstatus=2 on a DRAFT is
    # refused, and the old code swallowed that refusal, which made a real
    # "cannot cancel" indistinguishable from a no-op
    function _RemoveDoc($Req, $doctype, $name, $docstatus) {
        $dt = [uri]::EscapeDataString($doctype)
        if ([int]$docstatus -eq 1) {
            & $Req "Admin" "PUT" "/api/resource/$dt/$name" '{"docstatus":2}' | Out-Null
        }
        $d = & $Req "Admin" "DELETE" "/api/resource/$dt/$name" $null
        if ($d.code -eq 200 -or $d.code -eq 202) { return $null }
        return "HTTP $($d.code) $($d.err)"
    }

    $empIn   = [uri]::EscapeDataString("[[""employee"",""in"",[" + (($fixtureEmployees | ForEach-Object { """$_""" }) -join ",") + "]]]")
    $aprCols = [uri]::EscapeDataString('["name","employee","appraisal_cycle","docstatus","workflow_state"]')
    $epfCols = [uri]::EscapeDataString('["name","employee","docstatus","feedback"]')

    # EPFs first: an EPF's `appraisal` link blocks the parent's DELETE even when
    # the EPF itself is cancelled (quirks #63)
    $epfs = (& $Request "Admin" "GET" "/api/resource/Employee%20Performance%20Feedback?limit_page_length=0&filters=$empIn&fields=$epfCols" $null).json.data
    $myEpfs = @(@($epfs) | Where-Object { "$($_.feedback)" -like "*$CAF_FIXTURE_EPF_MARKER*" })
    foreach ($e in $myEpfs) {
        $why = _RemoveDoc $Request "Employee Performance Feedback" $e.name $e.docstatus
        if ($why) { $stuck += "  EPF       $($e.name)  $why" } else { $summary.epfs++ }
    }

    $apr = (& $Request "Admin" "GET" "/api/resource/Appraisal?limit_page_length=0&filters=$empIn&fields=$aprCols" $null).json.data
    $myApr = @(@($apr) | Where-Object { _IsFixturePair $_.employee $_.appraisal_cycle })
    foreach ($a in $myApr) {
        $why = _RemoveDoc $Request "Appraisal" $a.name $a.docstatus
        if ($why) { $stuck += "  Appraisal $($a.name)  $($a.employee) $($a.appraisal_cycle) $($a.workflow_state)  $why" }
        else      { $summary.appraisals++ }
    }

    if ($IncludeProbeEmployees) {
        # ZZ Probe OrgRoot counts as a THIRD org root and breaks the D53
        # invariant the data-quality script checks
        $emps = (& $Request "Admin" "GET" "/api/resource/Employee?filters=%5B%5B%22first_name%22%2C%22like%22%2C%22ZZ%20Probe%25%22%5D%5D&limit_page_length=0" $null).json.data
        foreach ($p in @($emps)) {
            & $Request "Admin" "DELETE" "/api/resource/Employee/$($p.name)" $null | Out-Null
            $summary.employees++
        }
    }

    # confirm BY MEANING: the FIXTURE pairs are clear. Counting every Appraisal
    # on the site is exactly what produced the old "3 appraisal(s) survived"
    # warning - about three rows this suite never owned.
    $after = (& $Request "Admin" "GET" "/api/resource/Appraisal?limit_page_length=0&filters=$empIn&fields=$aprCols" $null).json.data
    $left  = @(@($after) | Where-Object { _IsFixturePair $_.employee $_.appraisal_cycle })

    "  reset: removed $($summary.appraisals) appraisal(s), $($summary.epfs) EPF(s), $($summary.employees) probe employee(s); $($left.Count) fixture appraisal(s) remain"
    if ($left.Count -gt 0) {
        Write-Host "  WARNING: $($left.Count) FIXTURE appraisal(s) survived the reset - later assertions will fail on them, not on the product." -ForegroundColor Yellow
        $stuck | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
        Write-Host "  A DELETE is blocked by ANY referrer row, cancelled ones included (quirks #63)." -ForegroundColor Yellow
        Write-Host "  Find the referrer and remove it; do not widen this reset to take the site." -ForegroundColor Yellow
    }
}
