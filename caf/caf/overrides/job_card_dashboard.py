import frappe
from frappe import _

def get_data(data=None):  # <-- THIS IS REQUIRED
	return {
		"fieldname": "job_card",
		"non_standard_fieldnames": {
			"Quality Inspection": "reference_name",
			"Quality Review": "custom_job_card"
		},
		"transactions": [
			{"label": _("Transactions"), "items": ["Material Request", "Stock Entry"]},
			{"label": _("Reference"), "items": ["Quality Inspection"]},
			{"label": _("QI"), "items": ["Quality Review"]}
		],
	}