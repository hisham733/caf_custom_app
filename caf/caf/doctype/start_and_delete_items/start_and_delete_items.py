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
		if not self.custom_is_default:
			frappe.throw("Custom Is Default must be active when creating a new record.")
		
		# Then check uniqueness
		existing = frappe.get_all(
			self.doctype,
			filters={
					"custom_is_default": 1,
				"name": ["!=", self.name]
			},
			limit=1
		)
		if existing:
			frappe.throw(
				"There is already a record marked as Default. Only one record can have Custom Is Default active."
			)

@frappe.whitelist()
def create_new_version(docname):
    """
    Manually duplicate the record, including child tables
    """
    # Get old doc
    old_doc = frappe.get_doc("start and delete items", docname)

    # Uncheck old default
    old_doc.custom_is_default = 0
    old_doc.save(ignore_permissions=True)

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
            new_doc.set(fieldname, child_rows)
        else:
            new_doc.set(fieldname, old_doc.get(fieldname))

    # Set new default
    new_doc.custom_is_default = 1

    # Insert new record
    new_doc.insert(ignore_permissions=True)

    return new_doc.name
