# Copyright (c) 2025, hisham and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class startanddeleteitems(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from caf.caf.doctype.delet.delet import delet
		from caf.caf.doctype.start.start import start
		from frappe.types import DF

		amended_from: DF.Link | None
		delet: DF.Table[delet]
		naming_series: DF.Data | None
		start: DF.Table[start]
	# end: auto-generated types
	pass
	def validate(self):
		if (self.max_rounds or 0) < (self.default_rounds or 3):
			frappe.throw(
				"Max Rounds ({}) must be greater than or equal to Default Rounds ({}).".format(
					self.max_rounds, self.default_rounds
				)
			)

		if not self.is_default:
			frappe.throw("Is Default must be active when creating a new record.")
		
		# Then check uniqueness
		existing = frappe.get_all(
			self.doctype,
			filters={
					"is_default": 1,
				"name": ["!=", self.name]
			},
			limit=1
		)
		if existing:
			frappe.throw(
				"There is already a record marked as Default. Only one record can be the default."
			)

@frappe.whitelist()
def create_new_version(docname):
    """
    Manually duplicate the record, including child tables
    """
    # Get old doc
    old_doc = frappe.get_doc("start and delete items", docname)

    # Uncheck old default (use db_set to bypass validate)
    frappe.db.set_value("start and delete items", docname, "is_default", 0)

    # Create new document
    new_doc = frappe.new_doc("start and delete items")

    # Copy all fields except meta fields
    skip_fields = ["name", "creation", "modified", "owner", "modified_by", "doctype", "idx"]
    for field in old_doc.meta.fields:
        fieldname = field.fieldname
        if fieldname in skip_fields:
            continue

        # Handle child tables
        if field.fieldtype == "Table":
            child_rows = []
            for row in old_doc.get(fieldname):
                child_rows.append(row.as_dict())
            # Fallback: query child table directly for old custom_ fields
            if not child_rows:
                child_rows = frappe.get_all(
                    field.options,
                    filters={"parent": docname, "parenttype": old_doc.doctype},
                    order_by="idx asc",
                )
            new_doc.set(fieldname, child_rows)
        else:
            new_doc.set(fieldname, old_doc.get(fieldname))

    # Set new default
    new_doc.is_default = 1

    # Insert new record
    new_doc.insert(ignore_permissions=True)

    return new_doc.name
