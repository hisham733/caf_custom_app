from frappe import _


def get_data(data=None):
	return {
		"fieldname": "task",
		"non_standard_fieldnames":{
			"ToDo": "reference_name",
			"Stock Entry": "custom_task",
		},
		"transactions": [
			{"label": _("Activity"), "items": ["Timesheet"]},
			{"label": _("Traceability"), "items": ["ToDo","Expense Claim","Stock Entry"]},
		],


	}
