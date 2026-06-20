from frappe import _


def get_data(data=None):
    return {
        "fieldname": "work_order",
        "non_standard_fieldnames": {
            "Batch": "reference_name",
            "Quality Review": "custom_work_order",
            "Weight Record": "custom_work_order",
        },
        "transactions": [
            {
                "label": _("Transactions"),
                "items": ["Stock Entry", "Job Card", "Pick List", "Weight Record"],
            },
            {
                "label": _("Reference"),
                "items": ["Serial No", "Batch", "Material Request", "Quality Review"],
            },
        ],
    }
