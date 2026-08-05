# CAF Appraisal test suite - credentials TEMPLATE
# ================================================
# Copy to `credentials.ps1` (gitignored) and fill in the real tokens.
#
# ⚠️ NEVER commit the filled-in file. These are per-role API tokens, and the
# whole point of the suite is that it runs as a REAL role - Administrator
# bypasses every permission check, so a probe run as Administrator passes
# identically against a correct model and a completely broken one.
#
# Generate a token for a user:
#   POST /api/method/frappe.core.doctype.user.user.generate_keys  {"user": "..."}
# ⚠️ generate_keys REGENERATES an existing secret. Never call it for
# Administrator - that invalidates the protocol's own token mid-session.
#
# The dev-site values live in test_fixture_credentials.md, outside this repo.

$CAF_SITE_URL = "http://development.localhost:8000"

$CAF_TOKENS = @{
  # HR Manager - may appraise anyone (BR3)
  HRMgr  = "<api_key>:<api_secret>"

  # mid supervisor - has direct reports, and a supervisor ABOVE him. The case a
  # role-only design gets wrong.
  SupA   = "<api_key>:<api_secret>"

  # leaf employee - reports to SupA, supervises nobody
  EmpB   = "<api_key>:<api_secret>"

  # senior supervisor - two levels above EmpB, proves subtree read
  SupC   = "<api_key>:<api_secret>"

  # out-of-subtree control - sibling of SupA. SupA must NEVER see them.
  EmpD   = "<api_key>:<api_secret>"

  # HR User - permlevel probes; holds no permlevel-1 row
  HRUser = "<api_key>:<api_secret>"

  # Administrator - used ONLY where a test explicitly needs a bypassing
  # identity, and always labelled as such in the output
  Admin  = "<api_key>:<api_secret>"
}

# Employee records the suite asserts against
$CAF_EMP = @{
  A = "HR-EMP-00024"   # mid supervisor
  B = "HR-EMP-00185"   # leaf
  C = "HR-EMP-00016"   # senior supervisor
  D = "HR-EMP-00022"   # out-of-subtree
  HR = "HR-EMP-00003"  # HR Manager
}
