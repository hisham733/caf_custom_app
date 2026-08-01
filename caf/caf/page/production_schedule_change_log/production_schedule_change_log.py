import frappe
from frappe import _


@frappe.whitelist()
def get_change_log_for_date(date):
    """Return all Schedule Change Log entries for a given date, newest first."""
    logs = frappe.get_all(
        "Schedule Change Log",
        filters={"day": date},
        fields=[
            "name", "change_datetime", "changed_by", "action_type",
            "day", "workstation", "cook_round", "recipe_name",
            "dp_name", "summary", "changes_json",
        ],
        order_by="change_datetime desc",
        limit_page_length=500,
    )
    return {"entries": logs}
