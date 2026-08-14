"""Side quest — data alignment: report_to/leave_approver fill, user accounts,
Leave Approver role cleanup, display-fix fixtures. TEST SERVER ONLY.

    bench --site development.localhost execute caf.tests.workflow_gaps.data_align.run --args mode
    mode in: meta_check, apply_display, fill_dry, fill_apply, accounts_dry,
             accounts_apply, roles_dry, roles_apply, verify

Dry-run modes print the change list and change NOTHING.
"""

import csv
import re

import frappe
from frappe.utils.password import update_password

CSV_PATH = "/workspace/development/frappe-bench/sites/employeewithreport_to.csv"
TEMP_PW = "abc@123"
LA_ROLE = "Leave Approver"
SKIP_IDS = {"HR-EMP-00128"}   # Ow Yong Suit Chun - left (MG, 2026-08-14)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _slug(email_name):
    s = re.sub(r"[^a-z0-9]+", ".", email_name.lower()).strip(".")
    return f"{s}@caffood.com"


def _csv():
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _emp_map():
    emps = frappe.get_all(
        "Employee",
        fields=["name", "employee_name", "user_id", "company_email", "status",
                "reports_to", "leave_approver", "caf_reports_to_nobody"],
    )
    by_id = {e["name"]: e for e in emps}
    by_name = {}
    for e in emps:
        by_name.setdefault(_norm(e["employee_name"]), []).append(e)
    return by_id, by_name


def _existing_users():
    return {u["name"] for u in frappe.get_all("User", fields=["name"])}


def meta_check():
    meta = frappe.get_meta("Employee")
    for f in ("leave_approver", "reports_to"):
        df = meta.get_field(f)
        print(f"{f}: type={df.fieldtype} options={df.options} "
              f"fetch_from={df.fetch_from} fetch_if_empty={df.fetch_if_empty}")


def apply_display():
    # fetch_from lives on a COMPANION field, not on the Link itself
    # (Frappe: "Fetch From can't be self-referential")
    for fname, source, label in (
        ("leave_approver", "leave_approver.full_name", "Leave Approver Name"),
        ("reports_to", "reports_to.employee_name", "Reports To Name"),
    ):
        target = fname + "_name"
        name = f"Employee-{target}"
        if frappe.db.exists("Custom Field", name):
            cf = frappe.get_doc("Custom Field", name)
        else:
            cf = frappe.get_doc({
                "doctype": "Custom Field", "dt": "Employee",
                "fieldname": target, "label": label,
                "fieldtype": "Data", "read_only": 1,
                "insert_after": fname,
            })
        cf.fetch_from = source
        cf.fetch_if_empty = 1
        cf.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Employee")
    print("applied companion fields. run: reload-doctype Employee, then meta_check again")


def fill_plan():
    by_id, by_name = _emp_map()
    plan, problems = [], []
    for r in _csv():
        eid = r["ID"].strip()
        if eid in SKIP_IDS:
            plan.append((eid, "SKIP-left", "", ""))
            continue
        e = by_id.get(eid)
        if not e:
            problems.append((eid, "missing on dev"))
            continue
        if e["status"] != "Active":
            problems.append((eid, f"status={e['status']}"))
            continue
        rt = r["report_to"].strip()
        if rt.lower() == "root":
            plan.append((eid, "ROOT", "", ""))
            continue
        matches = by_name.get(_norm(rt))
        if not matches or len(matches) > 1:
            problems.append((eid, f"report_to '{rt}' unmatched/ambiguous"))
            continue
        mgr = matches[0]
        plan.append((eid, "SET", mgr["name"], mgr["user_id"] or ""))
    return plan, problems


def fill_dry():
    plan, problems = fill_plan()
    print(f"planned writes: {len(plan)}")
    for eid, action, rt, la in plan:
        print(f"  {eid:15s} {action:10s} reports_to={rt:16s} leave_approver={la}")
    print(f"problems: {len(problems)}")
    for p in problems:
        print(f"  {p}")


def fill_apply():
    plan, problems = fill_plan()
    done = 0
    for eid, action, rt, la in plan:
        if action == "ROOT":
            frappe.db.set_value("Employee", eid,
                                {"reports_to": None, "caf_reports_to_nobody": 1})
        elif action == "SKIP-left":
            continue
        else:
            frappe.db.set_value("Employee", eid, {
                "reports_to": rt,
                "leave_approver": la or None,
            })
        done += 1
    frappe.db.commit()
    print(f"applied {done} rows; problems: {len(problems)}")
    for p in problems:
        print(f"  PROBLEM {p}")


def accounts_plan():
    by_id, _ = _emp_map()
    users = _existing_users()
    plan, problems = [], []
    for eid, e in by_id.items():
        if e["status"] != "Active":
            continue
        if e["user_id"]:
            continue
        row = next((r for r in _csv() if r["ID"].strip() == eid), None)
        email = (row and row["User ID"].strip()) or e["company_email"] or None
        if email and email in users:
            plan.append((eid, e["employee_name"], email, "LINK-EXISTING"))
            continue
        if not email:
            email = _slug(e["employee_name"])
        i = 2
        base = email
        while email in users:
            email = f"{base.split('@')[0]}.{i}@{base.split('@')[1]}"
            i += 1
        plan.append((eid, e["employee_name"], email, "CREATE"))
    return plan, problems


def accounts_dry():
    plan, problems = accounts_plan()
    print(f"accounts to create/link: {len(plan)}")
    for eid, name, email, action in plan:
        print(f"  {eid:15s} {name:40s} -> {email:45s} [{action}]")


def accounts_apply():
    plan, problems = accounts_plan()
    made = 0
    for eid, name, email, action in plan:
        # order matters: link Employee.user_id FIRST (Employee-role auto-strip)
        frappe.db.set_value("Employee", eid, "user_id", email)
        if action == "LINK-EXISTING":
            u = frappe.get_doc("User", email)
            if "Employee" not in [r.role for r in u.get("roles")]:
                u.add_roles("Employee")
            update_password(email, TEMP_PW)
            made += 1
            continue
        u = frappe.get_doc({
            "doctype": "User", "email": email,
            "first_name": name, "user_type": "System User",
            "send_welcome_email": 0,
            "roles": [{"role": "Employee"}],
        })
        u.flags.ignore_permissions = True
        u.insert(ignore_permissions=True)
        update_password(email, TEMP_PW)
        made += 1
    frappe.db.commit()
    print(f"created/linked {made} accounts (temp password set server-side)")
    print(f"problems: {len(problems)}")
    for p in problems:
        print(f"  {p}")


def roles_plan():
    approvers = {
        r[0] for r in frappe.db.sql(
            """SELECT DISTINCT leave_approver FROM tabEmployee
               WHERE status='Active' AND leave_approver IS NOT NULL
               AND leave_approver != ''""")
    }
    hrms = {r[0] for r in frappe.db.sql(
        """SELECT parent FROM `tabHas Role`
           WHERE parenttype='User' AND role='HR Manager'""")}
    directors = {"ow.yong@caffood.com", "yow.kwee@caffood.com"}
    keep = approvers | hrms | directors
    holders = {r[0] for r in frappe.db.sql(
        """SELECT parent FROM `tabHas Role`
           WHERE parenttype='User' AND role=%s""", (LA_ROLE,))}
    remove = holders - keep
    grant = keep - holders
    return sorted(keep), sorted(remove), sorted(grant)


def roles_dry():
    keep, remove, grant = roles_plan()
    print(f"KEEP {LA_ROLE} ({len(keep)}):")
    for u in keep:
        print(f"   {u}")
    print(f"REMOVE {LA_ROLE} ({len(remove)}):")
    for u in remove:
        print(f"   {u}")
    print(f"GRANT {LA_ROLE} ({len(grant)}):")
    for u in grant:
        print(f"   {u}")


def roles_apply():
    keep, remove, grant = roles_plan()
    for u in remove:
        frappe.get_doc("User", u).remove_roles(LA_ROLE)
    for u in grant:
        frappe.get_doc("User", u).add_roles(LA_ROLE)
    frappe.db.commit()
    print(f"removed {len(remove)}, granted {len(grant)}")


def verify():
    out = frappe.db.sql("""
        SELECT
          (SELECT COUNT(*) FROM tabEmployee
             WHERE status='Active' AND (user_id IS NULL OR user_id='')) AS no_account,
          (SELECT COUNT(*) FROM tabEmployee
             WHERE status='Active' AND (reports_to IS NULL OR reports_to='')
               AND ifnull(caf_reports_to_nobody,0)=0) AS no_reports_to,
          (SELECT COUNT(DISTINCT leave_approver) FROM tabEmployee
             WHERE status='Active' AND leave_approver IS NOT NULL
               AND leave_approver != '') AS distinct_approvers
    """, as_dict=True)[0]
    print(out)
    return out


def run(mode="verify"):
    funcs = {
        "meta_check": meta_check,
        "apply_display": apply_display,
        "fill_dry": fill_dry,
        "fill_apply": fill_apply,
        "accounts_dry": accounts_dry,
        "accounts_apply": accounts_apply,
        "roles_dry": roles_dry,
        "roles_apply": roles_apply,
        "verify": verify,
    }
    return funcs[mode]()
