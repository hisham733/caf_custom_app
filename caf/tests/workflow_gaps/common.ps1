# Shared helpers for the workflow-gaps runners. NEW file; nothing existing touched.
# Dot-source this from each runner after setting $Creds.

$ErrorActionPreference = "Stop"
$Base = "http://development.localhost:8000"
$script:Results = @()

function Check([string]$tid, [bool]$ok, [string]$detail) {
    $script:Results += [pscustomobject]@{ id = $tid; ok = $ok; detail = $detail }
    Write-Host ("{0} {1,-22} {2}" -f ($(if ($ok) { "PASS" } else { "FAIL" }), $tid, $detail))
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
    $safeDt = $Dt.Replace(" ", "%20")
    $r = Invoke-Call $Role "GET" "/api/resource/$safeDt/$Name" $null
    if ($r.code -eq 200) { return $r.data.data } else { return $null }
}

# filters must be an array-of-arrays; single-filter calls use the leading comma
# (,@(@(..))) — PowerShell flattens @( @(..) ) and corrupts the JSON body.
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

function Insert-Doc([string]$Role, $Doc) {
    return Invoke-Call $Role "POST" "/api/method/frappe.client.insert" @{ doc = $Doc }
}

function Submit-Doc([string]$Role, [string]$Dt, [string]$Name) {
    return Invoke-Call $Role "PUT" "/api/resource/$Dt/$Name" @{ docstatus = 1 }
}

function Cancel-Doc([string]$Role, [string]$Dt, [string]$Name) {
    $safeDt = $Dt.Replace(" ", "%20")
    return Invoke-Call $Role "PUT" "/api/resource/$safeDt/$Name" @{ docstatus = 2 }
}

function Remove-Doc([string]$Role, [string]$Dt, [string]$Name) {
    $doc = Get-Doc $Role $Dt $Name
    if ($null -eq $doc) { return }
    if ($doc.docstatus -eq 1) { Cancel-Doc $Role $Dt $Name | Out-Null }
    $safeDt = $Dt.Replace(" ", "%20")
    Invoke-Call $Role "DELETE" "/api/resource/$safeDt/$Name" $null | Out-Null
}

function Summary() {
    Write-Host "`n=== SUMMARY ==="
    $pass = @($script:Results | Where-Object { $_.ok }).Count
    $fail = @($script:Results | Where-Object { -not $_.ok }).Count
    $script:Results | Where-Object { -not $_.ok } | ForEach-Object { Write-Host ("FAIL {0}: {1}" -f $_.id, $_.detail) }
    Write-Host "`n$pass/$($script:Results.Count) passed"
}

# Triple-scoped cleanup: ONLY rows owned by this session's fixture users,
# created today, on the suite's own dates. Real data (other owners) is never
# touched — MG boundary: core data (Employee/User) must not change; test
# records are disposable but must not be deleted by accident.
$SessionUsers = @("mohd@caffood.com", "mursyid@caffood.com", "hr.manager.test@caffood.com")

function Remove-MyDocs([string]$Dt, [string]$DateField, [array]$Dates) {
    $rows = Get-List "ADMIN" $Dt @(
        @($DateField, "in", $Dates),
        @("owner", "in", $SessionUsers),
        @("creation", ">=", "2026-08-14")
    ) @("name")
    foreach ($r in $rows) { Remove-Doc "ADMIN" $Dt $r.name | Out-Null }
}

function Count-MyDocs([string]$Dt, [string]$DateField, [array]$Dates) {
    $rows = Get-List "ADMIN" $Dt @(
        @($DateField, "in", $Dates),
        @("owner", "in", $SessionUsers),
        @("creation", ">=", "2026-08-14")
    ) @("name")
    return @($rows).Count
}
