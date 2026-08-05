# CAF Appraisal - run the whole suite
# ====================================
# Executable form of CAF_appraisal_test_plan.md sections 2.1-2.10.
# Section 3 is a browser checklist and is not scripted - see README.md.

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$scripts = @(
  "test_2_1_to_2_4.ps1",   # supervisor flow, HR flow, rejection loop, subtree
  "test_2_5_to_2_8.ps1",   # score toggle, BR6, edge cases, reports_to rules
  "probe_2_10a.ps1",       # HR Settings permlevel
  "probe_2_10b.ps1",       # Finger Log restriction
  "probe_2_10bc.ps1",      # EPF permlevel, KRA permissions, workflow present
  "probe_2_10e.ps1"        # cross-checks: did anything leak?
)

$all = @()
foreach ($s in $scripts) {
  Write-Host ""
  Write-Host ("#" * 70)
  Write-Host "# $s"
  Write-Host ("#" * 70)
  $out = & (Join-Path $here $s) 2>&1
  $out | ForEach-Object { Write-Host $_ }
  $all += ($out | Out-String -Stream | Select-String -Pattern "^T-\S+\s+(PASS|FAIL)")
}

Write-Host ""
Write-Host ("=" * 70)
$pass = @($all | Where-Object { $_ -match "\sPASS\s" }).Count
$fail = @($all | Where-Object { $_ -match "\sFAIL\s" }).Count
Write-Host "TOTAL: $pass passed, $fail failed"
if ($fail -gt 0) {
  Write-Host ""
  Write-Host "Failures:" -ForegroundColor Yellow
  $all | Where-Object { $_ -match "\sFAIL\s" } | ForEach-Object { Write-Host "  $_" }
  Write-Host ""
  Write-Host "Before assuming a product bug, check README.md - stale fixtures produce" -ForegroundColor Yellow
  Write-Host "most failures. 409 = duplicate, 405 = URL built from a null, 417 = a" -ForegroundColor Yellow
  Write-Host "ValidationError carrying a real explanation." -ForegroundColor Yellow
}
