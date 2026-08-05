# CAF Appraisal test suite - shared reset
# ========================================
# Dot-sourced by every script that creates documents, so the suite is
# RE-RUNNABLE and ORDER-INDEPENDENT.
#
# ⚠️ The reason this is a shared file rather than three copies: the first
# version deleted without cancelling, and a REST DELETE of a SUBMITTED document
# FAILS. A Completed appraisal therefore survived every "cleanup", and the next
# run collapsed - T-A1 hit a duplicate, returned no document name, and every
# later assertion built a URL from a null (405/404). Sixteen red lines, none of
# them a product fault.
#
# Cancel first, then delete. Same rule the Python cleanup scripts already follow.

function Reset-CafTestData {
    param(
        [Parameter(Mandatory = $true)] [scriptblock] $Request,
        [switch] $IncludeProbeEmployees
    )

    $summary = @{ appraisals = 0; epfs = 0; employees = 0 }

    # EPFs first - they can reference an appraisal
    $epfs = (& $Request "Admin" "GET" "/api/resource/Employee%20Performance%20Feedback?limit_page_length=0" $null).json.data
    foreach ($e in @($epfs)) {
        & $Request "Admin" "PUT" "/api/resource/Employee%20Performance%20Feedback/$($e.name)" '{"docstatus":2}' | Out-Null
        & $Request "Admin" "DELETE" "/api/resource/Employee%20Performance%20Feedback/$($e.name)" $null | Out-Null
        $summary.epfs++
    }

    $apr = (& $Request "Admin" "GET" "/api/resource/Appraisal?limit_page_length=0" $null).json.data
    foreach ($a in @($apr)) {
        # a Completed appraisal is docstatus 1 - cancel before deleting, or the
        # DELETE silently fails and the record survives
        & $Request "Admin" "PUT" "/api/resource/Appraisal/$($a.name)" '{"docstatus":2}' | Out-Null
        & $Request "Admin" "DELETE" "/api/resource/Appraisal/$($a.name)" $null | Out-Null
        $summary.appraisals++
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

    # confirm, rather than assume - a survivor here poisons the whole run
    $left = @((& $Request "Admin" "GET" "/api/resource/Appraisal?limit_page_length=0" $null).json.data).Count
    "  reset: removed $($summary.appraisals) appraisal(s), $($summary.epfs) EPF(s), $($summary.employees) probe employee(s); $left appraisal(s) remain"
    if ($left -gt 0) {
        Write-Host "  WARNING: $left appraisal(s) survived the reset - later assertions may fail on them, not on the product." -ForegroundColor Yellow
    }
}
