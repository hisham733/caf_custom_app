"""CAF — helpers for the stock organisational chart.

The stock chart (hrms) renders one card per employee with name/title/connections
only. This module feeds the department map the CAF client script uses to paint
each card's background by department (no department = no background).
"""

import frappe


@frappe.whitelist()
def get_employee_departments():
    """{employee_name: department} for active employees.

    Runs as the session user, so it returns exactly the employees that user may
    see — the same visibility the chart itself has.
    """
    rows = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "department"],
    )
    return {r.name: r.department or "" for r in rows}
