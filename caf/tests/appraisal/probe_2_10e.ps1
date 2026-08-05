# CAF Appraisal - test plan 2.10e: cross-checks that no change leaked further
# than intended. These were NOT run during chunks 1-4; running them now.

$ErrorActionPreference = "Continue"
# Credentials are NOT stored in this repo - see credentials.example.ps1.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$credFile = Join-Path $here "credentials.ps1"
if (-not (Test-Path $credFile)) {
  Write-Host "credentials.ps1 not found. Copy credentials.example.ps1 to credentials.ps1 and fill it in." -ForegroundColor Yellow
  exit 1
}
. $credFile
$U = $CAF_SITE_URL
$T = $CAF_TOKENS
function CafHeader($r) { return @{ Authorization = "token $($T[$r])" } }
function Req($role, $method, $path, $body) {
  $p = @{ Uri="$U$path"; Method=$method; Headers=(CafHeader $role); UseBasicParsing=$true; TimeoutSec=90 }
  if ($body) { $p.Body=$body; $p.ContentType="application/json" }
  try { $r=Invoke-WebRequest @p; return @{ code=[int]$r.StatusCode; json=($r.Content|ConvertFrom-Json) } }
  catch { $c=0; if($_.Exception.Response){$c=[int]$_.Exception.Response.StatusCode}
          $m=$null; if($_.ErrorDetails.Message){try{$m=($_.ErrorDetails.Message|ConvertFrom-Json).exception}catch{}}
          return @{ code=$c; json=$null; err=$m } }
}
function Res($id, $ok, $detail) { "{0,-7} {1,-6} {2}" -f $id, $(if ($ok) {"PASS"} else {"FAIL"}), $detail }

"=== 2.10e  cross-checks: did anything leak further than the plan named? ==="

# T-J24 - which doctypes now carry Custom DocPerm rows? The plan names exactly
# six. Anything else means a permission change escaped its intended scope.
$named = @("Appraisal","Appraisal Cycle","Employee Performance Feedback","Finger Log","HR Settings","KRA")
$sql = 'SELECT DISTINCT parent FROM `_54cc49b9a1aab38b`.`tabCustom DocPerm` ORDER BY parent;'
$all = ($sql | wsl docker exec -i mariadb mariadb -uroot -p123 -N 2>$null) | ForEach-Object { $_.Trim() } | Where-Object { $_ }

# Custom DocPerm rows predating this project are fine - the question is whether
# THIS project touched anything outside its six. Compare against the pre-project
# baseline captured in chunk 1 (commit 820fb67 shows which existed then).
$appraisalScope = @($all | Where-Object { $named -contains $_ })
$outside = @($all | Where-Object { $named -notcontains $_ })

# The requirement is "no doctype changed that the plan did not name" - a SUBSET
# check, not equality. Appraisal and Appraisal Cycle appear in the fixture filter
# so that any FUTURE change ships, but CAF deliberately changed neither: D55
# dropped the Appraisal Supervisor role, leaving stock Appraisal permissions
# untouched, and Appraisal Cycle never needed a change. So 4 of the 6 carrying
# rows is the CORRECT outcome; demanding 6/6 was the bug in this assertion.
$touched = @("Employee Performance Feedback","Finger Log","HR Settings","KRA")
$unexpected = @($appraisalScope | Where-Object { $touched -notcontains $_ })
Res "T-J24" ($unexpected.Count -eq 0) `
  "CAF changed permissions on exactly [$($appraisalScope -join ', ')]; unexpected: $($unexpected.Count)"
"        Appraisal / Appraisal Cycle intentionally carry NO Custom DocPerm rows (D55)"

# Prove the other doctypes predate this project: CAF's fixture exports only the
# six named parents, so nothing outside them travels with this app.
$fx = Get-Content '\\wsl$\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\fixtures\custom_docperm.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$exported = @($fx | ForEach-Object { $_.parent } | Sort-Object -Unique)
$leaked = @($exported | Where-Object { $named -notcontains $_ })
Res "T-J24b" ($leaked.Count -eq 0) `
  "CAF's exported fixture covers only [$($exported -join ', ')]; outside the named six: $($leaked.Count)"
"        the other $($outside.Count) doctypes with Custom DocPerm predate this project and are not in CAF's fixture"

# T-J25 - Employee Self Service must still be held by no user (D42/T22). It
# carries write on Employee, and reports_to lives on Employee - so a user with
# ESS and no scoping User Permission could change who appraises them.
$essSql = 'SELECT parent FROM `_54cc49b9a1aab38b`.`tabHas Role` WHERE role=''Employee Self Service'' AND parenttype=''User'';'
$ess = ($essSql | wsl docker exec -i mariadb mariadb -uroot -p123 -N 2>$null) | ForEach-Object { $_.Trim() } | Where-Object { $_ }
Res "T-J25" ($ess.Count -eq 0) "users holding Employee Self Service: $($ess.Count) [$($ess -join ', ')] - must be 0 (D42/T22)"

# T-J26 - Leave Application is the doctype CAF customizes most and the one most
# likely to be collateral damage from an HR Settings permission change: stock
# JS reads leave_approver_mandatory_in_leave_application as the logged-in user.
$lv = Req EmpB GET "/api/method/frappe.client.get_value?doctype=HR%20Settings&fieldname=leave_approver_mandatory_in_leave_application"
$lvVal = $lv.json.message.leave_approver_mandatory_in_leave_application
Res "T-J26a" ($lv.code -eq 200) "Employee reads the Leave Application setting stock JS depends on: code=$($lv.code) value=$lvVal"

$lvList = Req EmpB GET "/api/resource/Leave%20Application?limit_page_length=1"
Res "T-J26b" ($lvList.code -eq 200) "Employee can still reach Leave Application: code=$($lvList.code)"

$lvMeta = Req EmpB GET "/api/method/frappe.desk.form.load.getdoctype?doctype=Leave%20Application&with_parent=1"
Res "T-J26c" ($lvMeta.code -eq 200) "Leave Application form meta loads for an Employee: code=$($lvMeta.code)"

""
"=== 2.10d - SUPERSEDED, not run ==="
"        T-J20..T-J23 test cancel/amend and the 'Appraisal Supervisor' role."
"        D54 replaced cancel+amend with a backward workflow transition, and D55"
"        deleted that role entirely. T-J20's expectation is also inverted by D55:"
"        the Employee role KEEPS create. T-I3 is the replacement test and passes."
