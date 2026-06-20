from frappe import _


def get_data(data=None):
	return {
		"fieldname": "custom_daily_production_id",
		"non_standard_fieldnames": {
			"Stock Entry":"custom_daily_production_name",
		},
		# "internal_links": {
		# 	"Sales Order": ["items", "sales_order"],
		# 	"Project": ["items", "project"],
		# 	"Cost Center": ["items", "cost_center"],
		# },
		"transactions": [
			{
				"label": _("Reference"),
				"items": ["Material Request","Production Plan","Stock Entry"],
			},
			# {"label": _("Stock"), "items": ["Stock Entry", "Purchase Receipt", "Pick List"]},
			# {"label": _("Manufacturing"), "items": ["Work Order"]},
			# {"label": _("Internal Transfer"), "items": ["Sales Order"]},
			# {"label": _("Accounting Dimensions"), "items": ["Project", "Cost Center"]},
		],
	}
